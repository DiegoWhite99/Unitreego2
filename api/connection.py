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
    """Actualiza la IP del robot en config/config.py."""
    data = request.get_json() or {}
    new_ip = data.get("ip", "").strip()
    if not new_ip:
        return jsonify({"status": "error", "message": "IP vacia"}), 400

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "config.py"
    )
    try:
        with open(config_path, "w") as f:
            f.write(f'ROBOT_IP = "{new_ip}"\n')
        robot_state["ip"] = new_ip
        from core.logging_utils import emit_log
        emit_log("info", f"IP actualizada en config.py: {new_ip}")
        return jsonify({"status": "ok", "ip": new_ip})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/config", methods=["GET"])
def api_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "config.py"
    )
    current_ip = ROBOT_IP
    try:
        with open(config_path, "r") as f:
            content = f.read()
            match = re.search(r'ROBOT_IP\s*=\s*"([^"]+)"', content)
            if match:
                current_ip = match.group(1)
    except Exception:
        pass

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
