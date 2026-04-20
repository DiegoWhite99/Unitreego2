"""
yolo_detector.py — Modulo de deteccion de objetos con YOLO (Ultralytics).

Arquitectura:
  - Un detector con cola thread-safe de frames (BGR ndarray).
  - Fuentes de frames intercambiables:
      * ROBOT: push_frame() llamado por el callback WebRTC del Go2.
      * WEBCAM: thread propio con cv2.VideoCapture (fallback).
  - Thread de inferencia independiente que consume la cola y anota resultados.
  - Expone stream MJPEG + lista de detecciones (candidatos a waypoint).
"""

import threading
import time
from queue import Queue, Empty, Full
from typing import List, Dict, Optional

import cv2

_ULTRALYTICS_IMPORT_ERROR: Optional[str] = None
try:
    from ultralytics import YOLO
except Exception as exc:
    YOLO = None
    _ULTRALYTICS_IMPORT_ERROR = str(exc)


# Traduccion de las 80 clases de COCO (modelo por defecto de YOLOv8).
# Se usan caracteres ASCII para evitar problemas con cv2.putText (que no
# soporta bien tildes/enhe con las fuentes Hershey por defecto).
COCO_LABELS_ES = {
    "person": "persona", "bicycle": "bicicleta", "car": "auto",
    "motorcycle": "motocicleta", "airplane": "avion", "bus": "autobus",
    "train": "tren", "truck": "camion", "boat": "bote",
    "traffic light": "semaforo", "fire hydrant": "hidrante",
    "stop sign": "senal de pare", "parking meter": "parquimetro",
    "bench": "banca", "bird": "ave", "cat": "gato", "dog": "perro",
    "horse": "caballo", "sheep": "oveja", "cow": "vaca",
    "elephant": "elefante", "bear": "oso", "zebra": "cebra",
    "giraffe": "jirafa", "backpack": "mochila", "umbrella": "paraguas",
    "handbag": "bolso", "tie": "corbata", "suitcase": "maleta",
    "frisbee": "disco", "skis": "esquis", "snowboard": "snowboard",
    "sports ball": "pelota", "kite": "cometa", "baseball bat": "bate",
    "baseball glove": "guante", "skateboard": "patineta",
    "surfboard": "tabla de surf", "tennis racket": "raqueta",
    "bottle": "botella", "wine glass": "copa", "cup": "taza",
    "fork": "tenedor", "knife": "cuchillo", "spoon": "cuchara",
    "bowl": "tazon", "banana": "platano", "apple": "manzana",
    "sandwich": "sandwich", "orange": "naranja", "broccoli": "brocoli",
    "carrot": "zanahoria", "hot dog": "hot dog", "pizza": "pizza",
    "donut": "dona", "cake": "pastel", "chair": "silla", "couch": "sofa",
    "potted plant": "maceta", "bed": "cama", "dining table": "mesa",
    "toilet": "inodoro", "tv": "televisor", "laptop": "laptop",
    "mouse": "raton", "remote": "control remoto", "keyboard": "teclado",
    "cell phone": "celular", "microwave": "microondas", "oven": "horno",
    "toaster": "tostadora", "sink": "lavabo", "refrigerator": "refrigerador",
    "book": "libro", "clock": "reloj", "vase": "jarron", "scissors": "tijeras",
    "teddy bear": "oso de peluche", "hair drier": "secadora",
    "toothbrush": "cepillo de dientes",
}


class YoloDetector:
    """Detector YOLO con fuente de frames pluggable (robot WebRTC o webcam)."""

    SOURCE_ROBOT = "robot"
    SOURCE_WEBCAM = "webcam"

    def __init__(self):
        self._model = None
        self._model_name = "yolov8n.pt"
        self._source = self.SOURCE_ROBOT
        self._camera_index = 0
        self._conf_threshold = 0.35

        self._frame_queue: "Queue[bytes]" = Queue(maxsize=2)
        self._inference_thread: Optional[threading.Thread] = None
        self._running = False

        # Webcam fallback (opcional)
        self._webcam_cap: Optional[cv2.VideoCapture] = None
        self._webcam_thread: Optional[threading.Thread] = None
        self._webcam_running = False

        self._lock = threading.Lock()
        self._latest_frame_jpeg: Optional[bytes] = None
        self._latest_detections: List[Dict] = []
        self._frame_width = 0
        self._frame_height = 0
        self._fps = 0.0
        self._last_error: Optional[str] = None
        self._last_frame_ts = 0.0

    # ------------------------------------------------------------
    #  API DE FRAMES (desde robot o webcam)
    # ------------------------------------------------------------

    def push_frame(self, bgr_frame):
        """Inyecta un frame BGR (numpy ndarray) en la cola de inferencia.

        Usado por el callback de video WebRTC del Go2. Si la cola esta llena
        descarta el frame mas antiguo para evitar acumulacion (backpressure).
        """
        if bgr_frame is None or not self._running:
            return
        try:
            self._frame_queue.put_nowait(bgr_frame)
        except Full:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                pass
            try:
                self._frame_queue.put_nowait(bgr_frame)
            except Full:
                pass
        self._last_frame_ts = time.time()

    # ------------------------------------------------------------
    #  CICLO DE VIDA DE LA INFERENCIA
    # ------------------------------------------------------------

    def start(self, source: str = "robot", camera_index: int = 0,
              model_name: str = "yolov8n.pt", conf: float = 0.35) -> Dict:
        """Carga el modelo, abre la fuente y arranca el thread de inferencia."""
        if self._running:
            return {"ok": True, "message": "YOLO ya estaba en ejecucion"}

        if YOLO is None:
            self._last_error = (
                f"Ultralytics no esta instalado: {_ULTRALYTICS_IMPORT_ERROR}. "
                f"Ejecuta: pip install ultralytics"
            )
            return {"ok": False, "message": self._last_error}

        self._source = source if source in (self.SOURCE_ROBOT, self.SOURCE_WEBCAM) else self.SOURCE_ROBOT
        self._camera_index = int(camera_index)
        self._model_name = model_name or "yolov8n.pt"
        self._conf_threshold = float(conf)

        try:
            self._model = YOLO(self._model_name)
        except Exception as exc:
            self._last_error = f"No se pudo cargar modelo YOLO: {exc}"
            return {"ok": False, "message": self._last_error}

        self._running = True
        self._last_error = None
        self._drain_queue()

        self._inference_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._inference_thread.start()

        if self._source == self.SOURCE_WEBCAM:
            ok, msg = self._start_webcam_capture(self._camera_index)
            if not ok:
                self._running = False
                self._inference_thread = None
                return {"ok": False, "message": msg}
            return {"ok": True, "message": f"YOLO iniciado (webcam {self._camera_index}, modelo {self._model_name})"}

        return {"ok": True, "message": f"YOLO iniciado (robot, modelo {self._model_name})"}

    def stop(self) -> Dict:
        """Detiene inferencia y libera webcam si estaba activa."""
        if not self._running:
            return {"ok": True, "message": "YOLO ya estaba detenido"}

        self._running = False
        self._stop_webcam_capture()

        if self._inference_thread:
            self._inference_thread.join(timeout=3.0)
            self._inference_thread = None

        self._drain_queue()
        with self._lock:
            self._latest_frame_jpeg = None
            self._latest_detections = []

        return {"ok": True, "message": "YOLO detenido"}

    def _drain_queue(self):
        while True:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                break

    # ------------------------------------------------------------
    #  FUENTE: WEBCAM (fallback opcional)
    # ------------------------------------------------------------

    def _start_webcam_capture(self, camera_index: int):
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return False, f"No se pudo abrir la camara webcam index={camera_index}"

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self._webcam_cap = cap
        self._webcam_running = True
        self._webcam_thread = threading.Thread(target=self._webcam_loop, daemon=True)
        self._webcam_thread.start()
        return True, "OK"

    def _stop_webcam_capture(self):
        if not self._webcam_running:
            return
        self._webcam_running = False
        if self._webcam_thread:
            self._webcam_thread.join(timeout=2.0)
            self._webcam_thread = None
        if self._webcam_cap:
            self._webcam_cap.release()
            self._webcam_cap = None

    def _webcam_loop(self):
        while self._webcam_running and self._webcam_cap is not None:
            ok, frame = self._webcam_cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            self.push_frame(frame)

    # ------------------------------------------------------------
    #  LOOP DE INFERENCIA
    # ------------------------------------------------------------

    def _inference_loop(self):
        last_time = time.time()
        frame_count = 0

        while self._running:
            try:
                frame = self._frame_queue.get(timeout=0.5)
            except Empty:
                continue

            self._frame_height, self._frame_width = frame.shape[:2]

            detections = []
            annotated = frame

            try:
                results = self._model.predict(
                    frame, conf=self._conf_threshold, verbose=False
                )
            except Exception as exc:
                self._last_error = f"Error en inferencia YOLO: {exc}"
                results = []

            if results:
                r = results[0]
                names = r.names if hasattr(r, "names") else {}
                boxes = getattr(r, "boxes", None)
                annotated = frame.copy()
                if boxes is not None and len(boxes) > 0:
                    xyxy = boxes.xyxy.cpu().numpy()
                    confs = boxes.conf.cpu().numpy()
                    clss = boxes.cls.cpu().numpy().astype(int)
                    for (x1, y1, x2, y2), conf, cls_id in zip(xyxy, confs, clss):
                        raw_label = names.get(int(cls_id), str(int(cls_id)))
                        label_es = COCO_LABELS_ES.get(raw_label, raw_label)
                        detections.append(self._build_detection(
                            label_es, float(conf),
                            float(x1), float(y1), float(x2), float(y2)
                        ))
                        xi1, yi1, xi2, yi2 = int(x1), int(y1), int(x2), int(y2)
                        color = (0, 200, 0)
                        cv2.rectangle(annotated, (xi1, yi1), (xi2, yi2), color, 2)
                        text = f"{label_es} {conf:.2f}"
                        (tw, th), _ = cv2.getTextSize(
                            text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                        )
                        cv2.rectangle(
                            annotated, (xi1, max(0, yi1 - th - 6)),
                            (xi1 + tw + 4, yi1), color, -1
                        )
                        cv2.putText(
                            annotated, text, (xi1 + 2, yi1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA
                        )

            ok_jpg, jpg = cv2.imencode(
                ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
            )
            if not ok_jpg:
                continue

            frame_count += 1
            now = time.time()
            if now - last_time >= 1.0:
                self._fps = frame_count / (now - last_time)
                frame_count = 0
                last_time = now

            with self._lock:
                self._latest_frame_jpeg = jpg.tobytes()
                self._latest_detections = detections

    def _build_detection(self, label, conf, x1, y1, x2, y2) -> Dict:
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        w = max(1.0, x2 - x1)
        h = max(1.0, y2 - y1)
        fw = max(1, self._frame_width)
        fh = max(1, self._frame_height)
        norm_cx = cx / fw
        norm_cy = cy / fh
        area_ratio = (w * h) / (fw * fh)

        direction = "left" if norm_cx < 0.35 else ("right" if norm_cx > 0.65 else "center")
        if area_ratio > 0.25:
            distance_hint = "near"
        elif area_ratio > 0.08:
            distance_hint = "mid"
        else:
            distance_hint = "far"

        return {
            "label": label,
            "confidence": round(conf, 3),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "center": [round(cx, 1), round(cy, 1)],
            "norm_center": [round(norm_cx, 3), round(norm_cy, 3)],
            "area_ratio": round(area_ratio, 4),
            "direction": direction,
            "distance_hint": distance_hint,
        }

    # ------------------------------------------------------------
    #  GETTERS / STREAM
    # ------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def status(self) -> Dict:
        stale_for = time.time() - self._last_frame_ts if self._last_frame_ts else None
        return {
            "running": self._running,
            "source": self._source,
            "camera_index": self._camera_index,
            "model": self._model_name,
            "conf": self._conf_threshold,
            "fps": round(self._fps, 1),
            "frame_size": [self._frame_width, self._frame_height],
            "ultralytics_installed": YOLO is not None,
            "webcam_running": self._webcam_running,
            "seconds_since_last_frame": round(stale_for, 2) if stale_for is not None else None,
            "last_error": self._last_error,
        }

    def get_detections(self) -> List[Dict]:
        with self._lock:
            return list(self._latest_detections)

    def mjpeg_generator(self):
        boundary = b"--frame"
        waited = 0.0
        while self._running:
            with self._lock:
                frame = self._latest_frame_jpeg
            if frame is None:
                time.sleep(0.05)
                waited += 0.05
                if waited > 10.0:
                    break
                continue
            waited = 0.0
            yield (boundary + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                   + frame + b"\r\n")
            time.sleep(0.04)


detector = YoloDetector()
