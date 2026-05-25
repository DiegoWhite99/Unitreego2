"""Endpoints para autenticación en Unitree Cloud y consulta de robots vinculados.

POST /api/unitree/validate   — valida credenciales y devuelve la lista de robots
GET  /api/unitree/robots     — devuelve la lista guardada en sesión (sin re-autenticar)
"""

from __future__ import annotations

import hashlib
import time
import uuid

from flask import Blueprint, jsonify, request, session

bp = Blueprint("unitree_cloud", __name__, url_prefix="/api/unitree")


def _make_headers(token: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    secret = "XyvkwK45hp5PHfA8"
    sign = hashlib.md5(f"{secret}{ts}{nonce}".encode()).hexdigest()
    return {
        "Content-Type":   "application/x-www-form-urlencoded",
        "DeviceId":       "Samsung/Samsung/SM-S931B/s24/14/34",
        "DevicePlatform": "Android",
        "DeviceModel":    "SM-S931B",
        "SystemVersion":  "34",
        "AppVersion":     "1.11.4",
        "AppLocale":      "en_US",
        "AppTimezone":    "GMT-05:00",
        "Channel":        "UMENG_CHANNEL",
        "User-Agent":     (
            "Mozilla/5.0 (Linux; Android 14; SM-S931B Build/AP3A.240905.015.A2; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.103 "
            "Mobile Safari/537.36"
        ),
        "AppTimestamp":   ts,
        "AppNonce":       nonce,
        "AppSign":        sign,
        "AppName":        "Go2",
        "Token":          token,
    }


BASE_URL = "https://global-robot-api.unitree.com/"


@bp.route("/validate", methods=["POST"])
def validate():
    """Autentica en Unitree Cloud y devuelve los robots vinculados a la cuenta."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return jsonify({"ok": False, "error": "curl_cffi no instalado en el servidor"}), 500

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"ok": False, "error": "Email y contraseña requeridos"}), 400

    sess = cffi_requests.Session(impersonate="chrome120")
    pwd_md5 = hashlib.md5(password.encode()).hexdigest()

    # Login
    resp = sess.post(
        BASE_URL + "login/email",
        data={"email": email, "password": pwd_md5},
        headers=_make_headers(),
        timeout=12,
    )
    resp.encoding = "utf-8"
    login_data = resp.json()

    if login_data.get("code") != 0:
        msg = login_data.get("msg") or "Credenciales inválidas"
        return jsonify({"ok": False, "error": msg}), 401

    token = login_data.get("data", {}).get("accessToken", "")
    if not token:
        return jsonify({"ok": False, "error": "No se obtuvo token de acceso"}), 401

    # Consultar robots vinculados
    resp2 = sess.get(
        BASE_URL + "device/bind/list",
        headers=_make_headers(token),
        timeout=12,
    )
    resp2.encoding = "utf-8"
    devices_data = resp2.json()
    devices_raw = devices_data.get("data") or []

    robots = []
    for d in devices_raw:
        robots.append({
            "sn":   d.get("sn", ""),
            "name": d.get("name") or d.get("sn", "Robot"),
            "key":  d.get("key") or d.get("gcm_key", ""),
        })

    # Guardar en sesión Flask para uso posterior
    session["unitree_robots"] = robots
    session["unitree_email"]  = email

    return jsonify({"ok": True, "robots": robots})


@bp.route("/robots", methods=["GET"])
def get_robots():
    """Devuelve la lista de robots guardada en sesión (no requiere re-autenticar)."""
    robots = session.get("unitree_robots", [])
    return jsonify({"ok": True, "robots": robots})
