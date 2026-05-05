"""app.py — Bootstrap del backend Daiver Control CUN.

La logica vive en `core/` (dominio) y `api/` (blueprints Flask).
Aqui solo:
  1. Construimos `app` y `socketio` (en core.runtime, importados aqui).
  2. Registramos los blueprints HTTP.
  3. Registramos los handlers Socket.IO.
  4. Enganchamos el callback de QR del detector YOLO.
  5. Levantamos el servidor.
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config.config import ROBOT_IP

from api import register_blueprints
from api.sockets import register_socket_handlers
from core.perception import qr as qr_module
from core.runtime import app, socketio
from core.state import robot_state


# ────────────────────────────────────────────────────────────────────
# Wire-up
# ────────────────────────────────────────────────────────────────────
register_blueprints(app)
register_socket_handlers(socketio)
qr_module.register()  # callback YOLO -> qr_state + socket.emit('qr_detected')


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  Daiver Control CUN — Flask Backend")
    print(f"  Robot IP: {ROBOT_IP}")
    print(f"  Server:   http://localhost:5000")
    print("=" * 50)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
