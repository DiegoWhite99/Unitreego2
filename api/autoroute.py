"""Endpoints de Auto-Ruta (waypoint follower)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.autoroute import autoroute_follow_loop
from core.logging_utils import emit_log
from core.perception.lidar import proximity_enable_async
from core.primitives import robot_send_command
from core.runtime import run_async, run_async_no_wait
from core.state import autoroute_state, proximity_sensor, robot_state


bp = Blueprint("autoroute", __name__)


@bp.route("/api/autoroute/start", methods=["POST"])
def api_autoroute_start():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if autoroute_state["running"]:
        return jsonify({"status": "error",
                        "message": "Ya hay una ruta en curso"}), 409

    data = request.get_json(silent=True) or {}
    pts = data.get("points") or []
    cycles = int(data.get("cycles", 1) or 1)

    waypoints = [
        {"x": float(p["x"]), "y": float(p["y"])}
        for p in pts
        if isinstance(p, dict) and "x" in p and "y" in p
    ]
    if len(waypoints) < 2:
        return jsonify({"status": "error",
                        "message": "Ruta vacía o incompleta"}), 400

    # Activa el sensor si no lo esta (autodetencion en obstaculos).
    if not proximity_sensor["enabled"]:
        try:
            run_async(proximity_enable_async())
            proximity_sensor["enabled"] = True
        except Exception as exc:
            emit_log("warning", f"No se pudo activar sensor: {exc}")

    autoroute_state["waypoints"]         = waypoints
    autoroute_state["cycles_total"]      = max(1, cycles)
    autoroute_state["cycle_now"]         = 0
    autoroute_state["wp_now"]            = 0
    autoroute_state["_cancel"]           = False
    autoroute_state["running"]           = True
    autoroute_state["translate_to_pose"] = bool(data.get("translate_to_pose"))
    autoroute_state["smooth_mode"]       = bool(data.get("smooth_mode"))
    autoroute_state["pause_on_person"]   = bool(data.get("pause_on_person", True))
    autoroute_state["person_pause_active"] = False
    autoroute_state["strict_path_mode"]  = bool(data.get("strict_path_mode", True))
    autoroute_state["ai_path_assist"]    = bool(data.get("ai_path_assist", True))
    autoroute_state["_task"]             = run_async_no_wait(autoroute_follow_loop())

    emit_log("success",
             f"Auto-Ruta iniciada: {len(waypoints)} waypoints × {cycles} ciclos")
    return jsonify({
        "status":    "ok",
        "waypoints": len(waypoints),
        "cycles":    autoroute_state["cycles_total"],
    })


@bp.route("/api/autoroute/stop", methods=["POST"])
def api_autoroute_stop():
    autoroute_state["_cancel"] = True
    autoroute_state["person_pause_active"] = False
    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
    except Exception:
        pass
    emit_log("info", "Auto-Ruta: detenida por el usuario")
    return jsonify({"status": "ok"})


@bp.route("/api/autoroute/status", methods=["GET"])
def api_autoroute_status():
    return jsonify({
        "status":          "ok",
        "running":         autoroute_state["running"],
        "cycle":           autoroute_state["cycle_now"],
        "cycle_total":     autoroute_state["cycles_total"],
        "waypoint":        autoroute_state["wp_now"],
        "waypoint_total": len(autoroute_state["waypoints"]),
        "person_pause_active": bool(autoroute_state.get("person_pause_active")),
        "strict_path_mode": bool(autoroute_state.get("strict_path_mode", True)),
        "ai_path_assist": bool(autoroute_state.get("ai_path_assist", True)),
    })
