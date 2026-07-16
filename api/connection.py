"""Endpoints de conexion al robot, status, ping y configuracion."""

from __future__ import annotations

import base64
import json
import os
import re
import socket
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

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")


def _upsert_env_var(key: str, value: str) -> None:
    """Inserta o actualiza `KEY=value` en el .env preservando TODO lo demas.

    Antes esta config se escribia sobre config/config.py sobrescribiendolo
    entero (perdiendo .env loader, clave AES, modelos y API keys). Ahora
    persistimos solo la variable en el .env, que es de donde config.py la
    lee al arrancar.
    """
    lines: list[str] = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines: list[str] = []
    found = False
    for ln in lines:
        stripped = ln.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.split("=", 1)[0].strip()
            if existing_key == key:
                new_lines.append(f"{key}={value}\n")
                found = True
                continue
        new_lines.append(ln)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# ────────────────────────────────────────────────────────────────────
# Autodescubrimiento del robot en la LAN.
#
# Motivacion: el Go2 recibe una IP distinta cada vez que se une al WiFi
# (DHCP). En vez de perseguir la IP a mano en el .env, escaneamos la(s)
# subred(es) locales buscando quien responde el handshake del Go2 en el
# puerto 9991, y confirmamos que es el robot con /con_notify (data2).
# ────────────────────────────────────────────────────────────────────
_HANDSHAKE_PORT = 9991


def _local_subnet_prefixes() -> set[str]:
    """Prefijos /24 (p.ej. '192.168.2.') donde tiene sentido buscar: la
    subred de la IP local del PC + la de la IP del robot configurada."""
    prefixes: set[str] = set()

    def _add(ip: str) -> None:
        host = ip.split(":", 1)[0]          # descarta :puerto si lo hubiera
        parts = host.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            prefixes.add(".".join(parts[:3]) + ".")

    # IP con la que el PC sale a la red (sin enviar nada; solo fija la ruta).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        _add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # IP del robot que hay configurada ahora mismo.
    _add(os.environ.get("ROBOT_IP") or ROBOT_IP or "")
    return prefixes


def _con_notify_handshake(ip: str) -> int | None:
    """Devuelve el 'data2' de /con_notify (1/2/3) si responde; None si no.
    Confirma que el host es realmente un Go2 y no otro cacharro en 9991."""
    try:
        import requests
        r = requests.post(f"http://{ip}:{_HANDSHAKE_PORT}/con_notify", timeout=3)
        j = json.loads(base64.b64decode(r.text).decode("utf-8"))
        return j.get("data2")
    except Exception:
        return None


def _scan_for_robot() -> list[dict]:
    """Escanea las subredes locales y devuelve los Go2 encontrados.
    Cada item: {'ip': str, 'handshake': int|None, 'verified': bool}."""
    import concurrent.futures as cf

    candidates = [
        f"{prefix}{host}"
        for prefix in _local_subnet_prefixes()
        for host in range(1, 255)
    ]

    def _port_open(ip: str) -> str | None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            return ip if s.connect_ex((ip, _HANDSHAKE_PORT)) == 0 else None
        finally:
            s.close()

    open_hosts: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=128) as ex:
        for res in ex.map(_port_open, candidates):
            if res:
                open_hosts.append(res)

    found: list[dict] = []
    for ip in open_hosts:
        data2 = _con_notify_handshake(ip)
        found.append({"ip": ip, "handshake": data2, "verified": data2 is not None})

    # Orden de preferencia: (1) confirmados por con_notify primero; (2) si
    # varios responden, la IP ya configurada gana (es la conocida-buena, no
    # pisamos una conexion que ya funciona); (3) el resto ascendente.
    current = (os.environ.get("ROBOT_IP") or ROBOT_IP or "").split(":", 1)[0]
    found.sort(key=lambda f: (not f["verified"], f["ip"] != current, f["ip"]))
    return found


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    """Busca el robot en la red y (si lo halla) persiste su IP en el .env."""
    from core.logging_utils import emit_log

    emit_log("info", "Buscando robot en la red...")
    try:
        found = _scan_for_robot()
    except Exception as e:
        emit_log("error", f"Fallo el escaneo de red: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    if not found:
        msg = "No se encontro ningun robot en la red. Verifica que este encendido y en la misma WiFi."
        emit_log("warning", msg)
        return jsonify({"status": "ok", "found": [], "message": msg})

    best = found[0]
    # Persistimos la IP hallada para que sobreviva a reinicios de la app.
    try:
        _upsert_env_var("ROBOT_IP", best["ip"])
        os.environ["ROBOT_IP"] = best["ip"]
        robot_state["ip"] = best["ip"]
    except Exception:
        pass

    emit_log("success", f"Robot encontrado en {best['ip']} (handshake v{best['handshake']}).")
    return jsonify({"status": "ok", "found": found})


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
    """Actualiza la IP del robot persistiendola en el .env (no en config.py)."""
    data = request.get_json() or {}
    new_ip = data.get("ip", "").strip()
    if not new_ip:
        return jsonify({"status": "error", "message": "IP vacia"}), 400

    # Validacion basica: IPs, hostnames y opcional :puerto. Evita inyectar
    # contenido raro en el .env.
    if not re.match(r"^[A-Za-z0-9_.\-:]+$", new_ip):
        return jsonify({"status": "error", "message": "IP/host invalido"}), 400

    try:
        _upsert_env_var("ROBOT_IP", new_ip)
        os.environ["ROBOT_IP"] = new_ip  # refleja el cambio en runtime
        robot_state["ip"] = new_ip
        from core.logging_utils import emit_log
        emit_log("info", f"IP del robot actualizada en .env: {new_ip}")
        return jsonify({"status": "ok", "ip": new_ip})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/config", methods=["GET"])
def api_config():
    # Valor vivo: el que se haya guardado en .env/runtime, con fallback al
    # importado al arranque.
    current_ip = os.environ.get("ROBOT_IP") or robot_state.get("ip") or ROBOT_IP

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
