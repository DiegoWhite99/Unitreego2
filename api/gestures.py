"""Endpoints del reactor de gestos."""

from __future__ import annotations

from flask import Blueprint, jsonify

from core.agents.gestures import gesture_reactor


bp = Blueprint("gestures", __name__)


@bp.route("/api/gestures/state", methods=["GET"])
def api_gestures_state():
    return jsonify(gesture_reactor.state())


@bp.route("/api/gestures/start", methods=["POST"])
def api_gestures_start():
    gesture_reactor.start()
    return jsonify({"status": "ok", **gesture_reactor.state()})


@bp.route("/api/gestures/stop", methods=["POST"])
def api_gestures_stop():
    gesture_reactor.stop()
    return jsonify({"status": "ok", **gesture_reactor.state()})


@bp.route("/api/gestures/debug", methods=["GET"])
def api_gestures_debug():
    """Snapshot de diagnostico. Util cuando el toggle esta ON pero el robot
    no saluda: revela si el problema es el modelo YOLO, el robot, o que no
    hay personas en cuadro."""
    return jsonify(gesture_reactor.debug_snapshot())
