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
    Devuelve respuesta + lista de acciones ejecutadas."""
    payload = request.get_json(silent=True) or {}
    user_msg = (payload.get("message") or "").strip()
    history = payload.get("history") or []
    return jsonify(chat_handler(user_msg, history))
