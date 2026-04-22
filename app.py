"""
app.py — Backend Flask para Daiver Control CUN
Integra el dashboard web con el robot Unitree Go2 Air via WebRTC.
"""

import sys
import os
import asyncio
import math
import threading
import time

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from flask_socketio import SocketIO, emit

from config.config import ROBOT_IP
from yolo_detector import detector as yolo_detector

app = Flask(__name__, static_folder='website', template_folder='website')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ════════════════════════════════════════════════════════
#  ESTADO GLOBAL DEL ROBOT
# ════════════════════════════════════════════════════════

robot_state = {
    "connected": False,
    "ip": ROBOT_IP,
    "battery": 0,
    "speed": 0.0,
    "mode": "Standby",
    "routine_running": False,
    "routine_name": None
}

# Proximity-sensor mode: when enabled we turn on the Go2 utlidar, subscribe
# to its voxel_map_compressed topic, decode the point cloud (native decoder),
# and compute the nearest forward-facing distance in meters. If anything is
# under `stop_distance_m` we emit `proximity_alert` and slam Move=0.
#
# Lidar points come in the robot's local frame: +x forward, +y left, +z up.
# We only look at points in a forward cone (x > 0, |y| < ~0.6, z near body)
# so the system doesn't trip on the ground or the robot's own body.
proximity_sensor = {
    "enabled": False,
    # Umbrales ajustados: solo paramos cuando algo está MUY cerca directamente
    # al frente (30 cm) y el robot se está moviendo hacia allá.
    # Cono estrecho (±15 cm) para que pase por pasillos sin pararse.
    "stop_distance_m": 0.30,
    "clear_distance_m": 0.55,       # libera histéresis si >55 cm
    "forward_cone_y_m": 0.15,       # ±15 cm de ancho (pasa por pasillos ~30 cm)
    "min_z_m": 0.12,                # ignora el suelo (y pies de sillas bajos)
    "max_z_m": 0.60,                # ignora el techo
    "min_forward_vel_mps": 0.05,    # solo alerta si va hacia adelante
    "cmd_fresh_s": 0.7,             # cuán reciente debe ser el último Move
    "_last_alert_ts": 0.0,
    "_alert_active": False,         # en ON: ya alertamos, esperamos que salga
    "_clear_since": 0.0,            # cuándo empezó a estar libre (para histéresis)
    "_subscribed": False,
    "_subscribed_topics": [],
    "_last_distance": None,
    "_last_source": None,
    # Último comando de movimiento conocido.
    "_last_cmd_x": 0.0,
    "_last_cmd_ts": 0.0,
    # Ventana de gracia de FORCE: mientras time.time() < _force_until,
    # el sensor no emite alertas ni manda Move=0 — el operador ya aceptó
    # el riesgo sosteniendo Shift / boton Override en el frontend.
    "_force_until": 0.0,
    # Pose del robot en el frame del mapa del lidar.
    "_pose_x": 0.0,
    "_pose_y": 0.0,
    "_pose_z": 0.0,
    "_pose_yaw": 0.0,
    "_pose_valid": False,
    # Bookkeeping para enviar paredes al frontend (subsampled).
    "_last_points_emit_ts": 0.0,
}

# Conexion y pub_sub globales
robot_connection = None
robot_pub_sub = None
event_loop = None
loop_thread = None
routine_task = None
stop_routine_flag = False

# Compatibilidad entre nombres de comando usados en el proyecto
# y nombres disponibles en distintas versiones del SDK.
SPORT_CMD_COMPAT_ALIASES = {
    "SitDown": ("SitDown", "Sit", "StandDown"),
    "RiseSit": ("RiseSit", "StandUp", "Standup", "StandOut"),
    "RecoveryStand": ("RecoveryStand",),
    "StandDown": ("StandDown", "SitDown", "Sit"),
}


# ════════════════════════════════════════════════════════
#  ASYNCIO EVENT LOOP EN THREAD SEPARADO
# ════════════════════════════════════════════════════════

def start_event_loop(loop):
    """Ejecuta el event loop de asyncio en un thread dedicado."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def ensure_event_loop():
    """Crea el event loop si no existe."""
    global event_loop, loop_thread
    if event_loop is None or not event_loop.is_running():
        event_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=start_event_loop, args=(event_loop,), daemon=True)
        loop_thread.start()


def run_async(coro):
    """Ejecuta una coroutine en el event loop y retorna el resultado."""
    ensure_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, event_loop)
    return future.result(timeout=30)


def run_async_no_wait(coro):
    """Ejecuta una coroutine sin esperar resultado (para rutinas largas)."""
    ensure_event_loop()
    return asyncio.run_coroutine_threadsafe(coro, event_loop)


# ════════════════════════════════════════════════════════
#  FUNCIONES DE ROBOT (reusan la logica de los scripts)
# ════════════════════════════════════════════════════════

def emit_log(log_type, message):
    """Emite un log al frontend via SocketIO."""
    socketio.emit('log', {'type': log_type, 'message': message})


def emit_state_update():
    """Emite el estado actual al frontend."""
    socketio.emit('state_update', robot_state)


def resolve_sport_cmd_key(requested_key, sport_cmd_dict):
    """Resuelve aliases de comando para soportar diferentes versiones de SDK."""
    if requested_key in sport_cmd_dict:
        return requested_key

    for alias in SPORT_CMD_COMPAT_ALIASES.get(requested_key, ()):
        if alias in sport_cmd_dict:
            return alias

    return None


async def _go2_video_callback(track):
    """Callback WebRTC: lee frames del Go2 y los pasa al detector YOLO.

    aiortc entrega la track; este loop hace track.recv() hasta que se cierre.
    Los frames se convierten a BGR y se empujan a la cola del detector.
    Si el detector no esta corriendo, push_frame() es no-op.
    """
    emit_log('info', 'Canal de video del Go2 abierto, recibiendo frames...')
    try:
        while True:
            frame = await track.recv()
            try:
                bgr = frame.to_ndarray(format="bgr24")
            except Exception as exc:
                emit_log('warning', f'Frame del Go2 invalido: {exc}')
                continue
            yolo_detector.push_frame(bgr)
    except Exception as exc:
        emit_log('warning', f'Canal de video del Go2 cerrado: {exc}')


async def robot_connect(ip):
    """Conecta al robot via WebRTC y habilita canal de video para YOLO."""
    global robot_connection, robot_pub_sub

    from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod

    emit_log('info', f'Conectando a {ip}...')

    robot_connection = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ip
    )

    await robot_connection.connect()
    robot_pub_sub = robot_connection.datachannel.pub_sub

    await asyncio.sleep(2)

    # Habilita canal de video del Go2 y registra callback para YOLO.
    try:
        if hasattr(robot_connection, "video") and robot_connection.video is not None:
            robot_connection.video.add_track_callback(_go2_video_callback)
            robot_connection.video.switchVideoChannel(True)
            emit_log('success', 'Canal de video del Go2 habilitado')
    except Exception as exc:
        emit_log('warning', f'No se pudo habilitar video del Go2: {exc}')

    # Balance Stand inicial
    from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
    await robot_pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    robot_state["connected"] = True
    robot_state["ip"] = ip
    robot_state["mode"] = "Balance Stand"
    emit_log('success', f'Conexion establecida con {ip}')
    emit_state_update()


async def robot_disconnect():
    """Desconecta del robot. Apaga video y detiene YOLO si usaba la camara del robot."""
    global robot_connection, robot_pub_sub

    if yolo_detector.is_running() and yolo_detector.status().get("source") == "robot":
        yolo_detector.stop()
        emit_log('info', 'YOLO detenido (robot desconectando)')

    if robot_connection:
        try:
            if hasattr(robot_connection, "video") and robot_connection.video is not None:
                robot_connection.video.switchVideoChannel(False)
        except Exception:
            pass
        await robot_connection.disconnect()
        robot_connection = None
        robot_pub_sub = None

    robot_state["connected"] = False
    robot_state["mode"] = "Standby"
    emit_log('info', 'Desconectado del robot')
    emit_state_update()


async def robot_send_command(api_cmd, parameter=None):
    """Envia un comando individual al robot."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC

    resolved_cmd = resolve_sport_cmd_key(api_cmd, SPORT_CMD)
    if not resolved_cmd:
        emit_log('error', f"Comando no soportado por el SDK actual: {api_cmd}")
        return False

    if resolved_cmd != api_cmd:
        emit_log('warning', f"Compatibilidad SDK: '{api_cmd}' -> '{resolved_cmd}'")

    payload = {"api_id": SPORT_CMD[resolved_cmd]}
    if parameter:
        payload["parameter"] = parameter

    await robot_pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        payload
    )
    return True


async def robot_mover(x, y, z, duracion):
    """Movimiento continuo durante X segundos (re-envia cada 0.2s)."""
    if not robot_pub_sub:
        return

    from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC

    inicio = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - inicio < duracion:
        if stop_routine_flag:
            break
        await robot_pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z}
            }
        )
        await asyncio.sleep(0.2)


async def robot_stop():
    """Detiene el movimiento."""
    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(1)


async def robot_soft_brake(cycles=4, step_delay=0.12):
    """
    Frena de forma progresiva enviando varios comandos Move=0.
    Reduce tirones cuando se entra/sale de acciones cinematicas.
    """
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    cycles = max(1, int(cycles))
    for _ in range(cycles):
        ok = await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        if not ok:
            return False
        await asyncio.sleep(step_delay)

    return True


async def robot_prepare_stable_action(balance_wait=1.1):
    """Secuencia comun para iniciar acciones de forma mas suave."""
    if not await robot_soft_brake(cycles=4, step_delay=0.12):
        return False

    ok = await robot_send_command("BalanceStand")
    if not ok:
        return False

    await asyncio.sleep(balance_wait)
    return True


async def robot_scrape_safe():
    """Ejecuta Scrape real con pre/post estabilizacion para reducir golpes."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    # Entrada suave con frenado progresivo + equilibrio.
    ok = await robot_prepare_stable_action(balance_wait=1.35)
    if not ok:
        return False

    # Raspar real.
    ok = await robot_send_command("Scrape")
    if not ok:
        return False
    await asyncio.sleep(3.2)

    # Salida suave y recuperacion de equilibrio.
    ok = await robot_soft_brake(cycles=5, step_delay=0.12)
    if not ok:
        return False

    ok = await robot_send_command("BalanceStand")
    if not ok:
        return False
    await asyncio.sleep(1.6)

    return True


async def robot_heart_safe():
    """Ejecuta FingerHeart con transicion suave para evitar movimientos bruscos."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    # Entrada suave antes del gesto.
    ok = await robot_prepare_stable_action(balance_wait=1.25)
    if not ok:
        return False

    # Corazon real.
    ok = await robot_send_command("FingerHeart")
    if not ok:
        return False
    await asyncio.sleep(3.8)

    # Salida suave para evitar rebote de postura.
    ok = await robot_soft_brake(cycles=4, step_delay=0.12)
    if not ok:
        return False

    ok = await robot_send_command("BalanceStand")
    if not ok:
        return False
    await asyncio.sleep(1.3)

    return True


async def robot_sit_safe():
    """Sentarse con secuencia estable y compatibilidad de comando."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    ok = await robot_send_command("SitDown")
    if not ok:
        return False

    await asyncio.sleep(2.2)
    return True


async def robot_rise_safe():
    """Levantarse desde sentado con estabilizacion posterior."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)

    ok = await robot_send_command("RiseSit")
    if not ok:
        return False

    await asyncio.sleep(2.2)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(1.0)
    return True


async def robot_recovery_safe():
    """Recuperarse con comando dedicado y cierre en equilibrio."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)

    ok = await robot_send_command("RecoveryStand")
    if not ok:
        return False

    await asyncio.sleep(2.6)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(1.0)
    return True


async def robot_lie_safe():
    """Acostarse con secuencia estable y compatibilidad entre versiones SDK."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    ok = await robot_send_command("StandDown")
    if not ok:
        return False

    await asyncio.sleep(2.4)
    return True


async def robot_wiggle_safe():
    """Meneo estable por oscilaciones cortas de yaw (fallback robusto)."""
    if not robot_pub_sub:
        emit_log('error', 'No hay conexion activa')
        return False

    # Postura inicial estable.
    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    # Oscilacion corta izquierda/derecha para simular meneo.
    pattern = [0.75, -0.75, 0.75, -0.75, 0.6, -0.6]
    for z in pattern:
        await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": z})
        await asyncio.sleep(0.18)

    # Frenado y retorno a equilibrio.
    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)
    return True


# ════════════════════════════════════════════════════════
#  RUTINAS PREDEFINIDAS
# ════════════════════════════════════════════════════════

async def rutina_patrullaje():
    """Rutina de patrullaje basada en 05_rutina1.py."""
    global stop_routine_flag
    stop_routine_flag = False

    robot_state["routine_running"] = True
    robot_state["routine_name"] = "Patrullaje"
    emit_state_update()

    steps = [
        ("Avanzar 5.5m", 0.5, 0.0, 0.0, 11),
        ("Giro izquierda 180", 0.0, 0.0, 1.0, 1.8),
        ("Avanzar 5.0m", 0.5, 0.0, 0.0, 10),
        ("Giro izquierda 180", 0.0, 0.0, 1.0, 2),
        ("Avanzar 3.75m", 0.5, 0.0, 0.0, 7.5),
        ("Giro izquierda 180", 0.0, 0.0, 1.0, 1.7),
        ("Avanzar 4.8m (retorno)", 0.3, 0.0, 0.0, 16),
        ("Giro izquierda 180 (cierre)", 0.0, 0.0, 1.0, 1.7),
    ]

    try:
        for i, (desc, x, y, z, dur) in enumerate(steps, 1):
            if stop_routine_flag:
                emit_log('warning', 'Rutina detenida por el usuario')
                break
            emit_log('info', f'[STEP {i}/{len(steps)}] {desc}')
            await robot_mover(x, y, z, dur)
            await robot_stop()

        if not stop_routine_flag:
            emit_log('success', 'Rutina de patrullaje completada')
    except Exception as e:
        emit_log('error', f'Error en rutina: {e}')
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


async def rutina_salto():
    """Rutina de salto basada en 07_rutinaSalto.py."""
    global stop_routine_flag
    stop_routine_flag = False

    robot_state["routine_running"] = True
    robot_state["routine_name"] = "Salto"
    emit_state_update()

    try:
        steps_info = [
            "Balance Stand",
            "Avanzar 2m (impulso)",
            "Salto frontal",
            "Recuperar equilibrio",
            "Avanzar 2m",
            "Segundo salto frontal",
            "Recuperar equilibrio",
            "Giro 180",
            "Regresar 4m",
            "Salto final",
            "Balance Stand final"
        ]

        async def do_steps():
            # Step 1 - Balance Stand
            emit_log('info', f'[STEP 1/11] {steps_info[0]}')
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 2 - Avanzar 2m
            emit_log('info', f'[STEP 2/11] {steps_info[1]}')
            await robot_mover(0.4, 0.0, 0.0, 5)
            await robot_stop()
            if stop_routine_flag: return

            # Step 3 - Salto
            emit_log('info', f'[STEP 3/11] {steps_info[2]}')
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 4 - Recuperar
            emit_log('info', f'[STEP 4/11] {steps_info[3]}')
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 5 - Avanzar
            emit_log('info', f'[STEP 5/11] {steps_info[4]}')
            await robot_mover(0.4, 0.0, 0.0, 5)
            await robot_stop()
            if stop_routine_flag: return

            # Step 6 - Segundo salto
            emit_log('info', f'[STEP 6/11] {steps_info[5]}')
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 7 - Recuperar
            emit_log('info', f'[STEP 7/11] {steps_info[6]}')
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 8 - Giro 180
            emit_log('info', f'[STEP 8/11] {steps_info[7]}')
            await robot_mover(0.0, 0.0, 1.0, 1.8)
            await robot_stop()
            if stop_routine_flag: return

            # Step 9 - Regresar
            emit_log('info', f'[STEP 9/11] {steps_info[8]}')
            await robot_mover(0.4, 0.0, 0.0, 10)
            await robot_stop()
            if stop_routine_flag: return

            # Step 10 - Salto final
            emit_log('info', f'[STEP 10/11] {steps_info[9]}')
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if stop_routine_flag: return

            # Step 11 - Balance Stand final
            emit_log('info', f'[STEP 11/11] {steps_info[10]}')
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)

        await do_steps()

        if not stop_routine_flag:
            emit_log('success', 'Rutina de salto completada')
    except Exception as e:
        emit_log('error', f'Error en rutina: {e}')
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


async def rutina_exploracion():
    """Rutina de exploracion: avanza, observa, gira, repite."""
    global stop_routine_flag
    stop_routine_flag = False

    robot_state["routine_running"] = True
    robot_state["routine_name"] = "Exploracion"
    emit_state_update()

    try:
        directions = [0, 90, 180, 270]

        for i, angle in enumerate(directions):
            if stop_routine_flag:
                break

            emit_log('info', f'[EXPLORE {i+1}/4] Avanzar 3m')
            await robot_mover(0.4, 0.0, 0.0, 7.5)
            await robot_stop()

            if stop_routine_flag:
                break

            emit_log('info', f'[EXPLORE {i+1}/4] Giro 90 derecha')
            t_giro = (90 * math.pi / 180) / 1.0
            await robot_mover(0.0, 0.0, -1.0, t_giro)
            await robot_stop()

        if not stop_routine_flag:
            emit_log('success', 'Rutina de exploracion completada')
    except Exception as e:
        emit_log('error', f'Error en rutina: {e}')
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


# ════════════════════════════════════════════════════════
#  RUTAS FLASK — PAGINAS
# ════════════════════════════════════════════════════════

@app.route('/')
def index():
    return send_from_directory('website', 'index.html')


@app.route('/landing')
def landing():
    return send_from_directory('website', 'landing.html')


@app.route('/user-end')
@app.route('/user_end.hmtl')
def user_end():
    return send_from_directory('website', 'user_end.html')


@app.route('/control-remoto')
@app.route('/controlRemoto')
@app.route('/controlRemoto.html')
def control_remoto():
    return send_from_directory('website', 'controlRemoto.html')


@app.route('/autoroute')
@app.route('/auto-ruta')
@app.route('/autoroute.html')
def autoroute_page():
    return send_from_directory('website', 'autoroute.html')


@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory('website/css', filename)


@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory('website/js', filename)


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('website/assets', filename)


# ════════════════════════════════════════════════════════
#  API REST — CONEXION
# ════════════════════════════════════════════════════════

@app.route('/api/status')
def api_status():
    return jsonify(robot_state)


@app.route('/api/connect', methods=['POST'])
def api_connect():
    if robot_state["connected"]:
        return jsonify({"status": "error", "message": "Ya conectado"}), 400

    data = request.get_json() or {}
    ip = data.get('ip', ROBOT_IP)

    try:
        run_async(robot_connect(ip))
        return jsonify({"status": "ok", "message": f"Conectado a {ip}"})
    except Exception as e:
        robot_state["connected"] = False
        emit_state_update()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/disconnect', methods=['POST'])
def api_disconnect():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    try:
        global stop_routine_flag
        stop_routine_flag = True
        run_async(robot_disconnect())
        return jsonify({"status": "ok", "message": "Desconectado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ════════════════════════════════════════════════════════
#  API REST — COMANDOS DIRECTOS
# ════════════════════════════════════════════════════════

@app.route('/api/command', methods=['POST'])
def api_command():
    """Ejecuta un comando SPORT_CMD individual."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    data = request.get_json()
    cmd = data.get('command')
    parameter = data.get('parameter')

    valid_commands = [
        "Damp", "BalanceStand", "StopMove", "Move",
        "SwitchGait", "BodyHeight", "FootRaiseHeight", "SpeedLevel",
        "Hello", "Stretch", "RecoveryStand", "Euler",
        "SitDown", "StandDown", "RiseSit", "Pose", "Scrape",
        "FrontFlip", "FrontJump", "FrontPounce",
        "WiggleHips", "GetState", "EconomicGait",
        "Dance1", "Dance2", "FingerHeart"
    ]

    if cmd not in valid_commands:
        return jsonify({"status": "error", "message": f"Comando invalido: {cmd}"}), 400

    try:
        run_async(robot_send_command(cmd, parameter))
        emit_log('info', f'Comando ejecutado: {cmd}')
        return jsonify({"status": "ok", "command": cmd})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ════════════════════════════════════════════════════════
#  API REST — MOVIMIENTO CONTINUO
# ════════════════════════════════════════════════════════

@app.route('/api/move', methods=['POST'])
def api_move():
    """Envia un comando de movimiento (una sola vez, para control en tiempo real)."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    data = request.get_json()
    x = float(data.get('x', 0.0))
    y = float(data.get('y', 0.0))
    z = float(data.get('z', 0.0))

    # Limitar velocidades por seguridad
    x = max(-0.8, min(0.8, x))
    y = max(-0.5, min(0.5, y))
    z = max(-1.5, min(1.5, z))

    try:
        run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
        return jsonify({"status": "ok", "x": x, "y": y, "z": z})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop_move():
    """Detiene todo movimiento."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/emergency', methods=['POST'])
def api_emergency():
    """Parada de emergencia (Damp) — amortigua todos los motores."""
    global stop_routine_flag
    stop_routine_flag = True

    try:
        if robot_pub_sub:
            run_async(robot_send_command("Damp"))
        emit_log('warning', 'PARADA DE EMERGENCIA ACTIVADA')
        robot_state["mode"] = "Emergencia"
        emit_state_update()
        return jsonify({"status": "ok", "message": "Emergencia activada"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ════════════════════════════════════════════════════════
#  API REST — ACCIONES / POSES
# ════════════════════════════════════════════════════════

@app.route('/api/action', methods=['POST'])
def api_action():
    """Ejecuta una accion/pose predefinida."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    data = request.get_json()
    action = data.get('action')

    if action == "sit":
        try:
            ok = run_async(robot_sit_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar sentado"}), 500
            robot_state["mode"] = "SitDown"
            emit_log('info', 'Accion ejecutada: sit (sentado estabilizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "SitDown"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if action == "rise":
        try:
            ok = run_async(robot_rise_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar levantarse"}), 500
            robot_state["mode"] = "RiseSit"
            emit_log('info', 'Accion ejecutada: rise (levantarse estabilizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "RiseSit"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if action == "recovery":
        try:
            ok = run_async(robot_recovery_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar recuperarse"}), 500
            robot_state["mode"] = "RecoveryStand"
            emit_log('info', 'Accion ejecutada: recovery (recuperacion estabilizada)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "RecoveryStand"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if action == "lie":
        try:
            ok = run_async(robot_lie_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar acostarse"}), 500
            robot_state["mode"] = "StandDown"
            emit_log('info', 'Accion ejecutada: lie (acostarse estabilizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "StandDown"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # Scrape real con secuencia de estabilizacion para minimizar golpes.
    if action == "scrape":
        try:
            ok = run_async(robot_scrape_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar scrape"}), 500
            robot_state["mode"] = "Scrape"
            emit_log('info', 'Accion ejecutada: scrape (Scrape real estabilizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "Scrape"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if action == "wiggle":
        try:
            ok = run_async(robot_wiggle_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar meneo"}), 500
            robot_state["mode"] = "WiggleHips"
            emit_log('info', 'Accion ejecutada: wiggle (meneo estabilizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "WiggleHips"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if action == "heart":
        try:
            ok = run_async(robot_heart_safe())
            if not ok:
                return jsonify({"status": "error", "message": "No se pudo ejecutar corazon"}), 500
            robot_state["mode"] = "FingerHeart"
            emit_log('info', 'Accion ejecutada: heart (FingerHeart suavizado)')
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": "FingerHeart"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    action_map = {
        "stand": "BalanceStand",
        "sit": "SitDown",
        "lie": "StandDown",
        "rise": "RiseSit",
        "recovery": "RecoveryStand",
        "hello": "Hello",
        "stretch": "Stretch",
        "dance1": "Dance1",
        "dance2": "Dance2",
        "wiggle": "WiggleHips",
        "scrape": "Scrape",
        "heart": "FingerHeart",
        "frontflip": "FrontFlip",
        "frontjump": "FrontJump",
        "frontpounce": "FrontPounce",
    }

    cmd = action_map.get(action)
    if not cmd:
        return jsonify({"status": "error", "message": f"Accion invalida: {action}"}), 400

    try:
        ok = run_async(robot_send_command(cmd))
        if not ok:
            return jsonify({"status": "error", "message": f"No se pudo ejecutar comando: {cmd}"}), 500
        robot_state["mode"] = cmd
        emit_log('info', f'Accion ejecutada: {action} ({cmd})')
        emit_state_update()
        return jsonify({"status": "ok", "action": action, "command": cmd})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ════════════════════════════════════════════════════════
#  API REST — RUTINAS
# ════════════════════════════════════════════════════════

@app.route('/api/routine', methods=['POST'])
def api_routine():
    """Inicia una rutina predefinida (ejecuta en background)."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    if robot_state["routine_running"]:
        return jsonify({"status": "error", "message": f"Rutina '{robot_state['routine_name']}' en ejecucion"}), 400

    data = request.get_json()
    routine = data.get('routine')

    routine_map = {
        "patrol": rutina_patrullaje,
        "jump": rutina_salto,
        "explore": rutina_exploracion,
    }

    routine_fn = routine_map.get(routine)
    if not routine_fn:
        return jsonify({"status": "error", "message": f"Rutina invalida: {routine}"}), 400

    run_async_no_wait(routine_fn())
    emit_log('info', f'Rutina iniciada: {routine}')
    return jsonify({"status": "ok", "routine": routine})


@app.route('/api/routine/stop', methods=['POST'])
def api_routine_stop():
    """Detiene la rutina en ejecucion."""
    global stop_routine_flag
    stop_routine_flag = True
    emit_log('warning', 'Deteniendo rutina...')
    return jsonify({"status": "ok"})


# ════════════════════════════════════════════════════════
#  API REST — CONFIGURACION
# ════════════════════════════════════════════════════════

@app.route('/api/config/ip', methods=['POST'])
def api_update_ip():
    """Actualiza la IP del robot en config.py."""
    data = request.get_json() or {}
    new_ip = data.get('ip', '').strip()

    if not new_ip:
        return jsonify({"status": "error", "message": "IP vacia"}), 400

    config_path = os.path.join(os.path.dirname(__file__), 'config', 'config.py')
    try:
        with open(config_path, 'w') as f:
            f.write(f'ROBOT_IP = "{new_ip}"\n')
        robot_state["ip"] = new_ip
        emit_log('info', f'IP actualizada en config.py: {new_ip}')
        return jsonify({"status": "ok", "ip": new_ip})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/config', methods=['GET'])
def api_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'config.py')
    current_ip = ROBOT_IP
    try:
        with open(config_path, 'r') as f:
            content = f.read()
            import re
            match = re.search(r'ROBOT_IP\s*=\s*"([^"]+)"', content)
            if match:
                current_ip = match.group(1)
    except Exception:
        pass

    return jsonify({
        "robot_ip": current_ip,
        "commands": [
            "Damp", "BalanceStand", "StopMove", "Move",
            "SwitchGait", "BodyHeight", "Hello", "Stretch",
            "RecoveryStand", "Euler", "SitDown", "StandDown", "RiseSit",
            "Scrape", "FrontFlip", "FrontJump", "FrontPounce",
            "WiggleHips", "GetState", "EconomicGait",
            "Dance1", "Dance2", "FingerHeart"
        ],
        "actions": [
            "stand", "sit", "lie", "rise", "recovery", "hello", "stretch",
            "dance1", "dance2", "wiggle", "scrape", "heart",
            "frontflip", "frontjump", "frontpounce"
        ],
        "routines": ["patrol", "jump", "explore"]
    })


# ════════════════════════════════════════════════════════
#  API REST — YOLO (Vision por Computadora / Waypoints)
# ════════════════════════════════════════════════════════

@app.route('/api/yolo/status', methods=['GET'])
def api_yolo_status():
    """Devuelve estado del detector YOLO (corriendo, FPS, modelo, etc)."""
    return jsonify(yolo_detector.status())


@app.route('/api/yolo/start', methods=['POST'])
def api_yolo_start():
    """Inicia inferencia YOLO. Source por defecto: 'robot' (camara del Go2).

    Cuerpo: { "source": "robot"|"webcam", "camera_index": N, "model": ..., "conf": ... }
    """
    data = request.get_json() or {}
    source = data.get('source', 'robot')
    camera_index = int(data.get('camera_index', 0))
    model_name = data.get('model', 'yolov8n.pt')
    conf = float(data.get('conf', 0.35))

    if source == 'robot' and not robot_state["connected"]:
        msg = "Conecta primero el robot para usar su camara."
        emit_log('error', msg)
        return jsonify({"status": "error", "message": msg}), 400

    result = yolo_detector.start(source=source,
                                 camera_index=camera_index,
                                 model_name=model_name,
                                 conf=conf)
    if result.get("ok"):
        emit_log('success', result.get("message", "YOLO iniciado"))
        return jsonify({"status": "ok", "message": result["message"]})
    emit_log('error', result.get("message", "Error YOLO"))
    return jsonify({"status": "error", "message": result.get("message")}), 500


@app.route('/api/yolo/stop', methods=['POST'])
def api_yolo_stop():
    """Detiene el detector YOLO."""
    result = yolo_detector.stop()
    emit_log('info', result.get("message", "YOLO detenido"))
    return jsonify({"status": "ok", "message": result.get("message")})


@app.route('/api/yolo/detections', methods=['GET'])
def api_yolo_detections():
    """Lista de detecciones actuales (waypoints candidatos)."""
    return jsonify({
        "status": "ok",
        "running": yolo_detector.is_running(),
        "detections": yolo_detector.get_detections(),
    })


@app.route('/api/yolo/stream')
def api_yolo_stream():
    """Stream MJPEG con frames anotados en tiempo real."""
    if not yolo_detector.is_running():
        return jsonify({"status": "error", "message": "YOLO no esta corriendo"}), 409
    return Response(
        yolo_detector.mjpeg_generator(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


# ════════════════════════════════════════════════════════
#  SENSOR DE PROXIMIDAD (SportModeState.range_obstacle del Go2)
# ════════════════════════════════════════════════════════
#
# El Go2 publica SportModeState en `rt/lf/sportmodestate` a ~50 Hz. El
# mensaje incluye `range_obstacle`: [front, left, back, right] en metros,
# calculado internamente por el robot a partir de su lidar. Es ligero
# (JSON pequeño) y no interfiere con el video WebRTC — a diferencia del
# voxel map comprimido.
#
# Flujo:
#   ON  -> subscribimos a rt/lf/sportmodestate con un callback que lee
#          range_obstacle, y si front < stop_distance_m emite
#          `proximity_alert` + Move=0.
#   OFF -> unsubscribe.


def _robot_is_moving_forward():
    """True solo si el último Move conocido es hacia adelante y reciente."""
    now = time.time()
    age = now - proximity_sensor["_last_cmd_ts"]
    if age > proximity_sensor["cmd_fresh_s"]:
        return False
    return proximity_sensor["_last_cmd_x"] >= proximity_sensor["min_forward_vel_mps"]


def _trigger_proximity_alert(distance_m, direction, source):
    """Emite una ÚNICA alerta al entrar en zona peligrosa y frena el robot.
    No vuelve a emitir hasta que salga de la zona (histéresis gestionada
    por el callback del lidar).

    Si la ventana de FORCE está abierta (_force_until en el futuro), se
    descarta todo: sin emit, sin Move=0, sin flip de _alert_active. El
    operador pidió explícitamente caminar normal pese al obstáculo."""
    if time.time() < proximity_sensor.get("_force_until", 0.0):
        return

    if proximity_sensor["_alert_active"]:
        return  # ya avisamos; esperamos que salga del peligro

    proximity_sensor["_alert_active"] = True
    proximity_sensor["_last_alert_ts"] = time.time()
    proximity_sensor["_last_source"] = source

    socketio.emit("proximity_alert", {
        "distance_m": round(float(distance_m), 2),
        "direction": direction,
        "source": source,
    })

    if robot_state["connected"] and robot_pub_sub:
        try:
            run_async_no_wait(
                robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
            )
        except Exception:
            pass


def _on_robot_pose_message(message):
    """Actualiza la pose del robot desde `rt/utlidar/robot_pose`. Varios
    firmwares anidan la pose de forma distinta; probamos los casos comunes."""
    try:
        data = (message or {}).get("data") or {}
        pose = data.get("pose") or data
        position = pose.get("position") if isinstance(pose, dict) else None
        orientation = pose.get("orientation") if isinstance(pose, dict) else None

        if not position:
            return

        proximity_sensor["_pose_x"] = float(position.get("x", 0.0))
        proximity_sensor["_pose_y"] = float(position.get("y", 0.0))
        proximity_sensor["_pose_z"] = float(position.get("z", 0.0))

        if orientation:
            qx = float(orientation.get("x", 0.0))
            qy = float(orientation.get("y", 0.0))
            qz = float(orientation.get("z", 0.0))
            qw = float(orientation.get("w", 1.0))
            siny = 2.0 * (qw * qz + qx * qy)
            cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
            proximity_sensor["_pose_yaw"] = math.atan2(siny, cosy)

        proximity_sensor["_pose_valid"] = True
    except Exception:
        pass


def _on_lidar_points_message(message):
    """Detecta obstáculos frontales a partir de la nube de puntos del lidar.
    Los puntos vienen en el frame del mapa (world); los transformamos al frame
    del robot usando la pose más reciente, filtramos un cono frontal y
    calculamos la distancia mínima. Si es menor al umbral, alerta + Move=0.
    """
    if not proximity_sensor["enabled"]:
        return
    try:
        data = (message or {}).get("data") or {}
        decoded = data.get("data")
        if not isinstance(decoded, dict):
            return

        import numpy as _np
        pts = None
        if "points" in decoded:
            pts = _np.asarray(decoded["points"])
        elif "positions" in decoded:
            arr = _np.asarray(decoded["positions"], dtype=_np.float32)
            if arr.ndim == 1 and arr.size % 3 == 0:
                arr = arr.reshape(-1, 3)
            pts = arr
        if pts is None or pts.ndim != 2 or pts.shape[0] == 0 or pts.shape[1] < 3:
            return

        # Pose del robot: ROBOTODOM si disponible; si no, centro del grid
        # (heurística: Go2 publica un voxel grid de ~128 celdas × 0.05 m
        # aproximadamente centrado en el robot).
        if proximity_sensor["_pose_valid"]:
            rx = proximity_sensor["_pose_x"]
            ry = proximity_sensor["_pose_y"]
            rz = proximity_sensor["_pose_z"]
            yaw = proximity_sensor["_pose_yaw"]
        else:
            origin = data.get("origin") or [0.0, 0.0, 0.0]
            res = float(data.get("resolution") or 0.05)
            half = 128 * res / 2.0
            rx = float(origin[0]) + half
            ry = float(origin[1]) + half
            rz = float(origin[2]) if len(origin) >= 3 else 0.0
            yaw = 0.0

        dx = pts[:, 0] - rx
        dy = pts[:, 1] - ry
        dz = pts[:, 2] - rz

        c, s = math.cos(-yaw), math.sin(-yaw)
        lx = dx * c - dy * s
        ly = dx * s + dy * c

        cone_y = proximity_sensor["forward_cone_y_m"]
        mask = (
            (lx > 0.10) &
            (_np.abs(ly) < cone_y) &
            (dz > proximity_sensor["min_z_m"]) &
            (dz < proximity_sensor["max_z_m"])
        )

        # Empuja los puntos al frontend para el heatmap (subsampled a ~5 Hz).
        _maybe_emit_lidar_points(pts, rx, ry, yaw)

        if not _np.any(mask):
            # Sin nada al frente: contamos hacia la liberación de histéresis.
            _maybe_clear_alert_state(float("inf"))
            return

        fwd_x = lx[mask]
        fwd_y = ly[mask]
        dists = _np.sqrt(fwd_x * fwd_x + fwd_y * fwd_y)
        d = float(_np.min(dists))
        proximity_sensor["_last_distance"] = d

        # Histéresis: si el obstáculo se alejó bastante, liberamos el estado.
        _maybe_clear_alert_state(d)

        # Solo alertamos si 1) obstáculo muy cerca Y 2) el robot va hacia adelante.
        if d >= proximity_sensor["stop_distance_m"]:
            return
        if not _robot_is_moving_forward():
            # Quieto o retrocediendo: no spamear alerta (aunque haya una pared).
            return

        nearest = int(_np.argmin(dists))
        ny = float(fwd_y[nearest])
        direction = "center" if abs(ny) < 0.12 else ("left" if ny > 0 else "right")
        _trigger_proximity_alert(d, direction, "lidar_points")
    except Exception as exc:
        emit_log('warning', f'Callback lidar points: {exc}')


def _maybe_clear_alert_state(distance_m):
    """Reset del flag de alerta cuando la zona está clara durante >0.8 s.
    Así el usuario puede re-intentar avanzar y recibir otra alerta si toca."""
    now = time.time()
    clear_thr = proximity_sensor["clear_distance_m"]
    if distance_m >= clear_thr:
        if proximity_sensor["_clear_since"] == 0.0:
            proximity_sensor["_clear_since"] = now
        elif now - proximity_sensor["_clear_since"] >= 0.8:
            proximity_sensor["_alert_active"] = False
    else:
        proximity_sensor["_clear_since"] = 0.0


def _maybe_emit_lidar_points(pts, rx, ry, yaw):
    """Publica una muestra de puntos del lidar al frontend a ~5 Hz.
    Los puntos se envían en el frame del MAPA (world): el frontend los
    acumula para pintar el heatmap de paredes + trayectoria."""
    now = time.time()
    if now - proximity_sensor["_last_points_emit_ts"] < 0.2:
        return
    proximity_sensor["_last_points_emit_ts"] = now
    try:
        import numpy as _np
        n = pts.shape[0]
        if n == 0:
            return
        # Filtra al suelo / techo para quedarnos con paredes / objetos.
        zmask = (pts[:, 2] > proximity_sensor["min_z_m"]) & \
                (pts[:, 2] < proximity_sensor["max_z_m"])
        w_pts = pts[zmask]
        if w_pts.shape[0] > 1500:
            idx = _np.random.choice(w_pts.shape[0], 1500, replace=False)
            w_pts = w_pts[idx]

        xy = w_pts[:, :2].astype(float)
        socketio.emit("lidar_points", {
            "pose": {"x": rx, "y": ry, "yaw": yaw},
            # xy aplanado para reducir peso JSON
            "xy": xy.round(3).flatten().tolist(),
            "count": int(xy.shape[0]),
        })
    except Exception:
        pass




async def _proximity_enable_async():
    """
    Activa el sensor de proximidad real:
      1. Cambia decoder a 'native' para recibir ndarray de puntos.
      2. Deshabilita traffic-saving (si no, el robot throttlea el lidar).
      3. Prende el lidar L1 (el anillo empieza a girar).
      4. Suscribe a ROBOTODOM (pose del robot en el mapa) y al voxel map
         comprimido (nube de puntos). El callback del lidar transforma los
         puntos al frame del robot, filtra cono frontal y alerta < 60 cm.
    """
    from unitree_webrtc_connect.constants import RTC_TOPIC, DATA_CHANNEL_TYPE

    if not robot_connection or not robot_pub_sub:
        return False

    try:
        robot_connection.datachannel.set_decoder(decoder_type='native')
    except Exception as exc:
        emit_log('warning', f'set_decoder native: {exc}')

    try:
        await robot_connection.datachannel.disableTrafficSaving(True)
    except Exception as exc:
        emit_log('warning', f'disableTrafficSaving: {exc}')

    # Envía variantes de switch del lidar — en Go2 Air `"ON"` suele bastar.
    for payload in ("ON", {"enable": 1}):
        try:
            robot_pub_sub.publish_without_callback(
                RTC_TOPIC["ULIDAR_SWITCH"],
                payload,
                DATA_CHANNEL_TYPE["MSG"],
            )
        except Exception as exc:
            emit_log('warning', f'ULIDAR_SWITCH {payload!r}: {exc}')
    emit_log('info', 'Lidar L1 encendido (verifica que el anillo gire)')

    subscribed = []
    try:
        robot_pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], _on_robot_pose_message)
        subscribed.append(RTC_TOPIC["ROBOTODOM"])
    except Exception as exc:
        emit_log('warning', f'subscribe robot_pose: {exc}')

    try:
        robot_pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], _on_lidar_points_message)
        subscribed.append(RTC_TOPIC["ULIDAR_ARRAY"])
    except Exception as exc:
        emit_log('error', f'subscribe lidar array: {exc}')

    proximity_sensor["_subscribed"] = bool(subscribed)
    proximity_sensor["_subscribed_topics"] = subscribed
    proximity_sensor["_pose_valid"] = False

    if subscribed:
        emit_log('success',
                 f'Sensor activo. Suscrito a {len(subscribed)} topics. '
                 f'Parar si <{proximity_sensor["stop_distance_m"]*100:.0f} cm frontal.')
    return bool(subscribed)


async def _proximity_disable_async():
    from unitree_webrtc_connect.constants import RTC_TOPIC, DATA_CHANNEL_TYPE

    for t in proximity_sensor.get("_subscribed_topics") or []:
        try:
            robot_pub_sub and robot_pub_sub.unsubscribe(t)
        except Exception:
            pass

    if robot_pub_sub:
        for payload in ("OFF", {"enable": 0}):
            try:
                robot_pub_sub.publish_without_callback(
                    RTC_TOPIC["ULIDAR_SWITCH"],
                    payload,
                    DATA_CHANNEL_TYPE["MSG"],
                )
            except Exception:
                pass

    proximity_sensor["_subscribed"] = False
    proximity_sensor["_subscribed_topics"] = []
    proximity_sensor["_last_distance"] = None
    proximity_sensor["_pose_valid"] = False


@app.route('/api/sensor/status', methods=['GET'])
def api_sensor_status():
    return jsonify({
        "status": "ok",
        "enabled": proximity_sensor["enabled"],
        "stop_distance_m": proximity_sensor["stop_distance_m"],
        "last_distance_m": proximity_sensor["_last_distance"],
        "robot_connected": robot_state["connected"],
    })


@app.route('/api/sensor/toggle', methods=['POST'])
def api_sensor_toggle():
    """Activa/desactiva el sensor de proximidad del lidar del robot."""
    data = request.get_json(silent=True) or {}
    desired = data.get("enabled")
    if desired is None:
        desired = not proximity_sensor["enabled"]
    desired = bool(desired)

    if desired and not robot_state["connected"]:
        return jsonify({
            "status": "error",
            "message": "El robot no esta conectado. Conecta primero para usar el sensor.",
            "enabled": False,
        }), 400

    proximity_sensor["enabled"] = desired

    try:
        if desired:
            ok = run_async(_proximity_enable_async())
            if not ok:
                proximity_sensor["enabled"] = False
                return jsonify({
                    "status": "error",
                    "message": "No se pudo activar el sensor del robot.",
                    "enabled": False,
                }), 500
            emit_log('info', 'Sensor de proximidad ACTIVADO (lidar Go2)')
        else:
            run_async(_proximity_disable_async())
            emit_log('info', 'Sensor de proximidad desactivado')
    except Exception as exc:
        proximity_sensor["enabled"] = False
        return jsonify({"status": "error", "message": str(exc), "enabled": False}), 500

    return jsonify({
        "status": "ok",
        "enabled": proximity_sensor["enabled"],
        "stop_distance_m": proximity_sensor["stop_distance_m"],
    })


# ════════════════════════════════════════════════════════
#  AUTO-RUTA (seguidor de waypoints)
# ════════════════════════════════════════════════════════
#
# Se recibe una lista de puntos [{x,y}] en el frame del mapa del lidar y un
# número de ciclos. Un task asíncrono recorre cada waypoint:
#   - lee la pose del robot (la misma que alimenta el sensor: _pose_*)
#   - calcula heading y distancia al waypoint
#   - manda Move(x=linear, z=angular) hasta estar <reach_radius del punto
#   - pasa al siguiente; al terminar la lista, reinicia el ciclo.
# Un watchdog del lidar (_alert_active) frena el avance si aparece algo
# muy cerca; si el doble tap lo desbloqueó eso ya está manejado, aquí no.

autoroute_state = {
    "running": False,
    "cycles_total": 0,
    "cycle_now": 0,
    "waypoints": [],
    "wp_now": 0,
    "_task": None,
    "_cancel": False,
    # Tuning
    "linear_speed": 0.35,         # m/s hacia adelante máximo
    "angular_speed": 0.75,        # rad/s máximo para girar
    "reach_radius_m": 0.35,       # waypoint alcanzado si dist < 35 cm
    "heading_align_rad": 0.35,    # si dy ángulo > esto, solo rota
    "timeout_per_wp_s": 20.0,     # si no llega en 20s, pasa al siguiente
}


def _normalize_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


async def _autoroute_wait_for_pose(timeout_s=5.0):
    """Espera a que el lidar reporte pose valida. Retorna True si llego a
    tiempo. Si el sensor no esta suscrito o el lidar no publica, retorna
    False para que el llamador aborte con mensaje claro."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not proximity_sensor["_pose_valid"]:
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.15)
    return True


async def _autoroute_follow_loop():
    """Consumir waypoints x ciclos hasta cancelación."""
    state = autoroute_state
    try:
        # 1) Asegura que el robot este de pie y listo para caminar. Si esta
        #    sentado, los Move se ignoran silenciosamente.
        emit_log('info', 'Auto-Ruta: pidiendo BalanceStand…')
        try:
            await robot_send_command("BalanceStand")
        except Exception as exc:
            emit_log('warning', f'Auto-Ruta: BalanceStand fallo: {exc}')

        # 2) Espera a que el lidar reporte pose. Sin pose el seguidor no
        #    puede calcular errores de heading/distancia.
        ok_pose = await _autoroute_wait_for_pose(5.0)
        if not ok_pose:
            emit_log('error',
                     'Auto-Ruta: el lidar no reporto pose en 5 s. '
                     'Activa el sensor en el Control Remoto y verifica '
                     'que el robot publique utlidar/robot_pose.')
            state["_cancel"] = True
            return

        # 3) Traslada los waypoints: que el primero coincida con la pose
        #    actual del robot. Asi las rutas grabadas con dead-reckoning o
        #    con origen absoluto distinto funcionan desde "donde esta".
        pose_x = proximity_sensor["_pose_x"]
        pose_y = proximity_sensor["_pose_y"]
        waypoints = state["waypoints"]
        if waypoints:
            ox = float(waypoints[0]["x"]) - pose_x
            oy = float(waypoints[0]["y"]) - pose_y
            translated = [
                {"x": float(w["x"]) - ox, "y": float(w["y"]) - oy}
                for w in waypoints
            ]
            state["waypoints"] = translated
            emit_log('info',
                     f'Auto-Ruta: ruta trasladada al origen del robot '
                     f'(offset {ox:+.2f}, {oy:+.2f}).')

        for cycle in range(1, state["cycles_total"] + 1):
            if state["_cancel"]:
                break
            state["cycle_now"] = cycle
            for i, wp in enumerate(state["waypoints"]):
                if state["_cancel"]:
                    break
                state["wp_now"] = i + 1
                socketio.emit("autoroute_progress", {
                    "running": True,
                    "cycle": cycle,
                    "cycle_total": state["cycles_total"],
                    "waypoint": i + 1,
                    "waypoint_total": len(state["waypoints"]),
                })

                await _autoroute_go_to(wp)

        # Stop final
        try:
            await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        except Exception:
            pass
        emit_log('success', 'Auto-Ruta: recorrido completo.')
    except Exception as exc:
        emit_log('error', f'Auto-Ruta: error en el loop: {exc}')
    finally:
        state["running"] = False
        state["_task"] = None
        socketio.emit("autoroute_done", {})


async def _autoroute_go_to(wp):
    """Conduce el robot hacia el waypoint hasta que entre en el radio o
    se agote el timeout. Usa la pose del lidar (proximity_sensor)."""
    state = autoroute_state
    start_ts = asyncio.get_running_loop().time()

    while not state["_cancel"]:
        if (asyncio.get_running_loop().time() - start_ts) > state["timeout_per_wp_s"]:
            emit_log('warning', f'Waypoint ({wp.get("x"):.2f},{wp.get("y"):.2f}) timeout, siguiente')
            break

        if not proximity_sensor["_pose_valid"]:
            # Esperamos a tener pose del lidar
            await asyncio.sleep(0.15)
            continue

        px = proximity_sensor["_pose_x"]
        py = proximity_sensor["_pose_y"]
        yaw = proximity_sensor["_pose_yaw"]

        dx = float(wp.get("x", 0.0)) - px
        dy = float(wp.get("y", 0.0)) - py
        dist = math.hypot(dx, dy)
        if dist < state["reach_radius_m"]:
            break

        target_heading = math.atan2(dy, dx)
        heading_err = _normalize_angle(target_heading - yaw)

        # Estrategia simple: gira primero, avanza después.
        if abs(heading_err) > state["heading_align_rad"]:
            z = max(-state["angular_speed"],
                    min(state["angular_speed"], heading_err * 1.5))
            x = 0.0
        else:
            # Avanza proporcional a la distancia (hasta el máximo).
            x = max(0.0, min(state["linear_speed"], dist * 0.8))
            # Correcciones de yaw suaves mientras camina
            z = max(-0.4, min(0.4, heading_err * 1.2))

        # Si el sensor disparó alerta y NO estamos forzando, detenemos
        # este waypoint y pasamos al siguiente en la siguiente iteración.
        if proximity_sensor["enabled"] and proximity_sensor["_alert_active"]:
            try:
                await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
            except Exception:
                pass
            emit_log('warning', 'Auto-Ruta: sensor bloqueó el avance, saltando waypoint')
            break

        try:
            await robot_send_command("Move", {"x": x, "y": 0.0, "z": z})
        except Exception as exc:
            emit_log('error', f'Auto-Ruta move: {exc}')
            break

        await asyncio.sleep(0.2)

    # Stop entre waypoints
    try:
        await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    except Exception:
        pass


@app.route('/api/autoroute/start', methods=['POST'])
def api_autoroute_start():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if autoroute_state["running"]:
        return jsonify({"status": "error", "message": "Ya hay una ruta en curso"}), 409

    data = request.get_json(silent=True) or {}
    pts = data.get("points") or []
    cycles = int(data.get("cycles", 1) or 1)

    waypoints = [
        {"x": float(p["x"]), "y": float(p["y"])}
        for p in pts
        if isinstance(p, dict) and "x" in p and "y" in p
    ]
    if len(waypoints) < 2:
        return jsonify({"status": "error", "message": "Ruta vacía o incompleta"}), 400

    # Activa el sensor si no lo está (para que el robot se autodetenga).
    if not proximity_sensor["enabled"]:
        try:
            run_async(_proximity_enable_async())
            proximity_sensor["enabled"] = True
        except Exception as exc:
            emit_log('warning', f'No se pudo activar sensor: {exc}')

    autoroute_state["waypoints"] = waypoints
    autoroute_state["cycles_total"] = max(1, cycles)
    autoroute_state["cycle_now"] = 0
    autoroute_state["wp_now"] = 0
    autoroute_state["_cancel"] = False
    autoroute_state["running"] = True
    autoroute_state["_task"] = run_async_no_wait(_autoroute_follow_loop())

    emit_log('success', f'Auto-Ruta iniciada: {len(waypoints)} waypoints × {cycles} ciclos')
    return jsonify({
        "status": "ok",
        "waypoints": len(waypoints),
        "cycles": autoroute_state["cycles_total"],
    })


@app.route('/api/autoroute/stop', methods=['POST'])
def api_autoroute_stop():
    autoroute_state["_cancel"] = True
    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
    except Exception:
        pass
    emit_log('info', 'Auto-Ruta: detenida por el usuario')
    return jsonify({"status": "ok"})


@app.route('/api/autoroute/status', methods=['GET'])
def api_autoroute_status():
    return jsonify({
        "status": "ok",
        "running": autoroute_state["running"],
        "cycle": autoroute_state["cycle_now"],
        "cycle_total": autoroute_state["cycles_total"],
        "waypoint": autoroute_state["wp_now"],
        "waypoint_total": len(autoroute_state["waypoints"]),
    })


# ════════════════════════════════════════════════════════
#  SOCKETIO EVENTS
# ════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_ws_connect():
    emit('state_update', robot_state)
    emit('log', {'type': 'info', 'message': 'Dashboard conectado al servidor'})


@socketio.on('move_command')
def handle_move_command(data):
    """Recibe comandos de movimiento en tiempo real via WebSocket."""
    if not robot_state["connected"]:
        return

    x = float(data.get('x', 0.0))
    y = float(data.get('y', 0.0))
    z = float(data.get('z', 0.0))

    x = max(-0.8, min(0.8, x))
    y = max(-0.5, min(0.5, y))
    z = max(-1.5, min(1.5, z))

    # Registramos el Move para que el sensor de proximidad sepa si el robot
    # va hacia adelante (y solo alerte en ese caso).
    proximity_sensor["_last_cmd_x"] = x
    proximity_sensor["_last_cmd_ts"] = time.time()

    # El frontend marca `force=true` cuando el operador sostiene Shift,
    # el boton Override movil, o hace doble tap WASD. El operador insiste:
    # saltamos TODO protocolo de stop del sensor de proximidad.
    force = bool(data.get("force"))

    # Si el sensor está activo y hay un obstáculo en alerta y el usuario
    # empuja hacia adelante, bloqueamos — salvo que venga force.
    if (not force
            and proximity_sensor["enabled"]
            and proximity_sensor["_alert_active"]
            and x > 0):
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": z}))
        return

    # Con force el operador acepta el riesgo:
    #   1) limpiamos el estado de alerta en curso,
    #   2) abrimos una ventana de gracia (0.8 s) durante la cual el sensor
    #      no volvera a disparar alerta ni Move=0. Como los comandos se
    #      envian cada 200 ms, mientras el operador mantenga la tecla la
    #      ventana se renueva y el robot camina sin interrupciones.
    if force:
        proximity_sensor["_force_until"] = time.time() + 0.8
        if proximity_sensor["_alert_active"]:
            proximity_sensor["_alert_active"] = False
            proximity_sensor["_clear_since"] = 0.0
    else:
        # Si este comando NO trae force, el operador solto la combinacion:
        # cerramos la ventana de gracia en seco para que el sensor vuelva a
        # actuar normal desde ya (no dentro de 0.8 s).
        proximity_sensor["_force_until"] = 0.0

    try:
        run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
    except Exception as e:
        emit('log', {'type': 'error', 'message': str(e)})


@socketio.on('stop_command')
def handle_stop_command():
    """Detiene el robot via WebSocket."""
    # Al pedir stop, el operador no esta tocando ninguna tecla: cerramos
    # tambien la ventana de force para que el sensor vuelva a proteger
    # desde ya.
    proximity_sensor["_force_until"] = 0.0
    proximity_sensor["_last_cmd_x"] = 0.0
    if not robot_state["connected"]:
        return
    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
    except Exception as e:
        emit('log', {'type': 'error', 'message': str(e)})


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 50)
    print("  Daiver Control CUN — Flask Backend")
    print(f"  Robot IP: {ROBOT_IP}")
    print(f"  Server:   http://localhost:5000")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
