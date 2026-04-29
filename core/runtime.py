"""Runtime compartido: Flask app, Socket.IO, event loop asyncio.

Este modulo NO debe importar de otros core/* — es la base que todos los
demas usan. Asi evitamos imports circulares.

Uso tipico desde otros modulos:
    from core.runtime import socketio, run_async, get_pub_sub

    if get_pub_sub():
        run_async(robot_send_command("BalanceStand"))
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Coroutine, Optional

from flask import Flask
from flask_socketio import SocketIO


# ────────────────────────────────────────────────────────────────────
# Flask app + Socket.IO (singletons globales)
#
# IMPORTANTE: root_path se fija a la raiz del proyecto (un nivel arriba
# de core/) para que send_from_directory("src", ...) y send_from_directory(
# "informes", ...) sigan resolviendo a las carpetas reales aunque el
# modulo Flask viva en core/. Sin esto, Flask asume root_path = core/ y
# todas las rutas estaticas devuelven 404.
# ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

app = Flask(
    __name__,
    static_folder=os.path.join(PROJECT_ROOT, "src"),
    template_folder=os.path.join(PROJECT_ROOT, "src"),
    root_path=PROJECT_ROOT,
)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ────────────────────────────────────────────────────────────────────
# Event loop asyncio en thread dedicado (para WebRTC + asyncio.publish_*)
# ────────────────────────────────────────────────────────────────────
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None


def _start_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def ensure_event_loop() -> None:
    """Crea (o reusa) el event loop si todavia no esta corriendo."""
    global _event_loop, _loop_thread
    if _event_loop is None or not _event_loop.is_running():
        _event_loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_start_event_loop, args=(_event_loop,), daemon=True
        )
        _loop_thread.start()


def run_async(coro: Coroutine[Any, Any, Any], timeout: float = 30.0) -> Any:
    """Ejecuta una corutina en el event loop y bloquea hasta el resultado."""
    ensure_event_loop()
    assert _event_loop is not None
    future = asyncio.run_coroutine_threadsafe(coro, _event_loop)
    return future.result(timeout=timeout)


def run_async_no_wait(coro: Coroutine[Any, Any, Any]):
    """Lanza una corutina sin esperar (para tareas largas)."""
    ensure_event_loop()
    assert _event_loop is not None
    return asyncio.run_coroutine_threadsafe(coro, _event_loop)


# ────────────────────────────────────────────────────────────────────
# Conexion WebRTC al Go2 — referencias compartidas.
#
# Antes vivian como `global robot_connection, robot_pub_sub` repartidas
# por todo app.py. Las centralizamos aqui con get/set para que cualquier
# modulo las vea siempre frescas.
# ────────────────────────────────────────────────────────────────────
_robot_connection: Any = None
_robot_pub_sub: Any = None


def set_connection(conn: Any, pub_sub: Any) -> None:
    global _robot_connection, _robot_pub_sub
    _robot_connection = conn
    _robot_pub_sub = pub_sub


def clear_connection() -> None:
    global _robot_connection, _robot_pub_sub
    _robot_connection = None
    _robot_pub_sub = None


def get_connection() -> Any:
    return _robot_connection


def get_pub_sub() -> Any:
    return _robot_pub_sub
