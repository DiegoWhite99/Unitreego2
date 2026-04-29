"""QR detectado por YOLO + emision Socket.IO con la pose del lidar.

Registra un callback en `yolo_detector` que el detector invoca cuando
ve un QR. Aqui hacemos:
  - dedup (mismo QR sostenido emite cada `dedup_window_s`),
  - adjuntamos pose actual del robot,
  - emitimos evento `qr_detected` al frontend.
"""

from __future__ import annotations

import time

from yolo_detector import detector as yolo_detector

from ..runtime import socketio
from ..state import proximity_sensor, qr_state


def _on_qr_detected_from_yolo(qr_text: str, corners) -> None:
    now = time.time()
    if (qr_text == qr_state["last_text"]
            and now - qr_state["last_ts"] < qr_state["dedup_window_s"]):
        return
    pose = None
    if proximity_sensor["_pose_valid"]:
        pose = {
            "x":   round(proximity_sensor["_pose_x"], 3),
            "y":   round(proximity_sensor["_pose_y"], 3),
            "yaw": round(proximity_sensor["_pose_yaw"], 3),
        }
    qr_state["last_text"] = qr_text
    qr_state["last_ts"] = now
    qr_state["last_pose"] = pose
    try:
        socketio.emit("qr_detected", {
            "text":    qr_text,
            "pose":    pose,
            "corners": corners,
            "ts":      now,
        })
    except Exception:
        pass


def register() -> None:
    """Llamar UNA VEZ desde el bootstrap para enganchar el callback al detector."""
    yolo_detector.set_qr_callback(_on_qr_detected_from_yolo)
