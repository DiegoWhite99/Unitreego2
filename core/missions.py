"""Persistencia de misiones de Auto-Ruta (rutas con nombre, en disco).

Una "mision" es una ruta con nombre guardada como JSON en
``data/missions/<id>.json``. Da el modelo de BotBrain (una lista de patrullas
con nombre que se cargan y ejecutan) SIN depender de ROS ni de una base de
datos: hasta ahora el frontend solo guardaba UNA ruta en ``localStorage``.

Formato de una mision::

    {
      "id": "ruta-oficina-1-a1b2c3",
      "name": "Ruta Oficina 1",
      "created": "2026-06-05T09:30:00",
      "updated": "2026-06-05T09:31:00",
      "waypoints": [{"x": 0.0, "y": 0.0, "theta": null}, ...],
      "cycles": 1,
      "flags": {
          "translate_to_pose": true,
          "smooth_mode": false,
          "pause_on_person": true,
          "strict_path_mode": true,
          "ai_path_assist": true
      },
      "labels": [{"x": .., "y": .., "text": ".."}]
    }

Las operaciones de archivo corren en el hilo de la request Flask (NO en el
event loop asyncio compartido), asi que el IO bloqueante aqui es seguro.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

MISSIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "missions"

# Flags conocidos de autoroute_state y su default (se persisten con la ruta).
_FLAG_DEFAULTS = {
    "translate_to_pose": True,
    "smooth_mode": False,
    "pause_on_person": True,
    "strict_path_mode": True,
    "ai_path_assist": True,
}

_MAX_CYCLES = 99
_MAX_WAYPOINTS = 500
_MAX_NAME = 80


def _ensure_dir() -> None:
    MISSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (base or "ruta")[:40]


def _new_id(name: str) -> str:
    return f"{_slugify(name)}-{uuid.uuid4().hex[:6]}"


def _safe_id(mid: Any) -> Optional[str]:
    """Valida que el id sea un nombre de archivo seguro (sin path traversal)."""
    if not isinstance(mid, str):
        return None
    return mid if re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,79}", mid) else None


def _coerce_waypoint(p: Any) -> Optional[dict]:
    if not isinstance(p, dict):
        return None
    try:
        wp = {"x": float(p["x"]), "y": float(p["y"])}
    except (KeyError, TypeError, ValueError):
        return None
    theta = p.get("theta")
    if theta is not None:
        try:
            wp["theta"] = float(theta)
        except (TypeError, ValueError):
            pass
    return wp


def _coerce_label(lbl: Any) -> Optional[dict]:
    if not isinstance(lbl, dict):
        return None
    try:
        return {
            "x": float(lbl["x"]),
            "y": float(lbl["y"]),
            "text": str(lbl.get("text", ""))[:120],
        }
    except (KeyError, TypeError, ValueError):
        return None


def _sanitize(data: dict, existing: Optional[dict] = None) -> dict:
    """Normaliza/valida un payload de mision. Lanza ValueError si es invalido."""
    if not isinstance(data, dict):
        raise ValueError("payload no es un objeto")

    name = str(data.get("name", "")).strip()[:_MAX_NAME] or "Ruta sin nombre"

    raw_wps = data.get("waypoints")
    if not isinstance(raw_wps, list):
        raise ValueError("waypoints debe ser una lista")
    waypoints = [w for w in (_coerce_waypoint(p) for p in raw_wps) if w]
    if len(waypoints) < 2:
        raise ValueError("una mision necesita al menos 2 waypoints validos")
    if len(waypoints) > _MAX_WAYPOINTS:
        raise ValueError(f"demasiados waypoints (max {_MAX_WAYPOINTS})")

    try:
        cycles = int(data.get("cycles", 1) or 1)
    except (TypeError, ValueError):
        cycles = 1
    cycles = max(1, min(_MAX_CYCLES, cycles))

    in_flags = data.get("flags") or {}
    flags = {k: bool(in_flags.get(k, d)) for k, d in _FLAG_DEFAULTS.items()}

    raw_labels = data.get("labels")
    labels = (
        [lb for lb in (_coerce_label(x) for x in raw_labels) if lb]
        if isinstance(raw_labels, list)
        else []
    )

    now = _now_iso()
    if existing:
        mid = existing["id"]
        created = existing.get("created", now)
    else:
        mid = _new_id(name)
        created = now

    return {
        "id": mid,
        "name": name,
        "created": created,
        "updated": now,
        "waypoints": waypoints,
        "cycles": cycles,
        "flags": flags,
        "labels": labels,
    }


def _path(mid: str) -> Path:
    return MISSIONS_DIR / f"{mid}.json"


def _read_file(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def list_missions() -> list[dict]:
    """Todas las misiones, las mas recientes primero."""
    _ensure_dir()
    out: list[dict] = []
    for p in MISSIONS_DIR.glob("*.json"):
        obj = _read_file(p)
        if obj and obj.get("id"):
            out.append(obj)
    out.sort(key=lambda m: m.get("updated", ""), reverse=True)
    return out


def get_mission(mid: str) -> Optional[dict]:
    sid = _safe_id(mid)
    return _read_file(_path(sid)) if sid else None


def save_mission(data: dict) -> dict:
    """Crea (sin id) o actualiza (con id) una mision. Devuelve la guardada."""
    _ensure_dir()
    existing: Optional[dict] = None
    raw_id = data.get("id")
    if raw_id:
        sid = _safe_id(raw_id)
        if not sid:
            raise ValueError("id de mision invalido")
        existing = _read_file(_path(sid)) or {"id": sid, "created": _now_iso()}

    mission = _sanitize(data, existing=existing)
    path = _path(mission["id"])
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mission, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # escritura atomica
    return mission


def delete_mission(mid: str) -> bool:
    sid = _safe_id(mid)
    if not sid:
        return False
    path = _path(sid)
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception:
        return False
    return False
