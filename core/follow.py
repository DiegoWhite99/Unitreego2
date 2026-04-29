"""Follow-Me por QR: el robot persigue cualquier QR que vea.

Usa la posicion del QR en el frame para generar Move:
  - norm_cx - 0.5  -> error lateral -> gira para centrarlo
  - area_ratio    -> proxy de distancia -> avanza si esta lejos

Seguridad:
  - Si el QR no se ve hace > lost_timeout_s, Move=0.
  - Si proximity_sensor dispara alerta, Move=0.
  - Stop manual: marcar follow_state["_cancel"] = True.
"""

from __future__ import annotations

import asyncio

from yolo_detector import detector as yolo_detector

from .logging_utils import emit_log
from .primitives import robot_send_command
from .runtime import socketio
from .state import follow_state, proximity_sensor


async def _follow_send(x: float, z: float, reason: str) -> None:
    """Envia Move y emite heartbeat al frontend."""
    follow_state["_last_x"] = x
    follow_state["_last_z"] = z
    follow_state["_last_reason"] = reason
    try:
        await robot_send_command("Move", {"x": x, "y": 0.0, "z": z})
    except Exception as exc:
        emit_log("warning", f"Follow-QR move: {exc}")
    socketio.emit("follow_status", {
        "running": follow_state["running"],
        "x":       round(x, 3),
        "z":       round(z, 3),
        "reason":  reason,
        "qr":      follow_state["_last_qr_text"],
    })


async def follow_loop() -> None:
    """Loop principal. Corre cada 200 ms hasta que `_cancel` sea True."""
    state = follow_state
    try:
        emit_log("info", "Follow-QR: BalanceStand")
        try:
            await robot_send_command("BalanceStand")
        except Exception as exc:
            emit_log("warning", f"Follow-QR: BalanceStand fallo: {exc}")

        socketio.emit("follow_status", {"running": True, "reason": "started"})

        while not state["_cancel"]:
            qr = yolo_detector.get_last_qr_tracking()
            age = qr.get("age_s")
            ncx = qr.get("norm_cx")
            area = qr.get("area_ratio")
            text = qr.get("text")

            if age is None or age > state["lost_timeout_s"]:
                await _follow_send(0.0, 0.0, "QR no visible")
                await asyncio.sleep(0.2)
                continue

            if proximity_sensor["enabled"] and proximity_sensor["_alert_active"]:
                await _follow_send(0.0, 0.0, "Obstaculo adelante (sensor)")
                await asyncio.sleep(0.2)
                continue

            err = ncx - 0.5  # positivo = QR a la derecha
            z = -state["k_angular"] * err
            z = max(-state["max_angular"], min(state["max_angular"], z))

            if area >= state["near_area"]:
                x = 0.0
                reason = f"QR cerca (area {area:.3f})"
            elif area >= state["target_area"]:
                x = 0.15
                reason = f"Siguiendo (area {area:.3f})"
            else:
                deficit = state["target_area"] - area
                x = min(state["max_linear"], 0.18 + deficit * 4.0)
                reason = f"Acercando (area {area:.3f})"

            state["_last_qr_text"] = text
            await _follow_send(x, z, reason)
            await asyncio.sleep(0.2)
    except Exception as exc:
        emit_log("error", f"Follow-QR: error en el loop: {exc}")
    finally:
        try:
            await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        except Exception:
            pass
        state["running"] = False
        state["_task"] = None
        state["_last_x"] = 0.0
        state["_last_z"] = 0.0
        socketio.emit("follow_status", {"running": False, "reason": "stopped"})
