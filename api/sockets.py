"""Handlers Socket.IO. Se registran via `register_socket_handlers(socketio)`
desde el bootstrap."""

from __future__ import annotations

import time

from flask_socketio import SocketIO, emit

from core.primitives import robot_send_command
from core.runtime import run_async
from core.state import proximity_sensor, robot_state


def register_socket_handlers(socketio: SocketIO) -> None:

    @socketio.on("connect")
    def handle_ws_connect():
        emit("state_update", robot_state)
        emit("log", {"type": "info",
                     "message": "Dashboard conectado al servidor"})

    @socketio.on("move_command")
    def handle_move_command(data):
        """Comandos de movimiento en tiempo real via WebSocket."""
        if not robot_state["connected"]:
            return

        x = max(-0.8, min(0.8, float(data.get("x", 0.0))))
        y = max(-0.5, min(0.5, float(data.get("y", 0.0))))
        z = max(-1.5, min(1.5, float(data.get("z", 0.0))))

        # Registramos el Move para que el sensor de proximidad sepa
        # si el robot va hacia adelante (y solo alerte en ese caso).
        proximity_sensor["_last_cmd_x"] = x
        proximity_sensor["_last_cmd_ts"] = time.time()

        # `force=true` cuando el operador sostiene Shift / Override / doble tap.
        # En ese caso saltamos TODO protocolo de stop del sensor.
        force = bool(data.get("force"))

        # Si sensor ON + alerta + el usuario empuja hacia adelante: bloqueamos
        # (a menos que venga force).
        if (not force
                and proximity_sensor["enabled"]
                and proximity_sensor["_alert_active"]
                and x > 0):
            run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": z}))
            return

        # Con force: limpia alerta + abre ventana de gracia (0.8 s) que
        # se renueva cada 200 ms mientras el operador mantenga la tecla.
        if force:
            proximity_sensor["_force_until"] = time.time() + 0.8
            if proximity_sensor["_alert_active"]:
                proximity_sensor["_alert_active"] = False
                proximity_sensor["_clear_since"] = 0.0
        else:
            # Cierre seco de la ventana (operador soltó la combo) — sensor
            # vuelve a actuar normal desde ya, no dentro de 0.8 s.
            proximity_sensor["_force_until"] = 0.0

        try:
            run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
        except Exception as e:
            emit("log", {"type": "error", "message": str(e)})

    @socketio.on("stop_command")
    def handle_stop_command():
        """Detiene el robot via WebSocket. Cierra ventana de force."""
        proximity_sensor["_force_until"] = 0.0
        proximity_sensor["_last_cmd_x"] = 0.0
        if not robot_state["connected"]:
            return
        try:
            run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
        except Exception as e:
            emit("log", {"type": "error", "message": str(e)})
