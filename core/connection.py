"""Conexion WebRTC al Unitree Go2: connect/disconnect, video → YOLO.

Mantiene la misma logica que vivia en app.py:
- abre `UnitreeWebRTCConnection` modo LocalSTA,
- se suscribe al canal de video y empuja frames al detector YOLO,
- envia `BalanceStand` inicial,
- en desconexion: cierra video, detiene YOLO si estaba sobre el robot.
"""

from __future__ import annotations

import asyncio

from yolo_detector import detector as yolo_detector

from .logging_utils import emit_log, emit_state_update
from .runtime import (
    clear_connection,
    get_connection,
    set_connection,
)
from .state import robot_state


# ────────────────────────────────────────────────────────────────────
# Compatibilidad entre nombres SPORT_CMD usados en distintas versiones
# del SDK. Antes vivia en app.py como SPORT_CMD_COMPAT_ALIASES.
# ────────────────────────────────────────────────────────────────────
SPORT_CMD_COMPAT_ALIASES = {
    "SitDown":       ("SitDown", "Sit", "StandDown"),
    "RiseSit":       ("RiseSit", "StandUp", "Standup", "StandOut"),
    "RecoveryStand": ("RecoveryStand",),
    "StandDown":     ("StandDown", "SitDown", "Sit"),
}


def resolve_sport_cmd_key(requested_key: str, sport_cmd_dict: dict) -> str | None:
    """Devuelve la clave real disponible en el SDK para `requested_key`,
    probando alias si no esta literal. None si no hay nada compatible."""
    if requested_key in sport_cmd_dict:
        return requested_key
    for alias in SPORT_CMD_COMPAT_ALIASES.get(requested_key, ()):
        if alias in sport_cmd_dict:
            return alias
    return None


async def _go2_video_callback(track) -> None:
    """Callback WebRTC: lee frames y los empuja a YOLO.

    aiortc entrega el `track`; este loop hace `track.recv()` hasta que
    se cierre. Si el detector no esta corriendo, push_frame es no-op."""
    emit_log("info", "Canal de video del Go2 abierto, recibiendo frames...")
    try:
        while True:
            frame = await track.recv()
            try:
                bgr = frame.to_ndarray(format="bgr24")
            except Exception as exc:
                emit_log("warning", f"Frame del Go2 invalido: {exc}")
                continue
            yolo_detector.push_frame(bgr)
    except Exception as exc:
        emit_log("warning", f"Canal de video del Go2 cerrado: {exc}")


async def robot_connect(ip: str) -> None:
    """Conecta al robot via WebRTC y habilita canal de video para YOLO."""
    from unitree_webrtc_connect import (
        UnitreeWebRTCConnection,
        WebRTCConnectionMethod,
    )
    from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

    # Habilita el handshake con_notify v3 (firmware nuevo del Go2). Sin esto, el
    # SDK 2.x no descifra el data1 cifrado y la conexion LocalSTA falla con
    # "RSA key format is not supported". Idempotente. Ver core/unitree_v3_patch.
    from .unitree_v3_patch import apply_v3_patch
    apply_v3_patch()

    emit_log("info", f"Conectando a {ip}...")

    # Pre-chequeo de alcance: si el robot no responde en el puerto del handshake
    # (9991), fallamos rapido con un mensaje claro en vez de colgarnos ~30s en
    # ICE / recibir un error criptico. Causa #1 de "no conecta": robot apagado,
    # en otra red WiFi, o con una IP distinta a la configurada.
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 9991), timeout=3.0
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    except (asyncio.TimeoutError, OSError) as exc:
        msg = (
            f"El robot no responde en {ip}:9991. Verifica que este encendido y "
            f"conectado a la misma red WiFi. Si cambio de IP, actualizala en "
            f"Configuracion."
        )
        emit_log("error", msg)
        raise ConnectionError(msg) from exc

    # OJO: el SDK instalado (unitree_webrtc_connect 2.x) NO acepta el kwarg
    # `aes_128_key` — negocia su propia clave AES por sesion en el handshake
    # local con_notify (puerto 9991). Pasarlo lanzaba TypeError y rompia la
    # conexion antes de empezar (regresion del commit 1065ec11). La clave AES
    # de la cuenta solo aplica al metodo Remote/cloud o a un SDK con v3.
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip)
    await conn.connect()
    pub_sub = conn.datachannel.pub_sub
    set_connection(conn, pub_sub)

    await asyncio.sleep(2)

    # Habilita canal de video del Go2 y registra callback para YOLO.
    try:
        if hasattr(conn, "video") and conn.video is not None:
            conn.video.add_track_callback(_go2_video_callback)
            conn.video.switchVideoChannel(True)
            emit_log("success", "Canal de video del Go2 habilitado")
    except Exception as exc:
        emit_log("warning", f"No se pudo habilitar video del Go2: {exc}")

    # Balance Stand inicial.
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    robot_state["connected"] = True
    robot_state["ip"] = ip
    robot_state["mode"] = "Balance Stand"

    emit_log("success", f"Conexion establecida con {ip}")
    emit_state_update()


async def robot_disconnect() -> None:
    """Cierra video, apaga YOLO si dependia del robot, suelta la conexion."""
    if yolo_detector.is_running() and yolo_detector.status().get("source") == "robot":
        yolo_detector.stop()
        emit_log("info", "YOLO detenido (robot desconectando)")

    conn = get_connection()
    if conn:
        try:
            if hasattr(conn, "video") and conn.video is not None:
                conn.video.switchVideoChannel(False)
        except Exception:
            pass
        await conn.disconnect()
        clear_connection()

    robot_state["connected"] = False
    robot_state["mode"] = "Standby"
    emit_log("info", "Desconectado del robot")
    emit_state_update()
