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

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

from config.config import ROBOT_IP

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

# Conexion y pub_sub globales
robot_connection = None
robot_pub_sub = None
event_loop = None
loop_thread = None
routine_task = None
stop_routine_flag = False


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


async def robot_connect(ip):
    """Conecta al robot via WebRTC."""
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
    """Desconecta del robot."""
    global robot_connection, robot_pub_sub

    if robot_connection:
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

    payload = {"api_id": SPORT_CMD[api_cmd]}
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
        "SitDown", "RiseSit", "Pose", "Scrape",
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

    action_map = {
        "stand": "BalanceStand",
        "sit": "SitDown",
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
        run_async(robot_send_command(cmd))
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
            "RecoveryStand", "Euler", "SitDown", "RiseSit",
            "Scrape", "FrontFlip", "FrontJump", "FrontPounce",
            "WiggleHips", "GetState", "EconomicGait",
            "Dance1", "Dance2", "FingerHeart"
        ],
        "actions": [
            "stand", "sit", "rise", "recovery", "hello", "stretch",
            "dance1", "dance2", "wiggle", "scrape", "heart",
            "frontflip", "frontjump", "frontpounce"
        ],
        "routines": ["patrol", "jump", "explore"]
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

    try:
        run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
    except Exception as e:
        emit('log', {'type': 'error', 'message': str(e)})


@socketio.on('stop_command')
def handle_stop_command():
    """Detiene el robot via WebSocket."""
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
