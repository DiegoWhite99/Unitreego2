"""Endpoints para analisis de mapas con IA (imagen -> ruta sugerida)."""

from __future__ import annotations

import base64
import heapq
import json
import os
import urllib.error
import urllib.request
from typing import Any

from flask import Blueprint, jsonify, request

from core.agents.config import (
    GEMINI_API_KEY as AGENT_GEMINI_API_KEY,
    GEMINI_MODEL as AGENT_MODEL,
    GENAI_AVAILABLE,
    is_openai_model,
    openai_client as AGENT_OPENAI_CLIENT,
)


bp = Blueprint("map_ai", __name__)


def _load_openai_client(override_key: str = ""):
    try:
        from openai import OpenAI
    except Exception as exc:
        return None, f"No esta instalado `openai`: {exc}"

    key = (override_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        try:
            from config.config import OPENAI_API_KEY as cfg_key  # type: ignore

            key = (cfg_key or "").strip()
        except Exception:
            key = ""

    if not key:
        return None, "Falta OPENAI_API_KEY en variables de entorno o config/config.py"

    return OpenAI(api_key=key), None


def _resolve_openai_key(override_key: str = "") -> str:
    key = (override_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        from config.config import OPENAI_API_KEY as cfg_key  # type: ignore

        return (cfg_key or "").strip()
    except Exception:
        return ""


def _openai_rest_chat(model: str, prompt: str, data_uri: str, api_key: str) -> tuple[str, str | None]:
    try:
        payload = {
            "model": model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": "Eres un planificador de rutas para robotica movil. Responde solo JSON.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        txt = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        return txt, None
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = str(exc)
        return "", f"Fallo OpenAI REST: {detail[:320]}"
    except Exception as exc:
        return "", f"Fallo OpenAI REST: {exc}"


def _load_gemini_client():
    if not GENAI_AVAILABLE:
        return None, "Falta `google-generativeai` en el backend"

    key = os.environ.get("GEMINI_API_KEY", "").strip() or (AGENT_GEMINI_API_KEY or "").strip()
    if not key:
        try:
            from config.config import GEMINI_API_KEY as cfg_key  # type: ignore

            key = (cfg_key or "").strip()
        except Exception:
            key = ""

    if not key:
        return None, "Falta GEMINI_API_KEY en variables de entorno o config/config.py"

    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        return genai, None
    except Exception as exc:
        return None, f"No se pudo inicializar Gemini: {exc}"


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}

    if text.startswith("```"):
        text = text.strip("`")
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            try:
                parsed = json.loads(text[first_brace : last_brace + 1])
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}


def _clamp01(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return 0.0


def _run_ai_map_inference(prompt: str, raw: bytes, content_type: str, model: str, override_openai_key: str = "") -> tuple[str, str | None]:
    # Rama OpenAI
    if is_openai_model(model):
        client = AGENT_OPENAI_CLIENT
        if client is None or (override_openai_key or "").strip():
            client, err = _load_openai_client(override_openai_key)
            if err:
                client = None

        data_uri = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
        if client is not None:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=0.1,
                    messages=[
                        {
                            "role": "system",
                            "content": "Eres un planificador de rutas para robotica movil. Responde solo JSON.",
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_uri}},
                            ],
                        },
                    ],
                )
                txt = ""
                try:
                    txt = resp.choices[0].message.content or ""
                except Exception:
                    txt = ""
                if txt:
                    return txt, None
            except Exception:
                pass

        api_key = _resolve_openai_key(override_openai_key)
        if not api_key:
            return "", "Falta OPENAI_API_KEY en variables de entorno, config o sesion"
        return _openai_rest_chat(model=model, prompt=prompt, data_uri=data_uri, api_key=api_key)

    # Rama Gemini
    genai, err = _load_gemini_client()
    if err:
        return "", err
    try:
        mdl = genai.GenerativeModel(model)
        out = mdl.generate_content([
            prompt,
            {"mime_type": content_type, "data": raw},
        ])
        txt = getattr(out, "text", "") or ""
        return txt, None
    except Exception as exc:
        return "", f"Fallo Gemini: {exc}"


def _has_openai_ready(override_key: str = "") -> bool:
    if (override_key or "").strip().startswith("sk-"):
        return True
    if AGENT_OPENAI_CLIENT is not None:
        return True
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return True
    try:
        from config.config import OPENAI_API_KEY as cfg_key  # type: ignore

        return bool((cfg_key or "").strip())
    except Exception:
        return False


def _has_gemini_ready() -> bool:
    if not GENAI_AVAILABLE:
        return False
    key = os.environ.get("GEMINI_API_KEY", "").strip() or (AGENT_GEMINI_API_KEY or "").strip()
    if key:
        return True
    try:
        from config.config import GEMINI_API_KEY as cfg_key  # type: ignore

        return bool((cfg_key or "").strip())
    except Exception:
        return False


def _run_ai_with_failover(prompt: str, raw: bytes, content_type: str, preferred_model: str, override_openai_key: str = "") -> tuple[str, str, str, str | None]:
    """Ejecuta inferencia IA real con failover entre proveedores."""
    tried: list[str] = []

    candidates: list[tuple[str, str]] = []
    preferred = (preferred_model or "").strip()
    if preferred:
        candidates.append(("preferred", preferred))

    # Fallback cruzado de proveedor.
    if is_openai_model(preferred):
        candidates.append(("gemini", "gemini-2.5-flash"))
    else:
        candidates.append(("openai", "gpt-4.1-mini"))

    # Garantiza ambos intentos al final si no estaban en lista.
    if all(m != "gpt-4.1-mini" for _, m in candidates):
        candidates.append(("openai", "gpt-4.1-mini"))
    if all(m != "gemini-2.5-flash" for _, m in candidates):
        candidates.append(("gemini", "gemini-2.5-flash"))

    seen = set()
    for _, model in candidates:
        if model in seen:
            continue
        seen.add(model)

        provider = "openai" if is_openai_model(model) else "gemini"
        if provider == "openai" and not _has_openai_ready(override_openai_key):
            tried.append(f"{model}: OPENAI_API_KEY no configurada")
            continue
        if provider == "gemini" and not _has_gemini_ready():
            tried.append(f"{model}: GEMINI_API_KEY no configurada")
            continue

        text, err = _run_ai_map_inference(
            prompt=prompt,
            raw=raw,
            content_type=content_type,
            model=model,
            override_openai_key=override_openai_key,
        )
        if not err and text:
            return text, model, provider, None
        tried.append(f"{model}: {err or 'respuesta vacia'}")

    return "", preferred_model, "none", " | ".join(tried)


def _fallback_map_analysis(raw: bytes) -> dict[str, Any]:
    """Analisis local sin nube cuando no hay API key valida.

    Genera zonas por densidad y una ruta base simple para no bloquear UX.
    """
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("No se pudo decodificar imagen")

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        # Segmentacion de obstaculos / libre (más robusta que solo Canny).
        thr = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            4,
        )
        edges = cv2.Canny(blur, 60, 140)
        obstacles_mask = cv2.bitwise_or(thr, edges)
        kernel = np.ones((3, 3), np.uint8)
        obstacles_mask = cv2.morphologyEx(obstacles_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        obstacles_mask = cv2.dilate(obstacles_mask, kernel, iterations=1)

        free = (obstacles_mask == 0).astype(np.uint8)

        # Conectividad: nos quedamos con el mayor componente libre.
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=8)
        if num_labels > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            best_idx = int(np.argmax(areas)) + 1
            free = (labels == best_idx).astype(np.uint8)

        dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)

        # Zonas por cuadrante con riesgo mixto (densidad obstáculos + estrechez).
        zones: list[dict[str, Any]] = []
        quadrants = [
            ("Noroeste", 0, 0, w // 2, h // 2),
            ("Noreste", w // 2, 0, w - w // 2, h // 2),
            ("Suroeste", 0, h // 2, w // 2, h - h // 2),
            ("Sureste", w // 2, h // 2, w - w // 2, h - h // 2),
        ]
        scores = []
        for _, x, y, ww, hh in quadrants:
            roi_obs = obstacles_mask[y:y + hh, x:x + ww]
            roi_dist = dist[y:y + hh, x:x + ww]
            obs_density = float(np.mean(roi_obs > 0)) if roi_obs.size else 0.0
            mean_clear = float(np.mean(roi_dist)) if roi_dist.size else 0.0
            score = obs_density * 0.72 + (1.0 / max(0.12, mean_clear + 0.08)) * 0.28
            scores.append(score)
        p1 = float(np.percentile(scores, 35)) if scores else 0.0
        p2 = float(np.percentile(scores, 70)) if scores else 0.0
        for (name, x, y, ww, hh), score in zip(quadrants, scores):
            risk = "high" if score >= p2 else ("medium" if score >= p1 else "low")
            zones.append({
                "name": name,
                "risk": risk,
                "x": round(x / max(1, w), 4),
                "y": round(y / max(1, h), 4),
                "w": round(ww / max(1, w), 4),
                "h": round(hh / max(1, h), 4),
                "note": f"Indice de complejidad {score:.2f}",
            })

        # Obstaculos por contorno.
        contours, _ = cv2.findContours(obstacles_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        obstacles = []
        min_area = max(140, (w * h) * 0.0018)
        for c in contours:
            x, y, ww, hh = cv2.boundingRect(c)
            if ww * hh < min_area:
                continue
            obstacles.append({
                "x": round(x / max(1, w), 4),
                "y": round(y / max(1, h), 4),
                "w": round(ww / max(1, w), 4),
                "h": round(hh / max(1, h), 4),
                "kind": "estructura",
            })
            if len(obstacles) >= 28:
                break

        # --- Planificador de ruta local sobre grid reducido (A*). ---
        grid_h = 120
        scale = max(1, int(round(h / grid_h)))
        gh = max(24, h // scale)
        gw = max(24, w // scale)
        free_small = cv2.resize(free, (gw, gh), interpolation=cv2.INTER_NEAREST)
        dist_small = cv2.resize(dist, (gw, gh), interpolation=cv2.INTER_LINEAR)

        # Inflamos obstaculos segun distancia minima segura.
        safe = (dist_small >= 1.2).astype(np.uint8)

        def nearest_free(px: int, py: int) -> tuple[int, int]:
            px = max(0, min(gw - 1, px))
            py = max(0, min(gh - 1, py))
            if safe[py, px] == 1:
                return px, py
            best = (px, py)
            best_d = 10**9
            for y0 in range(max(0, py - 8), min(gh, py + 9)):
                for x0 in range(max(0, px - 8), min(gw, px + 9)):
                    if safe[y0, x0] != 1:
                        continue
                    d = (x0 - px) * (x0 - px) + (y0 - py) * (y0 - py)
                    if d < best_d:
                        best_d = d
                        best = (x0, y0)
            return best

        sx, sy = nearest_free(gw // 2, int(gh * 0.85))
        # target = punto superior más despejado.
        top_band_y0 = max(0, int(gh * 0.08))
        top_band_y1 = max(top_band_y0 + 1, int(gh * 0.30))
        best_t = (sx, max(0, sy - 6))
        best_score = -1.0
        for yy in range(top_band_y0, top_band_y1):
            for xx in range(0, gw):
                if safe[yy, xx] != 1:
                    continue
                score = float(dist_small[yy, xx])
                if score > best_score:
                    best_score = score
                    best_t = (xx, yy)
        tx, ty = nearest_free(best_t[0], best_t[1])

        def astar(start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
            sx0, sy0 = start
            gx0, gy0 = goal
            moves = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
            pq: list[tuple[float, int, int]] = []
            heapq.heappush(pq, (0.0, sx0, sy0))
            gscore = {(sx0, sy0): 0.0}
            parent: dict[tuple[int, int], tuple[int, int]] = {}
            seen = set()

            def hcost(x: int, y: int) -> float:
                return ((x - gx0) ** 2 + (y - gy0) ** 2) ** 0.5

            while pq:
                _, x, y = heapq.heappop(pq)
                if (x, y) in seen:
                    continue
                seen.add((x, y))
                if (x, y) == (gx0, gy0):
                    path = [(x, y)]
                    while (x, y) in parent:
                        x, y = parent[(x, y)]
                        path.append((x, y))
                    path.reverse()
                    return path

                for dx, dy in moves:
                    nx, ny = x + dx, y + dy
                    if nx < 0 or ny < 0 or nx >= gw or ny >= gh:
                        continue
                    if safe[ny, nx] != 1:
                        continue
                    step = 1.4142 if dx != 0 and dy != 0 else 1.0
                    clearance_bonus = float(dist_small[ny, nx]) * 0.12
                    ng = gscore[(x, y)] + step - clearance_bonus
                    if ng < gscore.get((nx, ny), 1e18):
                        gscore[(nx, ny)] = ng
                        parent[(nx, ny)] = (x, y)
                        f = ng + hcost(nx, ny)
                        heapq.heappush(pq, (f, nx, ny))
            return []

        path = astar((sx, sy), (tx, ty))

        def sample_path(p: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
            if not p:
                return []
            if len(p) <= n:
                return p
            out = []
            for i in range(n):
                idx = int(round(i * (len(p) - 1) / max(1, n - 1)))
                out.append(p[idx])
            return out

        sampled = sample_path(path, 8)
        waypoints = []
        for i, (xg, yg) in enumerate(sampled):
            nx = max(0.0, min(1.0, (xg * scale) / max(1, w - 1)))
            ny = max(0.0, min(1.0, (yg * scale) / max(1, h - 1)))
            waypoints.append({"nx": round(nx, 4), "ny": round(ny, 4), "label": f"WP{i + 1}"})

        if len(waypoints) < 2:
            waypoints = [
                {"nx": 0.50, "ny": 0.84, "label": "WP1"},
                {"nx": 0.50, "ny": 0.64, "label": "WP2"},
                {"nx": 0.52, "ny": 0.42, "label": "WP3"},
            ]

        mean_score = float(np.mean(scores)) if scores else 0.0
        confidence = max(0.52, min(0.88, 0.86 - mean_score * 0.22))

        return {
            "analysis": "Analisis local avanzado: segmentacion de espacio libre + planificador de ruta sobre grid.",
            "map_overview": "Modo local con deteccion de zonas y trayectoria por corredor libre.",
            "confidence": round(confidence, 3),
            "scale_hint_m_per_px": 0.05,
            "suggested_waypoints": waypoints,
            "obstacles": obstacles,
            "zones": zones,
            "fallback": True,
        }
    except Exception:
        return {
            "analysis": "No se pudo ejecutar analisis IA remoto. Se devolvio una ruta base de emergencia.",
            "map_overview": "Sin credenciales validas o proveedor no disponible.",
            "confidence": 0.5,
            "scale_hint_m_per_px": 0.05,
            "suggested_waypoints": [
                {"nx": 0.5, "ny": 0.82, "label": "WP1"},
                {"nx": 0.52, "ny": 0.58, "label": "WP2"},
                {"nx": 0.5, "ny": 0.34, "label": "WP3"},
            ],
            "obstacles": [],
            "zones": [],
            "fallback": True,
        }


def _pick_zone_center(z: dict[str, Any]) -> tuple[float, float]:
    x = _clamp01(z.get("x"))
    y = _clamp01(z.get("y"))
    w = _clamp01(z.get("w"))
    h = _clamp01(z.get("h"))
    return _clamp01(x + w * 0.5), _clamp01(y + h * 0.5)


def _build_zone_waypoints(zones: list[dict[str, Any]], mode: str, count: int, risk_filter: str) -> list[dict[str, Any]]:
    if count < 2:
        count = 2
    selected = [
        z for z in zones
        if risk_filter == "all" or str(z.get("risk") or "").lower() == risk_filter
    ]
    if not selected:
        selected = list(zones)
    if not selected:
        return []

    pts: list[tuple[float, float]] = []
    for z in selected:
        x = _clamp01(z.get("x"))
        y = _clamp01(z.get("y"))
        w = _clamp01(z.get("w"))
        h = _clamp01(z.get("h"))
        cx, cy = _pick_zone_center(z)
        if mode == "perimeter":
            pts.extend([
                (_clamp01(x + w * 0.15), _clamp01(y + h * 0.15)),
                (_clamp01(x + w * 0.85), _clamp01(y + h * 0.15)),
                (_clamp01(x + w * 0.85), _clamp01(y + h * 0.85)),
                (_clamp01(x + w * 0.15), _clamp01(y + h * 0.85)),
            ])
        elif mode == "zigzag":
            pts.extend([
                (_clamp01(x + w * 0.18), _clamp01(y + h * 0.20)),
                (_clamp01(x + w * 0.82), _clamp01(y + h * 0.40)),
                (_clamp01(x + w * 0.18), _clamp01(y + h * 0.60)),
                (_clamp01(x + w * 0.82), _clamp01(y + h * 0.80)),
            ])
        else:
            # transition: enlaza centros con entrada/salida de zona.
            pts.extend([
                (_clamp01(x + w * 0.20), _clamp01(y + h * 0.78)),
                (cx, cy),
                (_clamp01(x + w * 0.80), _clamp01(y + h * 0.28)),
            ])

    if not pts:
        return []
    if len(pts) > count:
        sampled: list[tuple[float, float]] = []
        for i in range(count):
            idx = int(round(i * (len(pts) - 1) / max(1, count - 1)))
            sampled.append(pts[idx])
        pts = sampled

    out = []
    for i, (nx, ny) in enumerate(pts):
        out.append({"nx": round(nx, 4), "ny": round(ny, 4), "label": f"ZWP{i + 1}"})
    return out


def _extract_space_sectors(raw: bytes) -> list[dict[str, Any]]:
    """Sectoriza la imagen en espacios transitables (componentes libres)."""
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        thr = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            4,
        )
        edges = cv2.Canny(blur, 60, 140)
        obs = cv2.bitwise_or(thr, edges)
        obs = cv2.morphologyEx(obs, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
        free = (obs == 0).astype(np.uint8)
        free = cv2.morphologyEx(free, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=8)
        if num_labels <= 1:
            return []

        dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
        sectors = []
        min_area = max(350, int(w * h * 0.01))
        for idx in range(1, num_labels):
            area = int(stats[idx, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            x = int(stats[idx, cv2.CC_STAT_LEFT])
            y = int(stats[idx, cv2.CC_STAT_TOP])
            ww = int(stats[idx, cv2.CC_STAT_WIDTH])
            hh = int(stats[idx, cv2.CC_STAT_HEIGHT])
            mask = (labels == idx)
            clear = float(np.mean(dist[mask])) if np.any(mask) else 0.0
            risk = "high" if clear < 1.1 else ("medium" if clear < 2.1 else "low")
            sectors.append({
                "name": f"Espacio {len(sectors) + 1}",
                "risk": risk,
                "x": round(x / max(1, w), 4),
                "y": round(y / max(1, h), 4),
                "w": round(ww / max(1, w), 4),
                "h": round(hh / max(1, h), 4),
                "free_score": round(clear, 3),
                "note": "Sector libre detectado por conectividad",
            })

        sectors.sort(key=lambda s: (s.get("w", 0) * s.get("h", 0)), reverse=True)
        return sectors[:10]
    except Exception:
        return []


def _normalize_space_kind(v: Any) -> str:
    x = str(v or "").strip().lower()
    aliases = {
        "habitacion": "habitacion",
        "dormitorio": "habitacion",
        "cuarto": "habitacion",
        "bano": "bano",
        "baño": "bano",
        "toilet": "bano",
        "sala": "sala",
        "living": "sala",
        "cocina": "cocina",
        "kitchen": "cocina",
        "comedor": "comedor",
        "pasillo": "pasillo",
        "hall": "pasillo",
        "estudio": "estudio",
        "oficina": "estudio",
        "lavanderia": "lavanderia",
        "balcon": "balcon",
    }
    return aliases.get(x, "otro")


@bp.route("/api/map-ai/analyze", methods=["POST"])
def api_map_ai_analyze():
    raw = b""
    content_type = "image/png"
    payload: dict[str, Any] = {}
    payload = {}

    image = request.files.get("map_image")
    if image:
        raw = image.read()
        content_type = image.content_type or "image/png"
    else:
        # Soporte alternativo por JSON para integraciones cliente-servidor.
        payload = request.get_json(silent=True) or {}
        b64 = str(payload.get("image_base64") or "").strip()
        ctype = str(payload.get("content_type") or "image/png").strip()
        if b64:
            try:
                raw = base64.b64decode(b64, validate=False)
                content_type = ctype
            except Exception:
                raw = b""

    if not raw:
        return jsonify({
            "status": "error",
            "message": "Falta imagen del mapa. Envia map_image (PNG/JPG/WEBP) o image_base64.",
        }), 400

    if len(raw) > 12 * 1024 * 1024:
        return jsonify({"status": "error", "message": "La imagen excede 12MB"}), 400

    if not content_type.startswith("image/"):
        return jsonify({
            "status": "error",
            "message": "Formato no soportado. Usa PNG, JPG/JPEG o WEBP.",
        }), 400

    zone_filter = (request.form.get("zone_filter") or payload.get("zone_filter") or "all").strip().lower()
    if zone_filter not in {"all", "low", "medium", "high"}:
        zone_filter = "all"
    route_mode = (request.form.get("zone_route_mode") or payload.get("zone_route_mode") or "transition").strip().lower()
    if route_mode not in {"transition", "perimeter", "zigzag"}:
        route_mode = "transition"
    try:
        zone_wp_count = int(request.form.get("zone_waypoint_count") or payload.get("zone_waypoint_count") or 6)
    except Exception:
        zone_wp_count = 6
    zone_wp_count = max(3, min(24, zone_wp_count))
    openai_override_key = (request.form.get("openai_api_key") or payload.get("openai_api_key") or request.headers.get("X-OpenAI-Key") or "").strip()

    model = (os.environ.get("MAP_AI_MODEL", "") or AGENT_MODEL or "gemini-2.5-flash").strip()
    if openai_override_key.startswith("sk-") and not is_openai_model(model):
        model = "gpt-4.1-mini"

    prompt = (
        "Analiza este mapa de navegacion para un robot cuadrupedo. "
        "Devuelve SOLO JSON valido con esta forma exacta: "
        "{\"analysis\": string, \"confidence\": number, "
        "\"scale_hint_m_per_px\": number, "
        "\"suggested_waypoints\": [{\"nx\": number, \"ny\": number, \"label\": string}], "
        "\"obstacles\": [{\"x\": number, \"y\": number, \"w\": number, \"h\": number, \"kind\": string}], "
        "\"zones\": [{\"name\": string, \"risk\": \"low\"|\"medium\"|\"high\", "
        "\"x\": number, \"y\": number, \"w\": number, \"h\": number, \"note\": string}], "
        "\"sectors\": [{\"name\": string, \"risk\": \"low\"|\"medium\"|\"high\", "
        "\"x\": number, \"y\": number, \"w\": number, \"h\": number, \"note\": string}], "
        "\"spaces\": [{\"name\": string, \"kind\": string, \"x\": number, \"y\": number, \"w\": number, \"h\": number, \"confidence\": number}], "
        "\"objects\": [{\"label\": string, \"x\": number, \"y\": number, \"w\": number, \"h\": number, \"confidence\": number, \"space_name\": string}], "
        "\"map_overview\": string, "
        "\"zone_waypoints\": [{\"nx\": number, \"ny\": number, \"label\": string}]}. "
        "Todos los campos normalizados deben estar entre 0 y 1. "
        "Incluye minimo 2 waypoints si detectas una trayectoria viable. "
        f"Enfoca las zonas por nivel: {zone_filter}. "
        f"Modo de recorrido de zona: {route_mode}. "
        f"Cantidad objetivo de waypoints de zona: {zone_wp_count}."
    )

    text, used_model, used_provider, err = _run_ai_with_failover(
        prompt=prompt,
        raw=raw,
        content_type=content_type,
        preferred_model=model,
        override_openai_key=openai_override_key,
    )
    if err:
        require_cloud = str(request.form.get("require_cloud") or (payload or {}).get("require_cloud") or "").strip().lower() in {"1", "true", "yes", "on"}
        allow_local = os.environ.get("MAP_AI_ALLOW_LOCAL_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"}
        if allow_local:
            local = _fallback_map_analysis(raw)
            sectors = _extract_space_sectors(raw)
            spaces = [
                {
                    "name": str(sec.get("name") or f"Espacio {i+1}"),
                    "kind": "otro",
                    "x": _clamp01(sec.get("x")),
                    "y": _clamp01(sec.get("y")),
                    "w": _clamp01(sec.get("w")),
                    "h": _clamp01(sec.get("h")),
                    "confidence": 0.62,
                }
                for i, sec in enumerate((sectors or local.get("zones") or [])[:12])
            ]
            short_err = str(err).split("|", 1)[0].strip()
            local_zone_wp = _build_zone_waypoints(
                sectors or local.get("zones") or [],
                mode=route_mode,
                count=zone_wp_count,
                risk_filter=zone_filter,
            )
            if not local_zone_wp:
                local_zone_wp = local.get("suggested_waypoints") or []
            return jsonify(
                {
                    "status": "ok",
                    "analysis": local.get("analysis") or "Analisis local activo.",
                    "map_overview": local.get("map_overview") or "Modo local.",
                    "confidence": float(local.get("confidence") or 0.5),
                    "scale_hint_m_per_px": float(local.get("scale_hint_m_per_px") or 0.05),
                    "suggested_waypoints": local.get("suggested_waypoints") or [],
                    "obstacles": local.get("obstacles") or [],
                    "zones": local.get("zones") or [],
                    "sectors": sectors,
                    "spaces": spaces,
                    "objects": [],
                    "model": used_model or model,
                    "provider": used_provider,
                    "fallback": True,
                    "warning": "No habia credenciales IA validas para nube. Se uso analisis local.",
                    "provider_error": err,
                    "provider_error_short": short_err,
                    "zone_waypoints": local_zone_wp,
                }
            )
        if not require_cloud:
            # Seguridad adicional: ante configuraciones anómalas, nunca bloquear
            # al operador. Devolvemos ruta base local en modo degradado.
            local = _fallback_map_analysis(raw)
            sectors = _extract_space_sectors(raw)
            spaces = [
                {
                    "name": str(sec.get("name") or f"Espacio {i+1}"),
                    "kind": "otro",
                    "x": _clamp01(sec.get("x")),
                    "y": _clamp01(sec.get("y")),
                    "w": _clamp01(sec.get("w")),
                    "h": _clamp01(sec.get("h")),
                    "confidence": 0.62,
                }
                for i, sec in enumerate((sectors or local.get("zones") or [])[:12])
            ]
            local_zone_wp = _build_zone_waypoints(
                sectors or local.get("zones") or [],
                mode=route_mode,
                count=zone_wp_count,
                risk_filter=zone_filter,
            )
            if not local_zone_wp:
                local_zone_wp = local.get("suggested_waypoints") or []
            return jsonify(
                {
                    "status": "ok",
                    "analysis": local.get("analysis") or "Analisis local activo.",
                    "map_overview": local.get("map_overview") or "Modo local.",
                    "confidence": float(local.get("confidence") or 0.5),
                    "scale_hint_m_per_px": float(local.get("scale_hint_m_per_px") or 0.05),
                    "suggested_waypoints": local.get("suggested_waypoints") or [],
                    "obstacles": local.get("obstacles") or [],
                    "zones": local.get("zones") or [],
                    "sectors": sectors,
                    "spaces": spaces,
                    "objects": [],
                    "model": used_model or model,
                    "provider": used_provider,
                    "fallback": True,
                    "warning": "Se aplico modo degradado local para garantizar continuidad.",
                    "provider_error": err,
                    "provider_error_short": str(err).split("|", 1)[0].strip(),
                    "zone_waypoints": local_zone_wp,
                }
            )
        return jsonify(
            {
                "status": "error",
                "message": "No hay IA en nube disponible. Configura OPENAI_API_KEY o GEMINI_API_KEY.",
                "detail": err,
            }
        ), 400

    parsed = _extract_json_object(text)
    waypoints_raw = parsed.get("suggested_waypoints") if isinstance(parsed, dict) else []
    obstacles_raw = parsed.get("obstacles") if isinstance(parsed, dict) else []
    zones_raw = parsed.get("zones") if isinstance(parsed, dict) else []
    sectors_raw = parsed.get("sectors") if isinstance(parsed, dict) else []
    spaces_raw = parsed.get("spaces") if isinstance(parsed, dict) else []
    objects_raw = parsed.get("objects") if isinstance(parsed, dict) else []
    zone_waypoints_raw = parsed.get("zone_waypoints") if isinstance(parsed, dict) else []

    waypoints = []
    if isinstance(waypoints_raw, list):
        for idx, p in enumerate(waypoints_raw):
            if not isinstance(p, dict):
                continue
            waypoints.append(
                {
                    "nx": _clamp01(p.get("nx")),
                    "ny": _clamp01(p.get("ny")),
                    "label": str(p.get("label") or f"WP{idx + 1}"),
                }
            )

    obstacles = []
    if isinstance(obstacles_raw, list):
        for o in obstacles_raw[:40]:
            if not isinstance(o, dict):
                continue
            obstacles.append(
                {
                    "x": _clamp01(o.get("x")),
                    "y": _clamp01(o.get("y")),
                    "w": _clamp01(o.get("w")),
                    "h": _clamp01(o.get("h")),
                    "kind": str(o.get("kind") or "obstacle"),
                }
            )

    zones = []
    if isinstance(zones_raw, list):
        for z in zones_raw[:24]:
            if not isinstance(z, dict):
                continue
            risk = str(z.get("risk") or "medium").lower()
            if risk not in {"low", "medium", "high"}:
                risk = "medium"
            zones.append(
                {
                    "name": str(z.get("name") or "Zona"),
                    "risk": risk,
                    "x": _clamp01(z.get("x")),
                    "y": _clamp01(z.get("y")),
                    "w": _clamp01(z.get("w")),
                    "h": _clamp01(z.get("h")),
                    "note": str(z.get("note") or ""),
                }
            )

    sectors = []
    if isinstance(sectors_raw, list):
        for z in sectors_raw[:16]:
            if not isinstance(z, dict):
                continue
            risk = str(z.get("risk") or "medium").lower()
            if risk not in {"low", "medium", "high"}:
                risk = "medium"
            sectors.append(
                {
                    "name": str(z.get("name") or "Espacio"),
                    "risk": risk,
                    "x": _clamp01(z.get("x")),
                    "y": _clamp01(z.get("y")),
                    "w": _clamp01(z.get("w")),
                    "h": _clamp01(z.get("h")),
                    "note": str(z.get("note") or ""),
                }
            )

    # Refuerzo local: si la IA no trae sectores, los derivamos de la imagen.
    if not sectors:
        sectors = _extract_space_sectors(raw)
    if not zones:
        zones = sectors[:]

    spaces = []
    if isinstance(spaces_raw, list):
        for s in spaces_raw[:30]:
            if not isinstance(s, dict):
                continue
            spaces.append(
                {
                    "name": str(s.get("name") or "Espacio"),
                    "kind": _normalize_space_kind(s.get("kind")),
                    "x": _clamp01(s.get("x")),
                    "y": _clamp01(s.get("y")),
                    "w": _clamp01(s.get("w")),
                    "h": _clamp01(s.get("h")),
                    "confidence": _clamp01(s.get("confidence") if s.get("confidence") is not None else 0.7),
                }
            )

    if not spaces and sectors:
        spaces = [
            {
                "name": str(sec.get("name") or f"Espacio {i+1}"),
                "kind": "otro",
                "x": _clamp01(sec.get("x")),
                "y": _clamp01(sec.get("y")),
                "w": _clamp01(sec.get("w")),
                "h": _clamp01(sec.get("h")),
                "confidence": 0.62,
            }
            for i, sec in enumerate(sectors[:12])
        ]

    objects = []
    if isinstance(objects_raw, list):
        for o in objects_raw[:80]:
            if not isinstance(o, dict):
                continue
            objects.append(
                {
                    "label": str(o.get("label") or "objeto"),
                    "x": _clamp01(o.get("x")),
                    "y": _clamp01(o.get("y")),
                    "w": _clamp01(o.get("w")),
                    "h": _clamp01(o.get("h")),
                    "confidence": _clamp01(o.get("confidence") if o.get("confidence") is not None else 0.6),
                    "space_name": str(o.get("space_name") or ""),
                }
            )

    zone_waypoints = []
    if isinstance(zone_waypoints_raw, list):
        for idx, p in enumerate(zone_waypoints_raw[:zone_wp_count]):
            if not isinstance(p, dict):
                continue
            zone_waypoints.append(
                {
                    "nx": _clamp01(p.get("nx")),
                    "ny": _clamp01(p.get("ny")),
                    "label": str(p.get("label") or f"ZWP{idx + 1}"),
                }
            )
    if not zone_waypoints:
        zone_waypoints = _build_zone_waypoints(
            sectors or zones,
            mode=route_mode,
            count=zone_wp_count,
            risk_filter=zone_filter,
        )

    analysis = str(parsed.get("analysis") or "Mapa procesado por IA.") if isinstance(parsed, dict) else "Mapa procesado por IA."
    confidence = parsed.get("confidence") if isinstance(parsed, dict) else 0.0
    scale_hint = parsed.get("scale_hint_m_per_px") if isinstance(parsed, dict) else 0.05

    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.0

    try:
        scale_hint = float(scale_hint)
        if scale_hint <= 0:
            scale_hint = 0.05
    except Exception:
        scale_hint = 0.05

    return jsonify(
        {
            "status": "ok",
            "analysis": analysis,
            "map_overview": str(parsed.get("map_overview") or "") if isinstance(parsed, dict) else "",
            "confidence": confidence,
            "scale_hint_m_per_px": scale_hint,
            "suggested_waypoints": waypoints,
            "obstacles": obstacles,
            "zones": zones,
            "sectors": sectors,
            "spaces": spaces,
            "objects": objects,
            "zone_waypoints": zone_waypoints,
            "model": used_model or model,
            "provider": used_provider,
        }
    )
