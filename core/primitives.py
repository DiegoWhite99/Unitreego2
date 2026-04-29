"""Primitivas de actuacion del Go2: enviar SPORT_CMD, mover, frenar.

Funciones de bajo nivel que escriben sobre el canal pub_sub. Las acciones
"complejas" estabilizadas (sit_safe, heart_safe, etc.) viven en `core.poses`.
"""

from __future__ import annotations

import asyncio

from .connection import resolve_sport_cmd_key
from .logging_utils import emit_log
from .runtime import get_pub_sub
from .state import is_stop_requested


async def robot_send_command(api_cmd: str, parameter: dict | None = None) -> bool:
    """Envia un SPORT_CMD individual. Devuelve True si se publicó.

    `parameter` es opcional (ej: {'x':0.4,'y':0,'z':0} para Move)."""
    pub_sub = get_pub_sub()
    if not pub_sub:
        emit_log("error", "No hay conexion activa")
        return False

    from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

    resolved_cmd = resolve_sport_cmd_key(api_cmd, SPORT_CMD)
    if not resolved_cmd:
        emit_log("error", f"Comando no soportado por el SDK actual: {api_cmd}")
        return False

    if resolved_cmd != api_cmd:
        emit_log("warning", f"Compatibilidad SDK: '{api_cmd}' -> '{resolved_cmd}'")

    payload: dict = {"api_id": SPORT_CMD[resolved_cmd]}
    if parameter:
        payload["parameter"] = parameter

    await pub_sub.publish_request_new(RTC_TOPIC["SPORT_MOD"], payload)
    return True


async def robot_mover(x: float, y: float, z: float, duracion: float) -> None:
    """Movimiento continuo durante `duracion` segundos (re-envia cada 0.2 s)."""
    pub_sub = get_pub_sub()
    if not pub_sub:
        return

    from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

    inicio = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - inicio < duracion:
        if is_stop_requested():
            break
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Move"],
             "parameter": {"x": x, "y": y, "z": z}},
        )
        await asyncio.sleep(0.2)


async def robot_stop() -> None:
    """Frena con Move=0 + 1 s de margen."""
    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(1)


async def robot_soft_brake(cycles: int = 4, step_delay: float = 0.12) -> bool:
    """Frenado progresivo enviando varios Move=0. Reduce tirones al
    entrar/salir de acciones cinematicas."""
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    cycles = max(1, int(cycles))
    for _ in range(cycles):
        ok = await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        if not ok:
            return False
        await asyncio.sleep(step_delay)
    return True


async def robot_prepare_stable_action(balance_wait: float = 1.1) -> bool:
    """Secuencia comun antes de acciones cinematicas: frena suave + balance."""
    if not await robot_soft_brake(cycles=4, step_delay=0.12):
        return False
    if not await robot_send_command("BalanceStand"):
        return False
    await asyncio.sleep(balance_wait)
    return True
