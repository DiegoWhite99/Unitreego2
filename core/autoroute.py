"""Auto-Ruta: seguidor de waypoints en el frame del lidar.

Recibe una lista de puntos [{x,y}] + numero de ciclos. Por cada ciclo:
recorre los waypoints A→B→...→FIN y luego SIEMPRE vuelve por reversa al
origen (regla del laboratorio para no cortar por zonas sin validar).
"""

from __future__ import annotations

import asyncio
import json
import math
import time

from .logging_utils import emit_log
from .primitives import robot_send_command
from .runtime import socketio
from .state import autoroute_state, proximity_sensor
from .agents.config import GEMINI_MODEL, GENAI_AVAILABLE, is_openai_model, openai_client
from yolo_detector import detector as yolo_detector


def _normalize_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _closest_point_on_segment(px: float, py: float,
                              ax: float, ay: float,
                              bx: float, by: float) -> tuple[float, float, float, float, float, float]:
    vx = bx - ax
    vy = by - ay
    seg_len = math.hypot(vx, vy)
    if seg_len < 1e-6:
        dx = px - ax
        dy = py - ay
        return ax, ay, 0.0, seg_len, math.hypot(dx, dy), 0.0
    ux = vx / seg_len
    uy = vy / seg_len
    apx = px - ax
    apy = py - ay
    s = apx * ux + apy * uy
    t = _clamp(s / seg_len, 0.0, 1.0)
    qx = ax + vx * t
    qy = ay + vy * t
    # Distancia lateral con signo (cross-track error).
    side = (vx * (py - ay) - vy * (px - ax)) / max(seg_len, 1e-6)
    return qx, qy, t, seg_len, abs(side), side


def _extract_json(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        i0 = text.find("{")
        i1 = text.rfind("}")
        if i0 >= 0 and i1 > i0:
            text = text[i0:i1 + 1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        i0 = text.find("{")
        i1 = text.rfind("}")
        if i0 >= 0 and i1 > i0:
            try:
                obj = json.loads(text[i0:i1 + 1])
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
    return {}


def _ai_path_adjustment(payload: dict) -> dict:
    """Asistente IA online para corregir seguimiento lateral.

    Devuelve factores acotados para no comprometer seguridad.
    """
    try:
        model = GEMINI_MODEL
        prompt = (
            "Eres un controlador de navegación para robot cuadrúpedo. "
            "Responde SOLO JSON con: {\"z_gain\":number,\"speed_scale\":number,\"lookahead_scale\":number}. "
            "Reglas: z_gain entre 0.7 y 1.8, speed_scale entre 0.25 y 1.0, "
            "lookahead_scale entre 0.55 y 1.25. "
            "Si hay mucho error lateral, sube z_gain y baja speed_scale.\n"
            f"Estado: {json.dumps(payload, ensure_ascii=True)}"
        )

        if is_openai_model(model) and openai_client is not None:
            resp = openai_client.chat.completions.create(
                model=model,
                temperature=0.1,
                max_tokens=80,
                messages=[
                    {"role": "system", "content": "Control experto de tracking de trayectoria. JSON puro."},
                    {"role": "user", "content": prompt},
                ],
            )
            txt = ""
            try:
                txt = resp.choices[0].message.content or ""
            except Exception:
                txt = ""
            obj = _extract_json(txt)
            if obj:
                return obj

        if GENAI_AVAILABLE:
            import google.generativeai as genai

            mdl = genai.GenerativeModel(model)
            out = mdl.generate_content(prompt)
            txt = ""
            try:
                txt = getattr(out, "text", "") or ""
            except Exception:
                txt = ""
            obj = _extract_json(txt)
            if obj:
                return obj
    except Exception:
        return {}
    return {}


async def _wait_for_pose(timeout_s: float = 5.0) -> bool:
    """Espera a que el lidar reporte pose valida."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not proximity_sensor["_pose_valid"]:
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.15)
    return True


async def _person_guard(person_state: dict) -> bool:
    """Retorna True cuando hay que pausar el avance por persona detectada."""
    state = autoroute_state
    if not state.get("pause_on_person", True) or not yolo_detector.is_running():
        state["person_pause_active"] = False
        return False

    blocked = False
    try:
        dets = yolo_detector.get_detections(compact=True, limit=24)
        min_conf = float(state.get("person_min_conf", 0.45) or 0.45)
        for d in dets:
            label = str(d.get("label") or "").strip().lower()
            conf = float(d.get("confidence") or 0.0)
            if label in {"persona", "person"} and conf >= min_conf:
                blocked = True
                break
    except Exception:
        blocked = False

    if blocked:
        person_state["hits"] += 1
        person_state["clear"] = 0
    else:
        person_state["clear"] += 1
        person_state["clear"] = min(1000, person_state["clear"])

    hits_thr = int(state.get("person_pause_hits", 3) or 3)
    clear_thr = int(state.get("person_resume_clear", 5) or 5)

    if person_state["hits"] >= hits_thr:
        if not person_state["paused"]:
            emit_log("warning", "Auto-Ruta: persona detectada, pausando avance")
        person_state["paused"] = True
        state["person_pause_active"] = True
        try:
            await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        except Exception:
            pass
        await asyncio.sleep(0.2)
        return True

    if person_state["paused"] and person_state["clear"] >= clear_thr:
        person_state["paused"] = False
        person_state["hits"] = 0
        state["person_pause_active"] = False
        emit_log("info", "Auto-Ruta: via despejada, retomando ruta")
    return False


async def _follow_segment(a: dict, b: dict,
                          cycle: int, seg_idx: int, total_segments: int,
                          returning: bool = False) -> bool:
    """Seguidor estricto de segmento A->B con correccion de desvio lateral.

    Usa look-ahead sobre la linea + control de cross-track para evitar
    recortes grandes entre waypoints.
    """
    state = autoroute_state
    smooth = bool(state.get("smooth_mode", False))
    lin_max = state["smooth_linear_speed"] if smooth else state["linear_speed"]
    head_thr = state["smooth_heading_align_rad"] if smooth else state["heading_align_rad"]
    reach = state["smooth_reach_radius_m"] if smooth else state["reach_radius_m"]
    lookahead = float(state.get("lookahead_m", 0.55) or 0.55)
    corridor = float(state.get("corridor_half_width_m", 0.60) or 0.60)
    cte_hard = float(state.get("cte_hard_threshold_m", 1.20) or 1.20)
    ai_on = bool(state.get("ai_path_assist", True))
    ai_interval = max(0.8, float(state.get("ai_assist_interval_s", 1.25) or 1.25))
    ai_trigger = max(0.10, float(state.get("ai_cte_trigger_m", 0.22) or 0.22))
    ai_last_ts = 0.0
    ai_cached = {"z_gain": 1.0, "speed_scale": 1.0, "lookahead_scale": 1.0}

    ax = float(a.get("x", 0.0))
    ay = float(a.get("y", 0.0))
    bx = float(b.get("x", 0.0))
    by = float(b.get("y", 0.0))
    seg_len = math.hypot(bx - ax, by - ay)
    if seg_len < 1e-4:
        return True

    timeout_s = max(float(state.get("timeout_per_wp_s", 20.0) or 20.0), 6.0 + seg_len * 7.0)
    start_ts = asyncio.get_running_loop().time()
    person_state = {"hits": 0, "clear": 0, "paused": False}

    emit_log(
        "info",
        f"  -> segmento {seg_idx}/{total_segments} "
        f"({ax:.2f},{ay:.2f}) -> ({bx:.2f},{by:.2f}), {seg_len:.2f} m"
        f"{' [retorno]' if returning else ''}",
    )

    while not state["_cancel"]:
        if (asyncio.get_running_loop().time() - start_ts) > timeout_s:
            emit_log("warning", f"Segmento {seg_idx} timeout, forzando siguiente")
            return False

        if not proximity_sensor["_pose_valid"]:
            await asyncio.sleep(0.12)
            continue

        if await _person_guard(person_state):
            continue

        px = proximity_sensor["_pose_x"]
        py = proximity_sensor["_pose_y"]
        yaw = proximity_sensor["_pose_yaw"]

        qx, qy, t, _, cte, side = _closest_point_on_segment(px, py, ax, ay, bx, by)
        dist_end = math.hypot(bx - px, by - py)

        # Objetivo virtual sobre la linea (look-ahead). Si el desvio es alto,
        # forzamos a volver primero al corredor.
        if cte > max(corridor * 0.9, cte_hard):
            tx, ty = qx, qy
        else:
            s_look = _clamp(t * seg_len + lookahead * ai_cached["lookahead_scale"], 0.0, seg_len)
            u = s_look / max(seg_len, 1e-6)
            tx = ax + (bx - ax) * u
            ty = ay + (by - ay) * u

        target_heading = math.atan2(ty - py, tx - px)
        heading_err = _normalize_angle(target_heading - yaw)

        # Ajuste IA online (cada ~1.2 s y solo cuando hay desvio relevante).
        now = time.time()
        if ai_on and cte >= ai_trigger and (now - ai_last_ts) >= ai_interval:
            ai_payload = {
                "segment_len_m": round(seg_len, 3),
                "progress": round(t, 3),
                "cross_track_m": round(cte, 3),
                "heading_error_rad": round(float(heading_err), 3),
                "distance_to_end_m": round(dist_end, 3),
                "corridor_half_width_m": round(corridor, 3),
                "returning": bool(returning),
                "smooth_mode": bool(smooth),
            }
            adj = _ai_path_adjustment(ai_payload)
            try:
                zg = float(adj.get("z_gain", 1.0))
                ss = float(adj.get("speed_scale", 1.0))
                ls = float(adj.get("lookahead_scale", 1.0))
                ai_cached = {
                    "z_gain": _clamp(zg, 0.7, 1.8),
                    "speed_scale": _clamp(ss, 0.25, 1.0),
                    "lookahead_scale": _clamp(ls, 0.55, 1.25),
                }
                ai_last_ts = now
            except Exception:
                pass

        k_head = (1.7 if smooth else 1.55) * ai_cached["z_gain"]
        k_cte = (1.10 if smooth else 1.30) * ai_cached["z_gain"]
        z = k_head * heading_err - k_cte * _clamp(side / max(corridor, 0.2), -1.0, 1.0)
        z = _clamp(z, -state["angular_speed"], state["angular_speed"])

        # Baja velocidad cuando se sale del corredor o hay error angular.
        cte_pen = _clamp(1.0 - cte / max(corridor, 0.25), 0.12, 1.0)
        head_pen = _clamp(1.0 - abs(heading_err) / 1.2, 0.15, 1.0)
        x = lin_max * cte_pen * head_pen * ai_cached["speed_scale"]

        if abs(heading_err) > max(1.05, head_thr * 1.5):
            x = 0.0
        elif dist_end < 0.8:
            x = min(x, max(0.10, dist_end * 0.9))

        if proximity_sensor["enabled"] and proximity_sensor["_alert_active"]:
            try:
                await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
            except Exception:
                pass
            emit_log("warning", "Auto-Ruta: sensor bloqueó el avance, pausando segmento")
            await asyncio.sleep(0.18)
            continue

        try:
            await robot_send_command("Move", {"x": max(0.0, x), "y": 0.0, "z": z})
        except Exception as exc:
            emit_log("error", f"Auto-Ruta move(segmento): {exc}")
            return False

        socketio.emit("autoroute_tracking", {
            "cycle": cycle,
            "segment": seg_idx,
            "segment_total": total_segments,
            "returning": returning,
            "cross_track_m": round(cte, 3),
            "dist_end_m": round(dist_end, 3),
            "corridor_m": round(corridor, 3),
        })

        # Requisito de llegada: cerca del final + segmento avanzado.
        if dist_end <= max(0.12, reach * 0.92) and t >= 0.90:
            break

        await asyncio.sleep(0.14)

    try:
        await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
    except Exception:
        pass
    state["person_pause_active"] = False
    return True


async def _go_to(wp: dict) -> None:
    """Conduce hasta entrar en el radio de alcance o agotar el timeout.
    En `smooth_mode` no frena entre waypoints (transicion fluida)."""
    state = autoroute_state
    smooth = state.get("smooth_mode", False)
    start_ts = asyncio.get_running_loop().time()

    lin_max  = state["smooth_linear_speed"]      if smooth else state["linear_speed"]
    reach    = state["smooth_reach_radius_m"]    if smooth else state["reach_radius_m"]
    head_thr = state["smooth_heading_align_rad"] if smooth else state["heading_align_rad"]
    person_hits = 0
    person_clear = 0
    person_paused = False

    if proximity_sensor["_pose_valid"]:
        p0x = proximity_sensor["_pose_x"]
        p0y = proximity_sensor["_pose_y"]
        d0 = math.hypot(float(wp.get("x", 0)) - p0x, float(wp.get("y", 0)) - p0y)
        emit_log(
            "info",
            f"  -> waypoint ({wp.get('x', 0):.2f}, {wp.get('y', 0):.2f}) "
            f"desde ({p0x:.2f}, {p0y:.2f}), distancia {d0:.2f} m"
            f"{' [fluido]' if smooth else ''}",
        )

    while not state["_cancel"]:
        if (asyncio.get_running_loop().time() - start_ts) > state["timeout_per_wp_s"]:
            emit_log(
                "warning",
                f"Waypoint ({wp.get('x'):.2f},{wp.get('y'):.2f}) timeout, siguiente",
            )
            break

        if not proximity_sensor["_pose_valid"]:
            await asyncio.sleep(0.15)
            continue

        # Seguridad IA: si YOLO ve persona, pausar hasta que despeje.
        if state.get("pause_on_person", True) and yolo_detector.is_running():
            blocked = False
            try:
                dets = yolo_detector.get_detections(compact=True, limit=24)
                min_conf = float(state.get("person_min_conf", 0.45) or 0.45)
                for d in dets:
                    label = str(d.get("label") or "").strip().lower()
                    conf = float(d.get("confidence") or 0.0)
                    if label in {"persona", "person"} and conf >= min_conf:
                        blocked = True
                        break
            except Exception:
                blocked = False

            if blocked:
                person_hits += 1
                person_clear = 0
            else:
                person_clear += 1
                if person_clear > 1000:
                    person_clear = 1000

            hits_thr = int(state.get("person_pause_hits", 3) or 3)
            clear_thr = int(state.get("person_resume_clear", 5) or 5)

            if person_hits >= hits_thr:
                if not person_paused:
                    emit_log("warning", "Auto-Ruta: persona detectada, pausando avance")
                person_paused = True
                state["person_pause_active"] = True
                try:
                    await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                continue

            if person_paused and person_clear >= clear_thr:
                person_paused = False
                person_hits = 0
                state["person_pause_active"] = False
                emit_log("info", "Auto-Ruta: via despejada, retomando ruta")

        px = proximity_sensor["_pose_x"]
        py = proximity_sensor["_pose_y"]
        yaw = proximity_sensor["_pose_yaw"]

        dx = float(wp.get("x", 0.0)) - px
        dy = float(wp.get("y", 0.0)) - py
        dist = math.hypot(dx, dy)
        if dist < reach:
            break

        target_heading = math.atan2(dy, dx)
        heading_err = _normalize_angle(target_heading - yaw)

        if abs(heading_err) > head_thr:
            z = max(-state["angular_speed"],
                    min(state["angular_speed"], heading_err * 1.5))
            x = 0.0
        else:
            if smooth:
                gain_by_heading = max(
                    0.35, 1.0 - abs(heading_err) / head_thr * 0.65
                )
                x = min(lin_max, dist * 1.0) * gain_by_heading
                z = max(-0.6, min(0.6, heading_err * 1.5))
            else:
                x = max(0.0, min(lin_max, dist * 0.8))
                z = max(-0.4, min(0.4, heading_err * 1.2))

        if proximity_sensor["enabled"] and proximity_sensor["_alert_active"]:
            try:
                await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
            except Exception:
                pass
            emit_log("warning", "Auto-Ruta: sensor bloqueó el avance, saltando waypoint")
            break

        try:
            await robot_send_command("Move", {"x": x, "y": 0.0, "z": z})
        except Exception as exc:
            emit_log("error", f"Auto-Ruta move: {exc}")
            break

        await asyncio.sleep(0.2)

    if not smooth:
        try:
            await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        except Exception:
            pass
    state["person_pause_active"] = False


async def autoroute_follow_loop() -> None:
    state = autoroute_state
    try:
        emit_log("info", "Auto-Ruta: pidiendo BalanceStand…")
        try:
            await robot_send_command("BalanceStand")
        except Exception as exc:
            emit_log("warning", f"Auto-Ruta: BalanceStand fallo: {exc}")

        if not await _wait_for_pose(5.0):
            emit_log(
                "error",
                "Auto-Ruta: el lidar no reporto pose en 5 s. "
                "Activa el sensor en el Control Remoto y verifica "
                "que el robot publique utlidar/robot_pose.",
            )
            state["_cancel"] = True
            return

        if state.get("translate_to_pose"):
            pose_x = proximity_sensor["_pose_x"]
            pose_y = proximity_sensor["_pose_y"]
            pose_yaw = proximity_sensor["_pose_yaw"]
            waypoints = state["waypoints"]
            if len(waypoints) >= 2:
                # Origen guardado y heading guardado (wp0 -> wp1).
                wp0x = float(waypoints[0]["x"])
                wp0y = float(waypoints[0]["y"])
                wp1x = float(waypoints[1]["x"])
                wp1y = float(waypoints[1]["y"])
                saved_heading = math.atan2(wp1y - wp0y, wp1x - wp0x)
                # Rotacion a aplicar: lo que el robot tendria que rotar para
                # encarar wp[1] desde su heading actual.
                delta_yaw = _normalize_angle(pose_yaw - saved_heading)
                cos_d = math.cos(delta_yaw)
                sin_d = math.sin(delta_yaw)
                rotated = []
                for w in waypoints:
                    dx = float(w["x"]) - wp0x
                    dy = float(w["y"]) - wp0y
                    nx = pose_x + dx * cos_d - dy * sin_d
                    ny = pose_y + dx * sin_d + dy * cos_d
                    rotated.append({"x": nx, "y": ny})
                state["waypoints"] = rotated
                emit_log(
                    "info",
                    f"Auto-Ruta: ruta anclada a la pose actual "
                    f"(origen {pose_x:+.2f},{pose_y:+.2f}; "
                    f"rotacion {math.degrees(delta_yaw):+.1f}°).",
                )
            elif waypoints:
                ox = float(waypoints[0]["x"]) - pose_x
                oy = float(waypoints[0]["y"]) - pose_y
                state["waypoints"] = [
                    {"x": float(w["x"]) - ox, "y": float(w["y"]) - oy}
                    for w in waypoints
                ]
                emit_log(
                    "info",
                    f"Auto-Ruta: ruta trasladada al origen del robot "
                    f"(offset {ox:+.2f}, {oy:+.2f}).",
                )
        else:
            emit_log(
                "info",
                f"Auto-Ruta: siguiendo {len(state['waypoints'])} waypoints "
                f"en frame absoluto del lidar (sin traslado).",
            )

        total_wp = len(state["waypoints"])
        strict_path = bool(state.get("strict_path_mode", True))
        for cycle in range(1, state["cycles_total"] + 1):
            if state["_cancel"]:
                break
            state["cycle_now"] = cycle

            if strict_path and total_wp >= 2:
                total_segments = total_wp - 1
                for i in range(1, total_wp):
                    if state["_cancel"]:
                        break
                    state["wp_now"] = i + 1
                    socketio.emit("autoroute_progress", {
                        "running":         True,
                        "cycle":           cycle,
                        "cycle_total":     state["cycles_total"],
                        "waypoint":        i + 1,
                        "waypoint_total":  total_wp,
                        "returning":       False,
                    })
                    reached = await _follow_segment(
                        state["waypoints"][i - 1],
                        state["waypoints"][i],
                        cycle=cycle,
                        seg_idx=i,
                        total_segments=total_segments,
                        returning=False,
                    )
                    if not reached and not state["_cancel"]:
                        # Fallback puntual para no trabar misión completa.
                        await _go_to(state["waypoints"][i])
            else:
                for i, wp in enumerate(state["waypoints"]):
                    if state["_cancel"]:
                        break
                    state["wp_now"] = i + 1
                    socketio.emit("autoroute_progress", {
                        "running":         True,
                        "cycle":           cycle,
                        "cycle_total":     state["cycles_total"],
                        "waypoint":        i + 1,
                        "waypoint_total":  total_wp,
                        "returning":       False,
                    })
                    await _go_to(wp)

            # REGLA: al final de cada ciclo, regresar SIEMPRE por el mismo
            # camino en reversa hasta wp[0].
            if not state["_cancel"] and total_wp >= 2:
                is_last_cycle = cycle >= state["cycles_total"]
                emit_log(
                    "info",
                    f"Auto-Ruta: fin del ciclo {cycle}. "
                    f"Volviendo al origen por el mismo camino...",
                )
                if strict_path:
                    total_segments = total_wp - 1
                    for i in range(total_wp - 1, 0, -1):
                        if state["_cancel"]:
                            break
                        state["wp_now"] = i
                        socketio.emit("autoroute_progress", {
                            "running":         True,
                            "cycle":           cycle,
                            "cycle_total":     state["cycles_total"],
                            "waypoint":        i,
                            "waypoint_total":  total_wp,
                            "returning":       True,
                        })
                        reached = await _follow_segment(
                            state["waypoints"][i],
                            state["waypoints"][i - 1],
                            cycle=cycle,
                            seg_idx=(total_segments - i + 1),
                            total_segments=total_segments,
                            returning=True,
                        )
                        if not reached and not state["_cancel"]:
                            await _go_to(state["waypoints"][i - 1])
                else:
                    for i in range(total_wp - 2, -1, -1):
                        if state["_cancel"]:
                            break
                        wp = state["waypoints"][i]
                        state["wp_now"] = i + 1
                        socketio.emit("autoroute_progress", {
                            "running":         True,
                            "cycle":           cycle,
                            "cycle_total":     state["cycles_total"],
                            "waypoint":        i + 1,
                            "waypoint_total":  total_wp,
                            "returning":       True,
                        })
                        await _go_to(wp)
                if is_last_cycle:
                    emit_log("success",
                             "Auto-Ruta: origen alcanzado. Recorrido completo.")
                else:
                    emit_log(
                        "success",
                        f"Auto-Ruta: origen alcanzado. "
                        f"Arrancando ciclo {cycle + 1}/{state['cycles_total']}.",
                    )

        try:
            await robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
        except Exception:
            pass
        emit_log("success", "Auto-Ruta: recorrido completo.")
    except Exception as exc:
        emit_log("error", f"Auto-Ruta: error en el loop: {exc}")
    finally:
        state["running"] = False
        state["_task"] = None
        socketio.emit("autoroute_done", {})
