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

# El SDK de Unitree imprime estados con emojis (🕒, 🟢...). En consola Windows
# (cp1252) eso lanza UnicodeEncodeError y aborta el connect() a mitad de
# handshake. Forzamos UTF-8 con reemplazo para que nunca rompa por el log.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    # debug por entorno (FLASK_DEBUG=1 para activarlo). Por defecto OFF:
    # evita exponer el debugger interactivo en la red del laboratorio.
    debug = os.environ.get("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")

    print("=" * 50)
    print("  Daiver Control CUN — Flask Backend")
    print(f"  Robot IP: {ROBOT_IP}")
    print(f"  Server:   http://localhost:5000")
    print(f"  Debug:    {debug}")
    print("=" * 50)

    # use_reloader=False: el reloader reinicia el proceso al guardar archivos
    #   (perderia la conexion al robot a mitad de operacion) y duplicaria el
    #   event loop asyncio y la carga del modelo YOLO.
    # allow_unsafe_werkzeug=True: permite arrancar el server de desarrollo
    #   aunque se lance sin terminal (doble-clic / pythonw / servicio), donde
    #   Flask-SocketIO lanzaria un RuntimeError de lo contrario.
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=debug,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
