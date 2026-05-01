"""Auto-Ruta: seguidor de waypoints en el frame del lidar.

Recibe una lista de puntos [{x,y}] + numero de ciclos. Por cada ciclo:
recorre los waypoints A→B→...→FIN y luego SIEMPRE vuelve por reversa al
origen (regla del laboratorio para no cortar por zonas sin validar).
"""

from __future__ import annotations

import asyncio
import math

from .logging_utils import emit_log
from .primitives import robot_send_command
from .runtime import socketio
from .state import autoroute_state, proximity_sensor


def _normalize_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


async def _wait_for_pose(timeout_s: float = 5.0) -> bool:
    """Espera a que el lidar reporte pose valida."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not proximity_sensor["_pose_valid"]:
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.15)
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
        for cycle in range(1, state["cycles_total"] + 1):
            if state["_cancel"]:
                break
            state["cycle_now"] = cycle

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
