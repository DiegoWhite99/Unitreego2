"""Reactor de gestos: el robot reacciona cuando ve una persona haciendo un
gesto reconocido por YOLO-pose (mano arriba -> saluda, etc).

Diseño:
- Polling cada ~1.2 s sobre `yolo_detector.get_detections()`.
- Por gesto: cooldown de 8 s para evitar repetir ante presencia sostenida.
- Disabled por defecto; el frontend lo activa con /api/gestures/start.
- Emite `gesture_reaction` por Socket.IO.
- Si robot desconectado o YOLO apagado, espera.

REQUISITOS para que dispare:
  1. POST /api/gestures/start  (o el toggle de la UI en /agente).
  2. YOLO corriendo con un modelo POSE (yolov8n-pose.pt). El modelo
     regular yolov8n.pt NO infiere gestos — `det["gesture"]` queda None.
  3. Robot conectado (sino, no hay a quién mandarle el "hello").
"""

from __future__ import annotations

import threading
import time

from yolo_detector import detector as yolo_detector

from ..runtime import socketio
from ..state import robot_state
from .tools import call_robot_action


GESTURE_REACTIONS = {
    "mano_arriba":         {"action": "hello",     "say": "¡Hola! 🐾"},
    "ambas_manos_arriba":  {"action": "hello",     "say": "¡Aquí estoy!"},
    "brazos_arriba":       {"action": "hello",     "say": "¡Te veo!"},
    "manos_juntas":        {"action": "heart",     "say": "🐾"},
    "t_pose":              {"action": "wiggle",    "say": "Modo T-pose detectado."},
    "mano_abajo":          {"action": "lie",       "say": "Me acuesto 🐶"},
    "manos_en_cadera":     {"action": "sit",       "say": "Me siento."},
    "puños_arriba":        {"action": "frontjump", "say": "¡Salto!"},
}


class GestureReactor:
    def __init__(self) -> None:
        self.enabled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cooldown_s = 8.0
        self._last_fire_at: dict[str, float] = {}
        self._poll_s = 1.2
        # Para `/api/gestures/debug` — refleja el ultimo tick de polling.
        self._last_tick_ts: float = 0.0
        self._last_skip_reason: str = "nunca arrancado"
        self._last_detections_count: int = 0
        self._last_seen_gestures: list[str] = []
        self._last_fired_gesture: str | None = None
        self._last_fired_ts: float = 0.0

    def start(self) -> None:
        if self.enabled:
            print("[GESTOS] start() ignorado: ya estaba ACTIVADO")
            return
        self.enabled = True
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="GestureReactor"
            )
            self._thread.start()
        print(
            "[GESTOS] reactor ACTIVADO. Requiere YOLO con modelo *-pose.pt + "
            "robot conectado para disparar."
        )

    def stop(self) -> None:
        if not self.enabled:
            return
        self.enabled = False
        self._stop.set()
        print("[GESTOS] reactor de gestos: APAGADO")

    def state(self) -> dict:
        return {
            "enabled":    self.enabled,
            "cooldown_s": self._cooldown_s,
            "mappings":   {k: v["action"] for k, v in GESTURE_REACTIONS.items()},
        }

    def debug_snapshot(self) -> dict:
        """Snapshot detallado para diagnosticar por qué no dispara.
        Lo expone el endpoint /api/gestures/debug."""
        yolo_status: dict = {}
        try:
            yolo_status = yolo_detector.status() or {}
        except Exception as exc:
            yolo_status = {"error": str(exc)}

        model_name = (yolo_status.get("model") or "")
        is_pose_model = "pose" in model_name.lower()

        cooldowns_remaining = {
            g: max(0.0, self._cooldown_s - (time.time() - ts))
            for g, ts in self._last_fire_at.items()
        }

        # Diagnostico: por qué no dispara en este momento.
        diagnostic = []
        if not self.enabled:
            diagnostic.append(
                "Reactor APAGADO. Activa con POST /api/gestures/start o el toggle de /agente."
            )
        if not yolo_status.get("running"):
            diagnostic.append(
                "YOLO no esta corriendo. Inicialo con POST /api/yolo/start "
                "{\"model\": \"yolov8n-pose.pt\"}."
            )
        elif not is_pose_model:
            diagnostic.append(
                f"YOLO corre con '{model_name}' pero NO es un modelo pose. "
                "Reinicia con model='yolov8n-pose.pt' (o cualquier *-pose.pt) "
                "para que se infieran gestos."
            )
        if not robot_state.get("connected"):
            diagnostic.append("Robot no conectado. Conecta el Go2 antes.")
        if not diagnostic and self._last_detections_count == 0:
            diagnostic.append(
                "Todo activo pero YOLO no ve a nadie. Acercate a la camara."
            )

        return {
            "enabled":            self.enabled,
            "thread_alive":       bool(self._thread and self._thread.is_alive()),
            "last_tick_age_s":    round(time.time() - self._last_tick_ts, 2)
                                  if self._last_tick_ts else None,
            "last_skip_reason":   self._last_skip_reason,
            "last_detections":    self._last_detections_count,
            "last_seen_gestures": self._last_seen_gestures,
            "last_fired":         self._last_fired_gesture,
            "last_fired_age_s":   round(time.time() - self._last_fired_ts, 2)
                                  if self._last_fired_ts else None,
            "cooldowns_s":        cooldowns_remaining,
            "yolo_running":       bool(yolo_status.get("running")),
            "yolo_model":         model_name,
            "yolo_is_pose":       is_pose_model,
            "robot_connected":    bool(robot_state.get("connected")),
            "diagnostic":         diagnostic,
        }

    def _fire(self, gesture_key: str, action: str, say: str) -> None:
        """Dispara una acción del robot respetando el cooldown por gesto.
        Centraliza el cooldown + log + emit para que el _loop pueda invocar
        tanto gestos simples como compuestos (p. ej. mano_pecho_a_cadera)."""
        now = time.time()
        last = self._last_fire_at.get(gesture_key, 0)
        if now - last < self._cooldown_s:
            return
        self._last_fire_at[gesture_key] = now
        self._last_fired_gesture = gesture_key
        self._last_fired_ts = now
        print(f"[GESTOS] gesto detectado '{gesture_key}' → acción '{action}'")
        try:
            result = call_robot_action(action)
        except Exception as ex:
            result = {"ok": False, "msg": str(ex)}
        try:
            socketio.emit("gesture_reaction", {
                "gesture": gesture_key,
                "action":  action,
                "say":     say,
                "ok":      bool(result.get("ok")),
                "msg":     result.get("msg") or "",
            })
        except Exception as ex:
            print(f"[GESTOS] no pude emitir socket: {ex}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._last_tick_ts = time.time()

            if not self.enabled:
                self._last_skip_reason = "reactor desactivado"
                if self._stop.wait(self._poll_s):
                    return
                continue
            try:
                if not yolo_detector.is_running():
                    self._last_skip_reason = "YOLO no corriendo"
                    self._last_detections_count = 0
                    if self._stop.wait(self._poll_s):
                        return
                    continue
                if not robot_state.get("connected"):
                    self._last_skip_reason = "robot desconectado"
                    self._last_detections_count = 0
                    if self._stop.wait(self._poll_s):
                        return
                    continue

                dets = yolo_detector.get_detections() or []
                self._last_detections_count = len(dets)

                seen_gestures: set[str] = set()
                for d in dets:
                    g = d.get("gesture")
                    if g and g in GESTURE_REACTIONS:
                        seen_gestures.add(g)
                self._last_seen_gestures = sorted(seen_gestures)

                if not seen_gestures:
                    # Diagnostico fino: ¿hay personas pero el modelo no es pose?
                    has_persons = any(
                        (d.get("label") or d.get("class_name")) == "person"
                        for d in dets
                    )
                    has_gesture_field = any("gesture" in d for d in dets)
                    if has_persons and not has_gesture_field:
                        self._last_skip_reason = (
                            "personas detectadas pero el modelo YOLO no es pose "
                            "(usa yolov8n-pose.pt para inferir gestos)"
                        )
                    elif has_persons:
                        self._last_skip_reason = (
                            "personas detectadas pero sin gesto reconocido"
                        )
                    else:
                        self._last_skip_reason = "sin personas en cuadro"
                else:
                    self._last_skip_reason = (
                        f"gestos vistos: {sorted(seen_gestures)}"
                    )

                # Cada gesto reconocido dispara su acción respetando
                # cooldown por gesto (no hay gestos compuestos).
                for g in seen_gestures:
                    spec = GESTURE_REACTIONS[g]
                    self._fire(g, spec["action"], spec.get("say", ""))
            except Exception as ex:
                self._last_skip_reason = f"error: {ex}"
                print(f"[GESTOS] error en loop: {ex}")
            if self._stop.wait(self._poll_s):
                return


# Singleton compartido por toda la app.
gesture_reactor = GestureReactor()
