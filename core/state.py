"""Estado global del sistema. Estos diccionarios viven aqui para que cualquier
modulo pueda leerlos/mutarlos sin pasar por imports circulares con app.py.

NOTA: Mantener la forma EXACTA de los diccionarios — el frontend depende de
ellos. Si vas a renombrar campos, hazlo en una segunda fase y migra el
frontend en el mismo commit.
"""

from config.config import ROBOT_IP


# ────────────────────────────────────────────────────────────────────
# Estado del robot expuesto al frontend (via Socket.IO state_update)
# ────────────────────────────────────────────────────────────────────
robot_state = {
    "connected": False,
    "ip": ROBOT_IP,
    "battery": 0,
    "speed": 0.0,
    "mode": "Standby",
    "routine_running": False,
    "routine_name": None,
}


# ────────────────────────────────────────────────────────────────────
# Sensor de proximidad (LiDAR L1 + ROBOTODOM). Solo paramos cuando algo
# esta MUY cerca directamente al frente y el robot va hacia alla.
# Cono estrecho (+-15 cm) para que pase por pasillos sin detenerse.
# ────────────────────────────────────────────────────────────────────
proximity_sensor = {
    "enabled": False,
    "stop_distance_m": 0.30,
    "clear_distance_m": 0.55,
    "forward_cone_y_m": 0.15,
    "min_z_m": 0.12,
    "max_z_m": 0.60,
    "min_forward_vel_mps": 0.05,
    "cmd_fresh_s": 0.7,
    "_last_alert_ts": 0.0,
    "_alert_active": False,
    "_clear_since": 0.0,
    "_subscribed": False,
    "_subscribed_topics": [],
    "_last_distance": None,
    "_last_source": None,
    "_last_cmd_x": 0.0,
    "_last_cmd_ts": 0.0,
    "_force_until": 0.0,
    "_pose_x": 0.0,
    "_pose_y": 0.0,
    "_pose_z": 0.0,
    "_pose_yaw": 0.0,
    "_pose_valid": False,
    "_last_points_emit_ts": 0.0,
}


# ────────────────────────────────────────────────────────────────────
# Ultimo QR detectado por YOLO + pose en el momento de la deteccion.
# ────────────────────────────────────────────────────────────────────
qr_state = {
    "last_text": None,
    "last_ts": 0.0,
    "last_pose": None,
    "dedup_window_s": 2.0,
}


# ────────────────────────────────────────────────────────────────────
# Follow-QR: el robot persigue cualquier QR que vea (modo seguimiento).
# ────────────────────────────────────────────────────────────────────
follow_state = {
    "running": False,
    "_task": None,
    "_cancel": False,
    # Tuning
    "max_linear": 0.35,
    "max_angular": 0.75,
    "target_area": 0.10,
    "near_area": 0.18,
    "k_angular": 1.8,
    "lost_timeout_s": 1.5,
    # Estado para la UI
    "_last_reason": "",
    "_last_x": 0.0,
    "_last_z": 0.0,
    "_last_qr_text": None,
}


# ────────────────────────────────────────────────────────────────────
# Auto-Ruta (waypoint follower).
# ────────────────────────────────────────────────────────────────────
autoroute_state = {
    "running": False,
    "cycles_total": 0,
    "cycle_now": 0,
    "waypoints": [],
    "wp_now": 0,
    "_task": None,
    "_cancel": False,
    "translate_to_pose": False,
    "smooth_mode": False,
    "linear_speed": 0.35,
    "angular_speed": 0.75,
    "reach_radius_m": 0.25,
    "heading_align_rad": 0.4,
    "timeout_per_wp_s": 20.0,
    "smooth_linear_speed": 0.4,
    "smooth_reach_radius_m": 0.5,
    "smooth_heading_align_rad": 1.4,
}


# ────────────────────────────────────────────────────────────────────
# Flag global para abortar rutinas en ejecucion.
# Mutable contenedor (list) para que `from .state import stop_flag` no
# capture un snapshot — quien lee tiene que hacer `stop_flag[0]`.
# Convencion: usar las funciones helper, no tocar el indice directo.
# ────────────────────────────────────────────────────────────────────
_stop_routine_flag = [False]


def request_stop_routine() -> None:
    _stop_routine_flag[0] = True


def clear_stop_routine() -> None:
    _stop_routine_flag[0] = False


def is_stop_requested() -> bool:
    return _stop_routine_flag[0]
