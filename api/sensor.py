"""Endpoints del sensor de proximidad (LiDAR L1 + ROBOTODOM)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.logging_utils import emit_log
from core.perception.lidar import (
    proximity_disable_async,
    proximity_enable_async,
)
from core.runtime import run_async
from core.state import proximity_sensor, robot_state


bp = Blueprint("sensor", __name__)


@bp.route("/api/sensor/status", methods=["GET"])
def api_sensor_status():
    return jsonify({
        "status":          "ok",
        "enabled":         proximity_sensor["enabled"],
        "stop_distance_m": proximity_sensor["stop_distance_m"],
        "last_distance_m": proximity_sensor["_last_distance"],
        "robot_connected": robot_state["connected"],
    })


@bp.route("/api/sensor/toggle", methods=["POST"])
def api_sensor_toggle():
    """Activa/desactiva el sensor de proximidad del lidar del robot."""
    data = request.get_json(silent=True) or {}
    desired = data.get("enabled")
    if desired is None:
        desired = not proximity_sensor["enabled"]
    desired = bool(desired)

    if desired and not robot_state["connected"]:
        return jsonify({
            "status":  "error",
            "message": "El robot no esta conectado. Conecta primero para usar el sensor.",
            "enabled": False,
        }), 400

    proximity_sensor["enabled"] = desired

    try:
        if desired:
            ok = run_async(proximity_enable_async())
            if not ok:
                proximity_sensor["enabled"] = False
                return jsonify({
                    "status":  "error",
                    "message": "No se pudo activar el sensor del robot.",
                    "enabled": False,
                }), 500
            emit_log("info", "Sensor de proximidad ACTIVADO (lidar Go2)")
        else:
            run_async(proximity_disable_async())
            emit_log("info", "Sensor de proximidad desactivado")
    except Exception as exc:
        proximity_sensor["enabled"] = False
        return jsonify({
            "status": "error", "message": str(exc), "enabled": False,
        }), 500

    return jsonify({
        "status":          "ok",
        "enabled":         proximity_sensor["enabled"],
        "stop_distance_m": proximity_sensor["stop_distance_m"],
    })
