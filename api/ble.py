"""Endpoint para escaneo BLE desde la web app.

GET /api/ble/scan   — escanea 6 segundos y devuelve dispositivos encontrados.
                      Prioriza robots Unitree pero devuelve todos si no hay match.
"""

from __future__ import annotations

import asyncio

from flask import Blueprint, jsonify

bp = Blueprint("ble", __name__, url_prefix="/api/ble")

UNITREE_KEYWORDS = ["go2", "unitree", "ut-", "go1", "b1"]


async def _scan(timeout: float = 6.0) -> list[dict]:
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)

    results = []
    for addr, (dev, adv) in devices.items():
        name = dev.name or ""
        rssi = adv.rssi if adv else None
        is_robot = any(k in name.lower() for k in UNITREE_KEYWORDS)
        results.append({
            "name":     name or "Desconocido",
            "address":  addr,
            "rssi":     rssi,
            "is_robot": is_robot,
        })

    # Robots primero, luego resto ordenado por rssi desc
    results.sort(key=lambda d: (not d["is_robot"], -(d["rssi"] or -999)))
    return results


@bp.route("/scan")
def scan():
    """Ejecuta el escaneo BLE en el event loop compartido y devuelve JSON."""
    try:
        from core.runtime import run_async
        devices = run_async(_scan(), timeout=12.0)
        return jsonify({"ok": True, "devices": devices})
    except ImportError:
        # Fallback: event loop propio si se llama fuera del contexto Flask
        try:
            loop = asyncio.new_event_loop()
            devices = loop.run_until_complete(_scan())
            loop.close()
            return jsonify({"ok": True, "devices": devices})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
