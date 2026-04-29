"""Endpoints de Follow-QR (perseguir un código QR detectado)."""

from __future__ import annotations

from flask import Blueprint, jsonify

from yolo_detector import detector as yolo_detector

from core.follow import follow_loop
from core.logging_utils import emit_log
from core.primitives import robot_send_command
from core.runtime import run_async, run_async_no_wait
from core.state import autoroute_state, follow_state, robot_state


bp = Blueprint("follow", __name__)


@bp.route("/api/follow/start", methods=["POST"])
def api_follow_start():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if follow_state["running"]:
        return jsonify({"status": "error", "message": "Ya estoy siguiendo"}), 409
    if autoroute_state.get("running"):
        return jsonify({
            "status": "error",
            "message": "Auto-Ruta esta corriendo, detenla primero",
        }), 409
    if not yolo_detector.is_running():
        return jsonify({
            "status": "error",
            "message": "YOLO no esta corriendo. Iniciala desde la pagina de ruta guiada.",
        }), 400

    follow_state["_cancel"] = False
    follow_state["running"] = True
    follow_state["_task"] = run_async_no_wait(follow_loop())
    emit_log("success", "Follow-QR: iniciado")
    return jsonify({"status": "ok"})


@bp.route("/api/follow/stop", methods=["POST"])
def api_follow_stop():
    follow_state["_cancel"] = True
    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
    except Exception:
        pass
    emit_log("info", "Follow-QR: detenido por el usuario")
    return jsonify({"status": "ok"})


@bp.route("/api/follow/status", methods=["GET"])
def api_follow_status():
    return jsonify({
        "status":  "ok",
        "running": follow_state["running"],
        "x":       follow_state["_last_x"],
        "z":       follow_state["_last_z"],
        "reason":  follow_state["_last_reason"],
        "qr":      follow_state["_last_qr_text"],
    })
