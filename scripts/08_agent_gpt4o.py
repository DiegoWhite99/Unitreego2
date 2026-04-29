"""
Agente cognitivo GPT-4o para Unitree Go2 (WebRTC + Function Calling).

Idea base
---------
El robot NO ejecuta una secuencia ciega de pasos. Tiene un "cerebro"
(GPT-4o) que recibe en cada tick:
  - la última distancia frontal medida por el LiDAR (en metros)
  - la pose actual relativa al origen
  - el estado del movimiento (parado / moviéndose / regresando)
y decide con qué *tool* responder:
  - iniciar_movimiento_continuo(velocidad)
  - detener_movimiento()
  - regresar_origen()

El bucle es ReAct: observación -> razonamiento del modelo -> tool call ->
ejecución sobre el robot -> nueva observación. La condición típica:
"avanza hasta la pared y regresa al origen" la resuelve el modelo
mirando la distancia frontal y disparando `detener_movimiento` cuando
detecta que es crítica.

Uso
---
    python scripts/08_agent_gpt4o.py
    python scripts/08_agent_gpt4o.py --simulate          # sin robot real
    python scripts/08_agent_gpt4o.py --goal "explora hasta la pared y vuelve"

Requisitos:
    pip install openai
y `OPENAI_API_KEY` válido en config/config.py.
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from openai import OpenAI

from config.config import ROBOT_IP, OPENAI_API_KEY, GEMINI_MODEL


# ────────────────────────────────────────────────────────────────────
# 1) DEFINICIÓN DE TOOLS (esquemas JSON para Function Calling)
# ────────────────────────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "iniciar_movimiento_continuo",
            "description": (
                "Inicia un avance continuo del robot hacia el frente. "
                "El robot seguirá moviéndose hasta que se llame a "
                "detener_movimiento(). Usar cuando hay espacio libre y "
                "se requiere explorar o aproximarse a un objetivo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "velocidad_mps": {
                        "type": "number",
                        "description": "Velocidad lineal en m/s (rango seguro 0.1 a 0.6).",
                        "minimum": 0.05,
                        "maximum": 0.8,
                    }
                },
                "required": ["velocidad_mps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detener_movimiento",
            "description": (
                "Detiene inmediatamente cualquier movimiento del robot. "
                "Llamar siempre que la distancia frontal sea crítica "
                "(<=60 cm) o cuando el objetivo se haya cumplido."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regresar_origen",
            "description": (
                "Hace que el robot regrese al punto donde inició la sesión "
                "(coordenadas guardadas como origen). Realiza un giro de 180°, "
                "avanza hasta la pose inicial y se detiene. Solo invocar cuando "
                "el robot esté detenido."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ────────────────────────────────────────────────────────────────────
# 2) ESTADO GLOBAL DEL ROBOT
# ────────────────────────────────────────────────────────────────────
@dataclass
class RobotState:
    pose_x: float = 0.0
    pose_y: float = 0.0
    yaw: float = 0.0
    pose_valid: bool = False

    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    origin_yaw: Optional[float] = None

    nearest_fwd_m: Optional[float] = None
    last_lidar_ts: float = 0.0

    motion_status: str = "idle"      # idle | moving | returning | stopped
    last_command_velocity: float = 0.0
    history_log: list = field(default_factory=list)

    def snapshot_for_model(self) -> dict:
        """Lo que el modelo verá en cada tick. JSON-serializable."""
        return {
            "distancia_frontal_m": (
                round(self.nearest_fwd_m, 3)
                if self.nearest_fwd_m is not None else None
            ),
            "estado_movimiento": self.motion_status,
            "velocidad_actual_mps": self.last_command_velocity,
            "pose_relativa_origen": {
                "dx": round(self.pose_x - (self.origin_x or 0.0), 3),
                "dy": round(self.pose_y - (self.origin_y or 0.0), 3),
                "yaw_deg": round(math.degrees(self.yaw), 1),
            } if self.pose_valid else None,
            "lidar_actualizado_hace_s": (
                round(time.time() - self.last_lidar_ts, 2)
                if self.last_lidar_ts else None
            ),
        }


# ────────────────────────────────────────────────────────────────────
# 3) CAPA WEBRTC: percepción (LiDAR + odom) y actuación (sport_mod)
# ────────────────────────────────────────────────────────────────────
STOP_DISTANCE_M = 0.60
FORWARD_CONE_Y_M = 0.55
MIN_Z_M, MAX_Z_M = 0.05, 0.80


class RobotInterface:
    """
    Abstrae la capa WebRTC. Si modo=simulate no hay robot real:
    - se simula una pared que se acerca a 0.4 m/s mientras el robot
      esté en estado 'moving', y se aleja al regresar.
    """

    def __init__(self, state: RobotState, simulate: bool = False):
        self.state = state
        self.simulate = simulate
        self.conn = None
        self.pub_sub = None
        self._sim_distance = 3.5  # pared virtual a 3.5 m al inicio
        self._sim_task: Optional[asyncio.Task] = None

    # ---------- conexión ----------
    async def connect(self):
        if self.simulate:
            print("[SIM] Modo simulación activado (sin robot).")
            self.state.pose_valid = True
            self.state.origin_x = self.state.origin_y = 0.0
            self.state.origin_yaw = 0.0
            self.state.nearest_fwd_m = self._sim_distance
            self.state.last_lidar_ts = time.time()
            self._sim_task = asyncio.create_task(self._sim_loop())
            return

        from unitree_webrtc_connect import (
            UnitreeWebRTCConnection,
            WebRTCConnectionMethod,
        )
        from unitree_webrtc_connect.constants import RTC_TOPIC

        self._RTC_TOPIC = RTC_TOPIC
        print(f"[NET] Conectando al Go2 en {ROBOT_IP}...")
        self.conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP
        )
        await self.conn.connect()
        print("[NET] Conectado.")
        self.pub_sub = self.conn.datachannel.pub_sub

        try:
            self.conn.datachannel.set_decoder(decoder_type="native")
        except Exception as exc:
            print(f"[WARN] decoder lidar: {exc}")

        try:
            await self.conn.datachannel.disableTrafficSaving(True)
        except Exception as exc:
            print(f"[WARN] disableTrafficSaving: {exc}")

        self.pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], self._on_odom)
        self.pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], self._on_lidar)

        # Encender LiDAR
        self.pub_sub.publish_without_callback(
            RTC_TOPIC["ULIDAR_SWITCH"], "ON",
            __import__(
                "unitree_webrtc_connect.constants", fromlist=["DATA_CHANNEL_TYPE"]
            ).DATA_CHANNEL_TYPE["MSG"],
        )
        await asyncio.sleep(2.0)

    async def disconnect(self):
        if self.simulate:
            if self._sim_task:
                self._sim_task.cancel()
            return
        try:
            from unitree_webrtc_connect.constants import (
                RTC_TOPIC, DATA_CHANNEL_TYPE,
            )
            self.pub_sub.publish_without_callback(
                RTC_TOPIC["ULIDAR_SWITCH"], "OFF", DATA_CHANNEL_TYPE["MSG"]
            )
        except Exception:
            pass
        if self.conn:
            await self.conn.disconnect()

    # ---------- callbacks de percepción ----------
    def _on_odom(self, msg):
        try:
            data = (msg or {}).get("data") or {}
            pose = data.get("pose") or data
            position = pose.get("position") or {}
            orientation = pose.get("orientation") or {}
            self.state.pose_x = float(position.get("x", self.state.pose_x))
            self.state.pose_y = float(position.get("y", self.state.pose_y))
            qx = float(orientation.get("x", 0))
            qy = float(orientation.get("y", 0))
            qz = float(orientation.get("z", 0))
            qw = float(orientation.get("w", 1))
            siny = 2.0 * (qw * qz + qx * qy)
            cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
            self.state.yaw = math.atan2(siny, cosy)
            self.state.pose_valid = True
            if self.state.origin_x is None:
                self.state.origin_x = self.state.pose_x
                self.state.origin_y = self.state.pose_y
                self.state.origin_yaw = self.state.yaw
                print(
                    f"[POSE] Origen guardado: "
                    f"({self.state.origin_x:+.2f}, {self.state.origin_y:+.2f})"
                )
        except Exception as exc:
            print(f"[ODOM err] {exc}")

    def _on_lidar(self, msg):
        try:
            data = (msg or {}).get("data") or {}
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
            self.state.nearest_fwd_m = self._compute_nearest_forward(pts)
            self.state.last_lidar_ts = time.time()
        except Exception as exc:
            print(f"[LIDAR err] {exc}")

    def _compute_nearest_forward(self, pts) -> Optional[float]:
        if not self.state.pose_valid:
            return None
        rx, ry = self.state.pose_x, self.state.pose_y
        yaw = self.state.yaw
        dx = pts[:, 0] - rx
        dy = pts[:, 1] - ry
        dz = pts[:, 2]
        c, s = math.cos(-yaw), math.sin(-yaw)
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        mask = (
            (lx > 0.10)
            & (np.abs(ly) < FORWARD_CONE_Y_M)
            & (dz > MIN_Z_M)
            & (dz < MAX_Z_M)
        )
        fwd_x = lx[mask]
        fwd_y = ly[mask]
        if fwd_x.size == 0:
            return None
        return float(np.min(np.sqrt(fwd_x ** 2 + fwd_y ** 2)))

    # ---------- actuación ----------
    async def move_forward(self, vx: float):
        self.state.last_command_velocity = vx
        self.state.motion_status = "moving"
        if self.simulate:
            return
        from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
        # BalanceStand previo para evitar que el robot esté tumbado.
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["BalanceStand"]}
        )
        await asyncio.sleep(0.3)
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Move"],
             "parameter": {"x": vx, "y": 0.0, "z": 0.0}},
        )

    async def stop(self):
        self.state.last_command_velocity = 0.0
        self.state.motion_status = "stopped"
        if self.simulate:
            return
        from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StopMove"]}
        )

    async def return_to_origin(self):
        """Gira 180° y avanza hasta la pose inicial. Versión sencilla
        suficiente para un script base; sin planificación de obstáculos."""
        self.state.motion_status = "returning"
        if self.simulate:
            # En simulación: alejamos la pared y "volvemos" en 3 s.
            for _ in range(15):
                self._sim_distance = min(self._sim_distance + 0.25, 3.5)
                await asyncio.sleep(0.2)
            self.state.motion_status = "stopped"
            self.state.last_command_velocity = 0.0
            return

        from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC

        # 1) Stop por seguridad.
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StopMove"]}
        )
        await asyncio.sleep(0.5)

        # 2) Giro 180° (yaw rate ~ 0.7 rad/s -> ~4.5 s para π rad).
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Move"],
             "parameter": {"x": 0.0, "y": 0.0, "z": 0.7}},
        )
        await asyncio.sleep(4.5)
        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StopMove"]}
        )
        await asyncio.sleep(0.5)

        # 3) Avanzar hacia el origen mientras la distancia residual sea > 15 cm.
        deadline = time.time() + 30.0
        while time.time() < deadline:
            dx = (self.state.origin_x or 0.0) - self.state.pose_x
            dy = (self.state.origin_y or 0.0) - self.state.pose_y
            if math.hypot(dx, dy) < 0.15:
                break
            await self.pub_sub.publish_request_new(
                RTC_TOPIC["SPORT_MOD"],
                {"api_id": SPORT_CMD["Move"],
                 "parameter": {"x": 0.3, "y": 0.0, "z": 0.0}},
            )
            await asyncio.sleep(0.5)

        await self.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StopMove"]}
        )
        self.state.motion_status = "stopped"
        self.state.last_command_velocity = 0.0

    # ---------- simulación ----------
    async def _sim_loop(self):
        try:
            while True:
                await asyncio.sleep(0.2)
                if self.state.motion_status == "moving":
                    self._sim_distance = max(
                        0.05,
                        self._sim_distance - self.state.last_command_velocity * 0.2,
                    )
                self.state.nearest_fwd_m = self._sim_distance
                self.state.last_lidar_ts = time.time()
        except asyncio.CancelledError:
            return


# ────────────────────────────────────────────────────────────────────
# 4) DISPATCHER DE TOOLS — conecta los nombres del modelo con el robot
# ────────────────────────────────────────────────────────────────────
async def dispatch_tool(robot: RobotInterface, name: str, args: dict) -> dict:
    if name == "iniciar_movimiento_continuo":
        v = float(args.get("velocidad_mps", 0.3))
        v = max(0.05, min(v, 0.8))
        await robot.move_forward(v)
        return {"ok": True, "ejecutado": "iniciar_movimiento_continuo",
                "velocidad_aplicada": v}

    if name == "detener_movimiento":
        await robot.stop()
        return {"ok": True, "ejecutado": "detener_movimiento"}

    if name == "regresar_origen":
        await robot.return_to_origin()
        return {"ok": True, "ejecutado": "regresar_origen",
                "pose_final": robot.state.snapshot_for_model()}

    return {"ok": False, "error": f"tool desconocida: {name}"}


# ────────────────────────────────────────────────────────────────────
# 5) BUCLE COGNITIVO ReAct
# ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres el cerebro de un robot cuadrúpedo Unitree Go2.
Recibes en cada tick un JSON con la distancia frontal en metros, el
estado del movimiento y la pose relativa al origen.

Reglas de seguridad (NO negociables):
1. Si la distancia frontal es <= 0.6 m y el robot está moviéndose,
   llama inmediatamente a detener_movimiento.
2. Nunca inicies movimiento si el estado no es 'idle' o 'stopped'.
3. Velocidad recomendada: 0.25–0.45 m/s para aproximación.
4. Después de detener cerca de un obstáculo, evalúa el objetivo del
   usuario y decide si llamar regresar_origen.

Responde SIEMPRE con una tool call cuando haya una acción pertinente.
Si no hay nada que hacer (p.ej. ya completaste el objetivo), responde
con texto plano que comience con "OBJETIVO_COMPLETADO".
"""


async def cognitive_loop(
    client: OpenAI,
    model: str,
    robot: RobotInterface,
    goal: str,
    tick_seconds: float = 1.0,
    max_ticks: int = 60,
):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"OBJETIVO DEL USUARIO: {goal}"},
    ]

    for tick in range(max_ticks):
        observation = robot.state.snapshot_for_model()
        messages.append({
            "role": "user",
            "content": (
                f"[tick={tick}] Estado actual:\n"
                f"{json.dumps(observation, ensure_ascii=False)}"
            ),
        })

        print(f"\n────── TICK {tick} ──────")
        print(f"[OBS] {observation}")

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.0,
        )
        choice = resp.choices[0]
        msg = choice.message
        # Append literal del modelo (con tool_calls si los hay)
        messages.append(msg.model_dump(exclude_none=True))

        if msg.content:
            print(f"[GPT] {msg.content}")
            if msg.content.strip().startswith("OBJETIVO_COMPLETADO"):
                print("[AGENT] Objetivo declarado completado por el modelo.")
                await robot.stop()
                return

        if not msg.tool_calls:
            await asyncio.sleep(tick_seconds)
            continue

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"[TOOL] {name}({args})")
            result = await dispatch_tool(robot, name, args)
            print(f"[TOOL <-] {result}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

        await asyncio.sleep(tick_seconds)

    print("[AGENT] Límite de ticks alcanzado, deteniendo por seguridad.")
    await robot.stop()


# ────────────────────────────────────────────────────────────────────
# 6) ENTRY POINT
# ────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--goal", default="Avanza hacia la pared sin chocar y luego regresa al origen.",
    )
    parser.add_argument("--simulate", action="store_true",
                        help="No conecta al robot real; usa una pared virtual.")
    parser.add_argument("--model", default=GEMINI_MODEL,
                        help="Modelo OpenAI (default: el de config.py).")
    parser.add_argument("--tick", type=float, default=1.0,
                        help="Segundos entre ticks del bucle cognitivo.")
    parser.add_argument("--max-ticks", type=int, default=60)
    args = parser.parse_args()

    if not OPENAI_API_KEY or not OPENAI_API_KEY.startswith(("sk-", "sk_")):
        raise RuntimeError(
            "OPENAI_API_KEY no está configurada en config/config.py."
        )

    client = OpenAI(api_key=OPENAI_API_KEY)
    state = RobotState()
    robot = RobotInterface(state, simulate=args.simulate)

    try:
        await robot.connect()
        # Esperar a tener pose y al menos una lectura LiDAR.
        for _ in range(50):
            if state.last_lidar_ts:
                break
            await asyncio.sleep(0.2)
        if not state.last_lidar_ts:
            print("[WARN] No llegó ningún frame de LiDAR; el modelo verá None.")

        await cognitive_loop(
            client=client,
            model=args.model,
            robot=robot,
            goal=args.goal,
            tick_seconds=args.tick,
            max_ticks=args.max_ticks,
        )
    finally:
        await robot.disconnect()
        print("[DONE]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ABORT] Ctrl+C")
