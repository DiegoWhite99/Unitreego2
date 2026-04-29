"""Endpoints de movimiento, comandos directos, acciones, rutinas."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.logging_utils import emit_log, emit_state_update
from core.poses import (
    robot_heart_safe,
    robot_lie_safe,
    robot_recovery_safe,
    robot_rise_safe,
    robot_scrape_safe,
    robot_sit_safe,
    robot_wiggle_safe,
)
from core.primitives import robot_send_command
from core.routines import ROUTINE_MAP
from core.runtime import get_pub_sub, run_async, run_async_no_wait
from core.state import (
    request_stop_routine,
    robot_state,
)


bp = Blueprint("motion", __name__)


# ────────────────────────────────────────────────────────────────────
# Comandos directos al SDK
# ────────────────────────────────────────────────────────────────────
_VALID_COMMANDS = {
    "Damp", "BalanceStand", "StopMove", "Move",
    "SwitchGait", "BodyHeight", "FootRaiseHeight", "SpeedLevel",
    "Hello", "Stretch", "RecoveryStand", "Euler",
    "SitDown", "StandDown", "RiseSit", "Pose", "Scrape",
    "FrontFlip", "FrontJump", "FrontPounce",
    "WiggleHips", "GetState", "EconomicGait",
    "Dance1", "Dance2", "FingerHeart",
}


@bp.route("/api/command", methods=["POST"])
def api_command():
    """Ejecuta un SPORT_CMD individual."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    data = request.get_json()
    cmd = data.get("command")
    parameter = data.get("parameter")

    if cmd not in _VALID_COMMANDS:
        return jsonify({"status": "error",
                        "message": f"Comando invalido: {cmd}"}), 400

    try:
        run_async(robot_send_command(cmd, parameter))
        emit_log("info", f"Comando ejecutado: {cmd}")
        return jsonify({"status": "ok", "command": cmd})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ────────────────────────────────────────────────────────────────────
# Movimiento
# ────────────────────────────────────────────────────────────────────
@bp.route("/api/move", methods=["POST"])
def api_move():
    """Move puntual (control en tiempo real). Limita velocidades."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    data = request.get_json()
    x = max(-0.8, min(0.8, float(data.get("x", 0.0))))
    y = max(-0.5, min(0.5, float(data.get("y", 0.0))))
    z = max(-1.5, min(1.5, float(data.get("z", 0.0))))

    try:
        run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
        return jsonify({"status": "ok", "x": x, "y": y, "z": z})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/stop", methods=["POST"])
def api_stop_move():
    """Detiene todo movimiento."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400
    try:
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/emergency", methods=["POST"])
def api_emergency():
    """Parada de emergencia (Damp) — amortigua todos los motores."""
    request_stop_routine()
    try:
        if get_pub_sub():
            run_async(robot_send_command("Damp"))
        emit_log("warning", "PARADA DE EMERGENCIA ACTIVADA")
        robot_state["mode"] = "Emergencia"
        emit_state_update()
        return jsonify({"status": "ok", "message": "Emergencia activada"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ────────────────────────────────────────────────────────────────────
# Acciones predefinidas — antes 7 if-statements duplicados; ahora un mapa.
# ────────────────────────────────────────────────────────────────────

# Acciones "estabilizadas" → corutina + nombre que se reporta como mode.
_SAFE_ACTIONS = {
    "sit":      (robot_sit_safe,      "SitDown",       "sit (sentado estabilizado)"),
    "rise":     (robot_rise_safe,     "RiseSit",       "rise (levantarse estabilizado)"),
    "recovery": (robot_recovery_safe, "RecoveryStand", "recovery (recuperacion estabilizada)"),
    "lie":      (robot_lie_safe,      "StandDown",     "lie (acostarse estabilizado)"),
    "scrape":   (robot_scrape_safe,   "Scrape",        "scrape (Scrape real estabilizado)"),
    "wiggle":   (robot_wiggle_safe,   "WiggleHips",    "wiggle (meneo estabilizado)"),
    "heart":    (robot_heart_safe,    "FingerHeart",   "heart (FingerHeart suavizado)"),
}

# Acciones simples → SPORT_CMD directo.
_SIMPLE_ACTIONS = {
    "stand":       "BalanceStand",
    "hello":       "Hello",
    "stretch":     "Stretch",
    "dance1":      "Dance1",
    "dance2":      "Dance2",
    "frontflip":   "FrontFlip",
    "frontjump":   "FrontJump",
    "frontpounce": "FrontPounce",
}


@bp.route("/api/action", methods=["POST"])
def api_action():
    """Ejecuta una accion/pose predefinida."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    action = (request.get_json() or {}).get("action")

    if action in _SAFE_ACTIONS:
        coro_fn, mode_name, log_label = _SAFE_ACTIONS[action]
        try:
            ok = run_async(coro_fn())
            if not ok:
                return jsonify({"status": "error",
                                "message": f"No se pudo ejecutar {action}"}), 500
            robot_state["mode"] = mode_name
            emit_log("info", f"Accion ejecutada: {log_label}")
            emit_state_update()
            return jsonify({"status": "ok", "action": action, "command": mode_name})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    cmd = _SIMPLE_ACTIONS.get(action)
    if not cmd:
        return jsonify({"status": "error",
                        "message": f"Accion invalida: {action}"}), 400

    try:
        ok = run_async(robot_send_command(cmd))
        if not ok:
            return jsonify({"status": "error",
                            "message": f"No se pudo ejecutar comando: {cmd}"}), 500
        robot_state["mode"] = cmd
        emit_log("info", f"Accion ejecutada: {action} ({cmd})")
        emit_state_update()
        return jsonify({"status": "ok", "action": action, "command": cmd})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ────────────────────────────────────────────────────────────────────
# Rutinas
# ────────────────────────────────────────────────────────────────────
@bp.route("/api/routine", methods=["POST"])
def api_routine():
    """Inicia una rutina pre-grabada (en background)."""
    if not robot_state["connected"]:
        return jsonify({"status": "error", "message": "No conectado"}), 400

    if robot_state["routine_running"]:
        return jsonify({
            "status": "error",
            "message": f"Rutina '{robot_state['routine_name']}' en ejecucion",
        }), 400

    routine = (request.get_json() or {}).get("routine")
    routine_fn = ROUTINE_MAP.get(routine)
    if not routine_fn:
        return jsonify({"status": "error",
                        "message": f"Rutina invalida: {routine}"}), 400

    run_async_no_wait(routine_fn())
    emit_log("info", f"Rutina iniciada: {routine}")
    return jsonify({"status": "ok", "routine": routine})


@bp.route("/api/routine/stop", methods=["POST"])
def api_routine_stop():
    request_stop_routine()
    emit_log("warning", "Deteniendo rutina...")
    return jsonify({"status": "ok"})
