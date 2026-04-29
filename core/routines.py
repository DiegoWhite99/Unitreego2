"""Rutinas pre-grabadas: patrullaje, salto, exploracion.

Cada una respeta `is_stop_requested()` para abortar limpiamente y
actualiza `robot_state` para que el frontend muestre el progreso.
"""

from __future__ import annotations

import asyncio
import math

from .logging_utils import emit_log, emit_state_update
from .primitives import robot_mover, robot_send_command, robot_stop
from .state import (
    clear_stop_routine,
    is_stop_requested,
    robot_state,
)


async def rutina_patrullaje() -> None:
    """Equivalente a scripts/05_rutina1.py."""
    clear_stop_routine()
    robot_state["routine_running"] = True
    robot_state["routine_name"] = "Patrullaje"
    emit_state_update()

    steps = [
        ("Avanzar 5.5m",                 0.5, 0.0, 0.0, 11),
        ("Giro izquierda 180",           0.0, 0.0, 1.0, 1.8),
        ("Avanzar 5.0m",                 0.5, 0.0, 0.0, 10),
        ("Giro izquierda 180",           0.0, 0.0, 1.0, 2),
        ("Avanzar 3.75m",                0.5, 0.0, 0.0, 7.5),
        ("Giro izquierda 180",           0.0, 0.0, 1.0, 1.7),
        ("Avanzar 4.8m (retorno)",       0.3, 0.0, 0.0, 16),
        ("Giro izquierda 180 (cierre)",  0.0, 0.0, 1.0, 1.7),
    ]

    try:
        for i, (desc, x, y, z, dur) in enumerate(steps, 1):
            if is_stop_requested():
                emit_log("warning", "Rutina detenida por el usuario")
                break
            emit_log("info", f"[STEP {i}/{len(steps)}] {desc}")
            await robot_mover(x, y, z, dur)
            await robot_stop()

        if not is_stop_requested():
            emit_log("success", "Rutina de patrullaje completada")
    except Exception as exc:
        emit_log("error", f"Error en rutina: {exc}")
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


async def rutina_salto() -> None:
    """Equivalente a scripts/07_rutinaSalto.py."""
    clear_stop_routine()
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
            "Balance Stand final",
        ]

        async def do_steps() -> None:
            emit_log("info", f"[STEP 1/11] {steps_info[0]}")
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 2/11] {steps_info[1]}")
            await robot_mover(0.4, 0.0, 0.0, 5)
            await robot_stop()
            if is_stop_requested(): return

            emit_log("info", f"[STEP 3/11] {steps_info[2]}")
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 4/11] {steps_info[3]}")
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 5/11] {steps_info[4]}")
            await robot_mover(0.4, 0.0, 0.0, 5)
            await robot_stop()
            if is_stop_requested(): return

            emit_log("info", f"[STEP 6/11] {steps_info[5]}")
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 7/11] {steps_info[6]}")
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 8/11] {steps_info[7]}")
            await robot_mover(0.0, 0.0, 1.0, 1.8)
            await robot_stop()
            if is_stop_requested(): return

            emit_log("info", f"[STEP 9/11] {steps_info[8]}")
            await robot_mover(0.4, 0.0, 0.0, 10)
            await robot_stop()
            if is_stop_requested(): return

            emit_log("info", f"[STEP 10/11] {steps_info[9]}")
            await robot_send_command("FrontJump")
            await asyncio.sleep(3)
            if is_stop_requested(): return

            emit_log("info", f"[STEP 11/11] {steps_info[10]}")
            await robot_send_command("BalanceStand")
            await asyncio.sleep(3)

        await do_steps()

        if not is_stop_requested():
            emit_log("success", "Rutina de salto completada")
    except Exception as exc:
        emit_log("error", f"Error en rutina: {exc}")
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


async def rutina_exploracion() -> None:
    """Avanza, gira 90°, repite 4 veces."""
    clear_stop_routine()
    robot_state["routine_running"] = True
    robot_state["routine_name"] = "Exploracion"
    emit_state_update()

    try:
        directions = [0, 90, 180, 270]
        for i, _angle in enumerate(directions):
            if is_stop_requested():
                break

            emit_log("info", f"[EXPLORE {i+1}/4] Avanzar 3m")
            await robot_mover(0.4, 0.0, 0.0, 7.5)
            await robot_stop()

            if is_stop_requested():
                break

            emit_log("info", f"[EXPLORE {i+1}/4] Giro 90 derecha")
            t_giro = (90 * math.pi / 180) / 1.0
            await robot_mover(0.0, 0.0, -1.0, t_giro)
            await robot_stop()

        if not is_stop_requested():
            emit_log("success", "Rutina de exploracion completada")
    except Exception as exc:
        emit_log("error", f"Error en rutina: {exc}")
    finally:
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None
        emit_state_update()


# Mapeo nombre publico → corutina, para /api/routine.
ROUTINE_MAP = {
    "patrol":  rutina_patrullaje,
    "jump":    rutina_salto,
    "explore": rutina_exploracion,
}
