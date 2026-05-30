"""Endpoints de conexion al robot, status, ping y configuracion."""

from __future__ import annotations

import os
import re
import time

from flask import Blueprint, jsonify, request

from config.config import ROBOT_IP

from core.connection import robot_connect, robot_disconnect
from core.logging_utils import emit_state_update
from core.runtime import run_async
from core.state import (
    request_stop_routine,
    robot_state,
)


bp = Blueprint("connection", __name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")


def _upsert_env_var(key: str, value: str) -> None:
    """Inserta o actualiza `KEY=value` en el .env preservando TODO lo demas.

    Antes esta config se escribia sobre config/config.py sobrescribiendolo
    entero (perdiendo .env loader, clave AES, modelos y API keys). Ahora
    persistimos solo la variable en el .env, que es de donde config.py la
    lee al arrancar.
    """
    lines: list[str] = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines: list[str] = []
    found = False
    for ln in lines:
        stripped = ln.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.split("=", 1)[0].strip()
            if existing_key == key:
                new_lines.append(f"{key}={value}\n")
                found = True
                continue
        new_lines.append(ln)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@bp.route("/api/status")
def api_status():
    return jsonify(robot_state)


@bp.route("/api/ping")
def api_ping():
    """Endpoint ligero para medir latencia. Devuelve <1 ms de procesamiento."""
    return jsonify({
        "ok":              True,
        "ts":              time.time(),
        "robot_connected": robot_state["connected"],
    })


@bp.route("/api/connect", methods=["POST"])
def api_connect():
    if robot_state["connected"]:
        return jsonify({"status": "error", "message": "Ya conectado"}), 400

    data = request.get_json() or {}
    ip = data.get("ip", ROBOT_IP)

    try:
        run_async(robot_connect(ip))
        return jsonify({"status": "ok", "message": f"Conectado a {ip}"})
    except Exception as e:
        robot_state["connected"] = False
        emit_state_update()
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    try:
        request_stop_routine()
        run_async(robot_disconnect())
        return jsonify({"status": "ok", "message": "Desconectado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/config/ip", methods=["POST"])
def api_update_ip():
    """Actualiza la IP del robot persistiendola en el .env (no en config.py)."""
    data = request.get_json() or {}
    new_ip = data.get("ip", "").strip()
    if not new_ip:
        return jsonify({"status": "error", "message": "IP vacia"}), 400

    # Validacion basica: IPs, hostnames y opcional :puerto. Evita inyectar
    # contenido raro en el .env.
    if not re.match(r"^[A-Za-z0-9_.\-:]+$", new_ip):
        return jsonify({"status": "error", "message": "IP/host invalido"}), 400

    try:
        _upsert_env_var("ROBOT_IP", new_ip)
        os.environ["ROBOT_IP"] = new_ip  # refleja el cambio en runtime
        robot_state["ip"] = new_ip
        from core.logging_utils import emit_log
        emit_log("info", f"IP del robot actualizada en .env: {new_ip}")
        return jsonify({"status": "ok", "ip": new_ip})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/config", methods=["GET"])
def api_config():
    # Valor vivo: el que se haya guardado en .env/runtime, con fallback al
    # importado al arranque.
    current_ip = os.environ.get("ROBOT_IP") or robot_state.get("ip") or ROBOT_IP

    return jsonify({
        "robot_ip": current_ip,
        "commands": [
            "Damp", "BalanceStand", "StopMove", "Move",
            "SwitchGait", "BodyHeight", "Hello", "Stretch",
            "RecoveryStand", "Euler", "SitDown", "StandDown", "RiseSit",
            "Scrape", "FrontFlip", "FrontJump", "FrontPounce",
            "WiggleHips", "GetState", "EconomicGait",
            "Dance1", "Dance2", "FingerHeart",
        ],
        "actions": [
            "stand", "sit", "lie", "rise", "recovery", "hello", "stretch",
            "dance1", "dance2", "wiggle", "scrape", "heart",
            "frontflip", "frontjump", "frontpounce",
        ],
        "routines": ["patrol", "jump", "explore"],
    })
