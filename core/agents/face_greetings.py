"""Autonomous greeting when Diver recognizes a registered face."""

from __future__ import annotations

import threading
import time

from yolo_detector import detector as yolo_detector

from ..runtime import socketio
from ..state import robot_state
from .tools import call_robot_action


class FaceGreetingReactor:
    def __init__(self) -> None:
        self.enabled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cooldown_s = 45.0
        self._poll_s = 1.0
        self._last_greet_at: dict[str, float] = {}
        self._last_tick_ts = 0.0
        self._last_skip_reason = "nunca arrancado"
        self._last_seen_names: list[str] = []
        self._last_greeted_name: str | None = None
        self._last_greeted_ts = 0.0

    def start(self) -> None:
        if self.enabled and self._thread and self._thread.is_alive():
            return
        self.enabled = True
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="FaceGreetingReactor",
            )
            self._thread.start()
        yolo_detector.set_face_recognition_enabled(True)
        print("[ROSTROS] saludo autonomo ACTIVADO")

    def stop(self) -> None:
        if not self.enabled:
            return
        self.enabled = False
        self._stop.set()
        yolo_detector.set_face_recognition_enabled(False)
        print("[ROSTROS] saludo autonomo APAGADO")

    def state(self) -> dict:
        return {
            "enabled": self.enabled,
            "cooldown_s": self._cooldown_s,
            "last_seen_names": list(self._last_seen_names),
            "last_greeted_name": self._last_greeted_name,
            "last_greeted_age_s": (
                round(time.time() - self._last_greeted_ts, 2)
                if self._last_greeted_ts else None
            ),
            "last_tick_age_s": (
                round(time.time() - self._last_tick_ts, 2)
                if self._last_tick_ts else None
            ),
            "last_skip_reason": self._last_skip_reason,
        }

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
                    self._last_seen_names = []
                    self._last_skip_reason = "YOLO no corriendo"
                    if self._stop.wait(self._poll_s):
                        return
                    continue

                dets = yolo_detector.get_detections() or []
                names = sorted({
                    str(d.get("person_name")).strip()
                    for d in dets
                    if d.get("kind") == "face"
                    and d.get("known")
                    and d.get("person_name")
                })
                self._last_seen_names = names

                if not names:
                    self._last_skip_reason = "sin rostros conocidos"
                else:
                    self._last_skip_reason = f"rostros conocidos: {', '.join(names)}"
                    for name in names:
                        self._greet(name)
            except Exception as exc:
                self._last_skip_reason = f"error: {exc}"
                print(f"[ROSTROS] error en loop: {exc}")

            if self._stop.wait(self._poll_s):
                return

    def _greet(self, name: str) -> None:
        now = time.time()
        last = self._last_greet_at.get(name, 0.0)
        if now - last < self._cooldown_s:
            return

        self._last_greet_at[name] = now
        self._last_greeted_name = name
        self._last_greeted_ts = now
        say = f"Hola, {name}."

        robot_ok = None
        robot_msg = ""
        if robot_state.get("connected"):
            try:
                result = call_robot_action("hello")
                robot_ok = bool(result.get("ok"))
                robot_msg = result.get("msg") or ""
            except Exception as exc:
                robot_ok = False
                robot_msg = str(exc)

        try:
            socketio.emit("face_greeting", {
                "person_name": name,
                "say": say,
                "ok": True,
                "robot_ok": robot_ok,
                "msg": robot_msg,
            })
        except Exception as exc:
            print(f"[ROSTROS] no pude emitir socket: {exc}")


face_greeting_reactor = FaceGreetingReactor()
