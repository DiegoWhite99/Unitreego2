"""Endpoints de Auto-Ruta (waypoint follower)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from core import missions
from core.autoroute import autoroute_follow_loop
from core.logging_utils import emit_log
from core.perception.lidar import proximity_enable_async
from core.primitives import robot_send_command
from core.runtime import run_async, run_async_no_wait
from core.state import autoroute_state, proximity_sensor, robot_state


# Flags de ruta que el cliente puede mandar (se mapean 1:1 a autoroute_state).
_FLAG_KEYS = (
    "translate_to_pose", "smooth_mode", "pause_on_person",
    "strict_path_mode", "ai_path_assist",
)


bp = Blueprint("autoroute", __name__)


def _parse_waypoints(pts) -> list:
    """Convierte puntos crudos del cliente en waypoints {x,y[,theta]}."""
    out = []
    for p in pts or []:
        if not (isinstance(p, dict) and "x" in p and "y" in p):
            continue
        try:
            wp = {"x": float(p["x"]), "y": float(p["y"])}
        except (TypeError, ValueError):
            continue
        if p.get("theta") is not None:
            try:
                wp["theta"] = float(p["theta"])
            except (TypeError, ValueError):
                pass
        out.append(wp)
    return out


def _start_route(waypoints: list, cycles, flags: dict) -> None:
    """Configura autoroute_state y lanza el loop. Asume validacion previa."""
    # Activa el sensor si no lo esta (autodetencion en obstaculos).
    if not proximity_sensor["enabled"]:
        try:
            run_async(proximity_enable_async())
            proximity_sensor["enabled"] = True
        except Exception as exc:
            emit_log("warning", f"No se pudo activar sensor: {exc}")

    autoroute_state["waypoints"]           = waypoints
    autoroute_state["cycles_total"]        = max(1, int(cycles or 1))
    autoroute_state["cycle_now"]           = 0
    autoroute_state["wp_now"]              = 0
    autoroute_state["_cancel"]             = False
    autoroute_state["running"]             = True
    autoroute_state["translate_to_pose"]   = bool(flags.get("translate_to_pose"))
    autoroute_state["smooth_mode"]         = bool(flags.get("smooth_mode"))
    autoroute_state["pause_on_person"]     = bool(flags.get("pause_on_person", True))
    autoroute_state["person_pause_active"] = False
    autoroute_state["strict_path_mode"]    = bool(flags.get("strict_path_mode", True))
    autoroute_state["ai_path_assist"]      = bool(flags.get("ai_path_assist", True))
    autoroute_state["_task"]               = run_async_no_wait(autoroute_follow_loop())


@bp.route("/api/autoroute/start", methods=["POST"])
def api_autoroute_start():
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if autoroute_state["running"]:
        return jsonify({"status": "error",
                        "message": "Ya hay una ruta en curso"}), 409

    data = request.get_json(silent=True) or {}
    cycles = int(data.get("cycles", 1) or 1)
    waypoints = _parse_waypoints(data.get("points"))
    if len(waypoints) < 2:
        return jsonify({"status": "error",
                        "message": "Ruta vacía o incompleta"}), 400

    flags = {k: data.get(k) for k in _FLAG_KEYS if k in data}
    _start_route(waypoints, cycles, flags)

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


# ────────────────────────────────────────────────────────────────────
# Misiones: rutas con nombre persistidas en disco (data/missions/).
# Reemplazan al unico `localStorage.daiver:lastRoute` del frontend: ahora
# se pueden guardar/listar/cargar/borrar varias rutas con nombre, al estilo
# del panel "Missions" de BotBrain (pero sin ROS ni base de datos).
# ────────────────────────────────────────────────────────────────────
@bp.route("/api/autoroute/missions", methods=["GET"])
def api_missions_list():
    return jsonify({"status": "ok", "missions": missions.list_missions()})


@bp.route("/api/autoroute/missions", methods=["POST"])
def api_missions_save():
    data = request.get_json(silent=True) or {}
    try:
        saved = missions.save_mission(data)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    emit_log("success",
             f"Misión guardada: '{saved['name']}' ({len(saved['waypoints'])} wp)")
    return jsonify({"status": "ok", "mission": saved})


@bp.route("/api/autoroute/missions/<mid>", methods=["GET"])
def api_missions_get(mid):
    m = missions.get_mission(mid)
    if not m:
        return jsonify({"status": "error", "message": "Misión no encontrada"}), 404
    return jsonify({"status": "ok", "mission": m})


@bp.route("/api/autoroute/missions/<mid>", methods=["DELETE"])
def api_missions_delete(mid):
    if not missions.delete_mission(mid):
        return jsonify({"status": "error", "message": "Misión no encontrada"}), 404
    emit_log("info", f"Misión eliminada: {mid}")
    return jsonify({"status": "ok"})


@bp.route("/api/autoroute/missions/<mid>/start", methods=["POST"])
def api_missions_start(mid):
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if autoroute_state["running"]:
        return jsonify({"status": "error",
                        "message": "Ya hay una ruta en curso"}), 409
    m = missions.get_mission(mid)
    if not m:
        return jsonify({"status": "error", "message": "Misión no encontrada"}), 404

    data = request.get_json(silent=True) or {}
    cycles = int(data.get("cycles", m.get("cycles", 1)) or 1)
    flags = dict(m.get("flags") or {})
    for k in _FLAG_KEYS:            # overrides puntuales desde el body
        if k in data:
            flags[k] = bool(data[k])

    _start_route(list(m["waypoints"]), cycles, flags)
    emit_log("success",
             f"Auto-Ruta (misión '{m['name']}'): "
             f"{len(m['waypoints'])} wp × {cycles} ciclos")
    return jsonify({"status": "ok", "mission": m["id"],
                    "waypoints": len(m["waypoints"]), "cycles": max(1, cycles)})


@bp.route("/api/autoroute/goto", methods=["POST"])
def api_autoroute_goto():
    """Ir-a-punto: navega a un solo objetivo (sin retorno al origen)."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "Robot no conectado"}), 400
    if autoroute_state["running"]:
        return jsonify({"status": "error",
                        "message": "Ya hay una ruta en curso"}), 409

    data = request.get_json(silent=True) or {}
    try:
        x = float(data["x"])
        y = float(data["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"status": "error", "message": "Faltan coordenadas x/y"}), 400

    wp = {"x": x, "y": y}
    if data.get("theta") is not None:
        try:
            wp["theta"] = float(data["theta"])
        except (TypeError, ValueError):
            pass

    # Un solo waypoint, frame absoluto del lidar, sin retorno ni asistente IA.
    flags = {
        "translate_to_pose": False,
        "smooth_mode": bool(data.get("smooth_mode", False)),
        "pause_on_person": bool(data.get("pause_on_person", True)),
        "strict_path_mode": False,
        "ai_path_assist": False,
    }
    _start_route([wp], 1, flags)
    emit_log("info", f"Ir-a-punto: ({x:.2f}, {y:.2f})")
    return jsonify({"status": "ok", "target": {"x": x, "y": y}})
