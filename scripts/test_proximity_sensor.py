"""
Test del sensor de proximidad del Go2 Air (v2).

En Go2 Air `SportModeState.range_obstacle` siempre viene en [0,0,0,0] (solo
Go2 Pro/EDU lo populan), así que la detección real se hace así:

  1. Prender el lidar L1 (el anillo debe girar).
  2. Subscribir a `rt/utlidar/robot_pose` -> pose del robot en el frame del mapa.
  3. Subscribir a `rt/utlidar/voxel_map_compressed` -> nube de puntos (world frame).
  4. Cada frame: transformar puntos a frame del robot, filtrar cono frontal
     y encontrar la distancia mínima. Si <60 cm -> ¡obstáculo!

Uso:
  python scripts/test_proximity_sensor.py
Luego acerca algo (tu mano, una pared) al frente del robot a 30-80 cm y
observa la columna NEAREST_FWD (distancia mínima frontal en metros).
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import json
import math
import time

import numpy as np

from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import RTC_TOPIC, DATA_CHANNEL_TYPE
from config.config import ROBOT_IP


STOP_DISTANCE_M = 0.60
FORWARD_CONE_Y_M = 0.55
MIN_Z_M = 0.05
MAX_Z_M = 0.80


class Monitor:
    def __init__(self):
        self.pose = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "valid": False}
        self.lidar_points = 0
        self.lidar_frames = 0
        self.last_origin = None
        self.last_resolution = None
        self.last_points_arr = None
        self.nearest_fwd = None
        self.odom_first_dump = True

    # ------------------------------------------------------------
    def on_robot_odom(self, msg):
        try:
            data = (msg or {}).get("data") or {}
            if self.odom_first_dump:
                self.odom_first_dump = False
                try:
                    print("\n[ODOM first payload] " + json.dumps(data, default=str)[:500])
                except Exception:
                    print(f"\n[ODOM first payload keys] {list(data.keys())}")

            # Varios firmwares anidan la pose de distinta forma.
            pose = data.get("pose") or data
            position = pose.get("position") or {}
            orientation = pose.get("orientation") or {}

            if not position and isinstance(pose, list) and len(pose) >= 3:
                self.pose["x"], self.pose["y"], self.pose["z"] = map(float, pose[:3])
                self.pose["valid"] = True
                return

            self.pose["x"] = float(position.get("x", self.pose["x"]))
            self.pose["y"] = float(position.get("y", self.pose["y"]))
            self.pose["z"] = float(position.get("z", self.pose["z"]))

            qx = float(orientation.get("x", 0))
            qy = float(orientation.get("y", 0))
            qz = float(orientation.get("z", 0))
            qw = float(orientation.get("w", 1))
            # yaw desde quaternion (Z-up)
            siny = 2.0 * (qw * qz + qx * qy)
            cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
            self.pose["yaw"] = math.atan2(siny, cosy)
            self.pose["valid"] = True
        except Exception as exc:
            print(f"[ODOM err] {exc}")

    # ------------------------------------------------------------
    def on_lidar(self, msg):
        try:
            data = (msg or {}).get("data") or {}
            self.last_origin = data.get("origin")
            self.last_resolution = data.get("resolution")
            decoded = data.get("data")
            if not isinstance(decoded, dict):
                return

            pts = decoded.get("points")
            if pts is None and "positions" in decoded:
                arr = np.asarray(decoded["positions"], dtype=np.float32)
                if arr.ndim == 1 and arr.size % 3 == 0:
                    arr = arr.reshape(-1, 3)
                pts = arr
            if pts is None:
                return
            pts = np.asarray(pts)
            if pts.ndim != 2 or pts.shape[0] == 0 or pts.shape[1] < 3:
                return

            self.lidar_frames += 1
            self.lidar_points = int(pts.shape[0])
            self.last_points_arr = pts

            self.nearest_fwd = self._compute_nearest_forward(pts)
        except Exception as exc:
            print(f"[LIDAR err] {exc}")

    # ------------------------------------------------------------
    def _compute_nearest_forward(self, pts):
        """Transforma puntos a frame del robot y devuelve la distancia mínima
        frontal en metros (o None si no hay datos utilizables)."""
        if self.pose["valid"]:
            rx, ry, rz, yaw = self.pose["x"], self.pose["y"], self.pose["z"], self.pose["yaw"]
        elif self.last_origin is not None and len(self.last_origin) >= 2:
            # Heurística: en el Go2 el voxel grid se centra en el robot, con
            # 128 celdas y 0.05 m -> 3.2 m de medio ancho.
            res = self.last_resolution or 0.05
            half = 128 * res / 2.0
            rx = self.last_origin[0] + half
            ry = self.last_origin[1] + half
            rz = (self.last_origin[2] if len(self.last_origin) >= 3 else 0.0)
            yaw = 0.0
        else:
            return None

        dx = pts[:, 0] - rx
        dy = pts[:, 1] - ry
        dz = pts[:, 2] - rz

        c, s = math.cos(-yaw), math.sin(-yaw)
        lx = dx * c - dy * s
        ly = dx * s + dy * c

        # Cono frontal
        mask = (
            (lx > 0.10) &
            (np.abs(ly) < FORWARD_CONE_Y_M) &
            (dz > MIN_Z_M) &
            (dz < MAX_Z_M)
        )
        fwd = np.stack([lx[mask], ly[mask]], axis=1)
        if fwd.shape[0] == 0:
            return None

        d = float(np.min(np.sqrt(fwd[:, 0] ** 2 + fwd[:, 1] ** 2)))
        return d


async def try_switch(pub_sub, label, payload):
    try:
        pub_sub.publish_without_callback(
            RTC_TOPIC["ULIDAR_SWITCH"],
            payload,
            DATA_CHANNEL_TYPE["MSG"],
        )
        print(f"  -> switch enviado: {label}")
    except Exception as exc:
        print(f"  -> switch {label} falló: {exc}")


async def main():
    print("=" * 60)
    print("  TEST SENSOR DE PROXIMIDAD GO2 (v2)")
    print(f"  Robot IP: {ROBOT_IP}")
    print(f"  Umbral:   < {STOP_DISTANCE_M*100:.0f} cm frontal = parar")
    print("=" * 60)

    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP,
    )
    print("[INFO] Conectando...")
    await conn.connect()
    print("[OK] Conectado.")
    pub_sub = conn.datachannel.pub_sub

    # Decoder nativo (devuelve Nx3 ndarray con puntos)
    try:
        conn.datachannel.set_decoder(decoder_type='native')
        print("[CFG] decoder lidar = native")
    except Exception as exc:
        print(f"[WARN] no se pudo cambiar decoder: {exc}")

    await asyncio.sleep(1.5)

    mon = Monitor()

    print("[SUB] rt/utlidar/robot_pose")
    pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], mon.on_robot_odom)
    print("[SUB] rt/utlidar/voxel_map_compressed")
    pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], mon.on_lidar)

    try:
        await conn.datachannel.disableTrafficSaving(True)
    except Exception as exc:
        print(f"[WARN] disableTrafficSaving: {exc}")

    print("\n[SWITCH LIDAR ON]")
    await try_switch(pub_sub, "string ON", "ON")
    await asyncio.sleep(0.3)
    await try_switch(pub_sub, "dict enable=1", {"enable": 1})
    await asyncio.sleep(2.0)

    print("\n" + "=" * 60)
    print("  MONITOR 30 s — ACERCA UN OBJETO AL FRENTE DEL ROBOT")
    print("  (columna NEAREST_FWD es la distancia mínima al cono frontal)")
    print("=" * 60)

    t0 = time.time()
    last_report = 0.0
    triggered = False
    while time.time() - t0 < 30:
        await asyncio.sleep(0.1)
        now = time.time() - t0
        if now - last_report >= 0.3:
            last_report = now
            pose = mon.pose
            pose_s = (f"x={pose['x']:+.2f} y={pose['y']:+.2f} yaw={math.degrees(pose['yaw']):+.1f}°"
                      if pose["valid"] else "(sin ROBOTODOM, usando origin)")
            nf = mon.nearest_fwd
            nf_s = f"{nf*100:5.1f}cm" if nf is not None else "   -  "
            flag = ""
            if nf is not None and nf < STOP_DISTANCE_M:
                flag = "  <<< ALERTA OBSTACULO"
                if not triggered:
                    triggered = True
                    print("[!] Primera alerta de obstáculo.")
            print(f"t={now:5.1f}s  pose={pose_s}  NEAREST_FWD={nf_s}  "
                  f"frames={mon.lidar_frames}  pts={mon.lidar_points}{flag}")

    print("\n[INFO] Apagando lidar...")
    await try_switch(pub_sub, "string OFF", "OFF")
    await asyncio.sleep(0.5)
    await conn.disconnect()
    print("[DONE]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ABORT] Ctrl+C")
