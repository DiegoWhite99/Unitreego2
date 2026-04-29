"""Sensor de proximidad basado en LiDAR L1 + ROBOTODOM.

Flujo:
  ON  -> activamos lidar (`ULIDAR_SWITCH`), nos suscribimos a:
           - `rt/utlidar/robot_pose`   -> pose en frame del mapa
           - `rt/utlidar/voxel_map_compressed` -> nube de puntos
         El callback transforma puntos a frame del robot, filtra cono
         frontal y si la distancia < `stop_distance_m` emite alerta y
         frena el robot (Move=0).
  OFF -> unsubscribe + `ULIDAR_SWITCH` OFF.

Tambien empuja una muestra de puntos al frontend a ~5 Hz para el
heatmap 3D (`lidar_points` event).
"""

from __future__ import annotations

import math
import time

from ..logging_utils import emit_log
from ..primitives import robot_send_command
from ..runtime import (
    get_connection,
    get_pub_sub,
    run_async_no_wait,
    socketio,
)
from ..state import proximity_sensor, robot_state


# ────────────────────────────────────────────────────────────────────
# Helpers internos
# ────────────────────────────────────────────────────────────────────
def _robot_is_moving_forward() -> bool:
    """True solo si el ultimo Move es hacia adelante y reciente."""
    now = time.time()
    age = now - proximity_sensor["_last_cmd_ts"]
    if age > proximity_sensor["cmd_fresh_s"]:
        return False
    return proximity_sensor["_last_cmd_x"] >= proximity_sensor["min_forward_vel_mps"]


def _trigger_proximity_alert(distance_m: float, direction: str, source: str) -> None:
    """Emite UNA alerta al entrar en zona peligrosa y frena el robot.

    Si la ventana FORCE esta abierta (operador sostiene Shift / doble
    tap), descartamos: sin emit, sin Move=0, sin flip de _alert_active."""
    if time.time() < proximity_sensor.get("_force_until", 0.0):
        return

    if proximity_sensor["_alert_active"]:
        return

    proximity_sensor["_alert_active"] = True
    proximity_sensor["_last_alert_ts"] = time.time()
    proximity_sensor["_last_source"] = source

    socketio.emit("proximity_alert", {
        "distance_m": round(float(distance_m), 2),
        "direction":  direction,
        "source":     source,
    })

    if robot_state["connected"] and get_pub_sub():
        try:
            run_async_no_wait(
                robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0})
            )
        except Exception:
            pass


def _maybe_clear_alert_state(distance_m: float) -> None:
    """Reset del flag de alerta cuando la zona esta clara > 0.8 s.
    Asi el usuario puede re-intentar avanzar y recibir otra alerta si toca."""
    now = time.time()
    clear_thr = proximity_sensor["clear_distance_m"]
    if distance_m >= clear_thr:
        if proximity_sensor["_clear_since"] == 0.0:
            proximity_sensor["_clear_since"] = now
        elif now - proximity_sensor["_clear_since"] >= 0.8:
            proximity_sensor["_alert_active"] = False
    else:
        proximity_sensor["_clear_since"] = 0.0


def _maybe_emit_lidar_points(pts, rx: float, ry: float, yaw: float) -> None:
    """Publica una muestra de puntos al frontend a ~5 Hz."""
    now = time.time()
    if now - proximity_sensor["_last_points_emit_ts"] < 0.2:
        return
    proximity_sensor["_last_points_emit_ts"] = now
    try:
        import numpy as _np
        n = pts.shape[0]
        if n == 0:
            return
        zmask = (
            (pts[:, 2] > proximity_sensor["min_z_m"])
            & (pts[:, 2] < proximity_sensor["max_z_m"] + 0.4)
        )
        w_pts = pts[zmask]
        if w_pts.shape[0] > 2000:
            idx = _np.random.choice(w_pts.shape[0], 2000, replace=False)
            w_pts = w_pts[idx]

        xyz = w_pts[:, :3].astype(float)
        socketio.emit("lidar_points", {
            "pose":  {"x": rx, "y": ry, "yaw": yaw},
            "xyz":   xyz.round(3).flatten().tolist(),
            "xy":    xyz[:, :2].round(3).flatten().tolist(),
            "count": int(xyz.shape[0]),
        })
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────
# Callbacks Socket pub/sub
# ────────────────────────────────────────────────────────────────────
def _on_robot_pose_message(message) -> None:
    try:
        data = (message or {}).get("data") or {}
        pose = data.get("pose") or data
        position = pose.get("position") if isinstance(pose, dict) else None
        orientation = pose.get("orientation") if isinstance(pose, dict) else None
        if not position:
            return

        proximity_sensor["_pose_x"] = float(position.get("x", 0.0))
        proximity_sensor["_pose_y"] = float(position.get("y", 0.0))
        proximity_sensor["_pose_z"] = float(position.get("z", 0.0))

        if orientation:
            qx = float(orientation.get("x", 0.0))
            qy = float(orientation.get("y", 0.0))
            qz = float(orientation.get("z", 0.0))
            qw = float(orientation.get("w", 1.0))
            siny = 2.0 * (qw * qz + qx * qy)
            cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
            proximity_sensor["_pose_yaw"] = math.atan2(siny, cosy)

        proximity_sensor["_pose_valid"] = True
    except Exception:
        pass


def _on_lidar_points_message(message) -> None:
    if not proximity_sensor["enabled"]:
        return
    try:
        data = (message or {}).get("data") or {}
        decoded = data.get("data")
        if not isinstance(decoded, dict):
            return

        import numpy as _np
        pts = None
        if "points" in decoded:
            pts = _np.asarray(decoded["points"])
        elif "positions" in decoded:
            arr = _np.asarray(decoded["positions"], dtype=_np.float32)
            if arr.ndim == 1 and arr.size % 3 == 0:
                arr = arr.reshape(-1, 3)
            pts = arr
        if pts is None or pts.ndim != 2 or pts.shape[0] == 0 or pts.shape[1] < 3:
            return

        if proximity_sensor["_pose_valid"]:
            rx = proximity_sensor["_pose_x"]
            ry = proximity_sensor["_pose_y"]
            rz = proximity_sensor["_pose_z"]
            yaw = proximity_sensor["_pose_yaw"]
        else:
            origin = data.get("origin") or [0.0, 0.0, 0.0]
            res = float(data.get("resolution") or 0.05)
            half = 128 * res / 2.0
            rx = float(origin[0]) + half
            ry = float(origin[1]) + half
            rz = float(origin[2]) if len(origin) >= 3 else 0.0
            yaw = 0.0

        dx = pts[:, 0] - rx
        dy = pts[:, 1] - ry
        dz = pts[:, 2] - rz

        c, s = math.cos(-yaw), math.sin(-yaw)
        lx = dx * c - dy * s
        ly = dx * s + dy * c

        cone_y = proximity_sensor["forward_cone_y_m"]
        mask = (
            (lx > 0.10)
            & (_np.abs(ly) < cone_y)
            & (dz > proximity_sensor["min_z_m"])
            & (dz < proximity_sensor["max_z_m"])
        )

        _maybe_emit_lidar_points(pts, rx, ry, yaw)

        if not _np.any(mask):
            _maybe_clear_alert_state(float("inf"))
            return

        fwd_x = lx[mask]
        fwd_y = ly[mask]
        dists = _np.sqrt(fwd_x * fwd_x + fwd_y * fwd_y)
        d = float(_np.min(dists))
        proximity_sensor["_last_distance"] = d

        _maybe_clear_alert_state(d)

        if d >= proximity_sensor["stop_distance_m"]:
            return
        if not _robot_is_moving_forward():
            return

        nearest = int(_np.argmin(dists))
        ny = float(fwd_y[nearest])
        direction = "center" if abs(ny) < 0.12 else ("left" if ny > 0 else "right")
        _trigger_proximity_alert(d, direction, "lidar_points")
    except Exception as exc:
        emit_log("warning", f"Callback lidar points: {exc}")


# ────────────────────────────────────────────────────────────────────
# ON / OFF — los endpoints HTTP las llaman via run_async()
# ────────────────────────────────────────────────────────────────────
async def proximity_enable_async() -> bool:
    from unitree_webrtc_connect.constants import DATA_CHANNEL_TYPE, RTC_TOPIC

    conn = get_connection()
    pub_sub = get_pub_sub()
    if not conn or not pub_sub:
        return False

    try:
        conn.datachannel.set_decoder(decoder_type="native")
    except Exception as exc:
        emit_log("warning", f"set_decoder native: {exc}")

    try:
        await conn.datachannel.disableTrafficSaving(True)
    except Exception as exc:
        emit_log("warning", f"disableTrafficSaving: {exc}")

    for payload in ("ON", {"enable": 1}):
        try:
            pub_sub.publish_without_callback(
                RTC_TOPIC["ULIDAR_SWITCH"],
                payload,
                DATA_CHANNEL_TYPE["MSG"],
            )
        except Exception as exc:
            emit_log("warning", f"ULIDAR_SWITCH {payload!r}: {exc}")
    emit_log("info", "Lidar L1 encendido (verifica que el anillo gire)")

    subscribed: list[str] = []
    try:
        pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], _on_robot_pose_message)
        subscribed.append(RTC_TOPIC["ROBOTODOM"])
    except Exception as exc:
        emit_log("warning", f"subscribe robot_pose: {exc}")

    try:
        pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], _on_lidar_points_message)
        subscribed.append(RTC_TOPIC["ULIDAR_ARRAY"])
    except Exception as exc:
        emit_log("error", f"subscribe lidar array: {exc}")

    proximity_sensor["_subscribed"] = bool(subscribed)
    proximity_sensor["_subscribed_topics"] = subscribed
    proximity_sensor["_pose_valid"] = False

    if subscribed:
        emit_log(
            "success",
            f"Sensor activo. Suscrito a {len(subscribed)} topics. "
            f"Parar si <{proximity_sensor['stop_distance_m']*100:.0f} cm frontal.",
        )
    return bool(subscribed)


async def proximity_disable_async() -> None:
    from unitree_webrtc_connect.constants import DATA_CHANNEL_TYPE, RTC_TOPIC

    pub_sub = get_pub_sub()
    for t in proximity_sensor.get("_subscribed_topics") or []:
        try:
            pub_sub and pub_sub.unsubscribe(t)
        except Exception:
            pass

    if pub_sub:
        for payload in ("OFF", {"enable": 0}):
            try:
                pub_sub.publish_without_callback(
                    RTC_TOPIC["ULIDAR_SWITCH"],
                    payload,
                    DATA_CHANNEL_TYPE["MSG"],
                )
            except Exception:
                pass

    proximity_sensor["_subscribed"] = False
    proximity_sensor["_subscribed_topics"] = []
    proximity_sensor["_last_distance"] = None
    proximity_sensor["_pose_valid"] = False
