"""Acciones complejas con secuencias de estabilizacion previa/posterior.

Cada funcion sigue el patron:
    1. Frenar suave (Move=0 progresivo).
    2. BalanceStand para fijar postura.
    3. Comando real (SitDown, FingerHeart, Scrape, ...).
    4. (algunas) Frenado posterior + BalanceStand para evitar rebote.

Reusan las primitivas en `core.primitives`.
"""

from __future__ import annotations

import asyncio

from .logging_utils import emit_log
from .primitives import (
    robot_prepare_stable_action,
    robot_send_command,
    robot_soft_brake,
)
from .runtime import get_pub_sub


async def robot_scrape_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    if not await robot_prepare_stable_action(balance_wait=1.35):
        return False

    if not await robot_send_command("Scrape"):
        return False
    await asyncio.sleep(3.2)

    if not await robot_soft_brake(cycles=5, step_delay=0.12):
        return False
    if not await robot_send_command("BalanceStand"):
        return False
    await asyncio.sleep(1.6)
    return True


async def robot_heart_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    if not await robot_prepare_stable_action(balance_wait=1.25):
        return False

    if not await robot_send_command("FingerHeart"):
        return False
    await asyncio.sleep(3.8)

    if not await robot_soft_brake(cycles=4, step_delay=0.12):
        return False
    if not await robot_send_command("BalanceStand"):
        return False
    await asyncio.sleep(1.3)
    return True


async def robot_sit_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    if not await robot_send_command("SitDown"):
        return False
    await asyncio.sleep(2.2)
    return True


async def robot_rise_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)

    if not await robot_send_command("RiseSit"):
        return False
    await asyncio.sleep(2.2)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(1.0)
    return True


async def robot_recovery_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)

    if not await robot_send_command("RecoveryStand"):
        return False
    await asyncio.sleep(2.6)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(1.0)
    return True


async def robot_lie_safe() -> bool:
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    if not await robot_send_command("StandDown"):
        return False
    await asyncio.sleep(2.4)
    return True


async def robot_wiggle_safe() -> bool:
    """Meneo robusto via oscilacion corta de yaw — fallback cuando WiggleHips
    no esta disponible o se siente muy agresivo."""
    if not get_pub_sub():
        emit_log("error", "No hay conexion activa")
        return False

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)

    pattern = [0.75, -0.75, 0.75, -0.75, 0.6, -0.6]
    for z in pattern:
        await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": z})
        await asyncio.sleep(0.18)

    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    await asyncio.sleep(0.3)
    await robot_send_command("BalanceStand")
    await asyncio.sleep(0.8)
    return True
