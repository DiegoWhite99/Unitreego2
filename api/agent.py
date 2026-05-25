"""Endpoints del agente Diver (chat con tools)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.agents.chat import chat as chat_handler, health as health_handler


bp = Blueprint("agent", __name__)


@bp.route("/api/agente/health", methods=["GET"])
def api_agente_health():
    return jsonify(health_handler())


@bp.route("/api/agente/chat", methods=["POST"])
def api_agente_chat():
    """Recibe un mensaje del usuario, llama al modelo y ejecuta tools.
    Devuelve respuesta + lista de acciones ejecutadas.
    Acepta campo opcional `image_b64` (JPEG base64) para visión del mapa."""
    import base64
    payload  = request.get_json(silent=True) or {}
    user_msg = (payload.get("message") or "").strip()
    history  = payload.get("history") or []
    map_jpg: bytes | None = None
    raw_b64 = payload.get("image_b64") or ""
    if raw_b64:
        try:
            # Quitar prefijo data:image/...;base64, si viene del canvas
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            map_jpg = base64.b64decode(raw_b64)
        except Exception:
            map_jpg = None
    return jsonify(chat_handler(user_msg, history, map_image_jpg=map_jpg))
