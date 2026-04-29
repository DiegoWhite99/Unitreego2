"""Helpers de logging hacia el frontend via Socket.IO.

Ojo: no son `logging` de stdlib — son emisores Socket.IO que pintan en
la consola del dashboard web. El backend tambien hace `print` en algunos
sitios; no lo cambiamos en esta refactorizacion.
"""

from .runtime import socketio
from .state import robot_state


def emit_log(log_type: str, message: str) -> None:
    """Emite un mensaje al panel de logs del dashboard.
    log_type: 'info' | 'success' | 'warning' | 'error'.
    """
    socketio.emit("log", {"type": log_type, "message": message})


def emit_state_update() -> None:
    """Empuja `robot_state` al frontend para refrescar indicadores."""
    socketio.emit("state_update", robot_state)
