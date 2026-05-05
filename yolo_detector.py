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

from core.perception.faces import face_recognition_service

_ULTRALYTICS_IMPORT_ERROR: Optional[str] = None
try:
    from ultralytics import YOLO
except Exception as exc:
    YOLO = None
    _ULTRALYTICS_IMPORT_ERROR = str(exc)

_TORCH_IMPORT_ERROR: Optional[str] = None
try:
    import torch
except Exception as exc:
    torch = None
    _TORCH_IMPORT_ERROR = str(exc)


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
        # Secundario opcional: solo se activa bajo demanda porque duplica
        # inferencia cuando el primario es un modelo pose.
        self._secondary_model = None
        self._secondary_name = None
        self._loaded_model_name = None
        self._with_secondary_objects = False
        self._secondary_every_n = 10
        self._secondary_frame_count = 0
        self._source = self.SOURCE_ROBOT
        self._camera_index = 0
        self._conf_threshold = 0.35
        self._imgsz = 320
        self._target_fps = 6.0
        self._device = "cpu"
        self._half = False
        self._last_inference_ms = 0.0
        self._jpeg_quality = 70
        self._max_det = 25
        self._adaptive_load_shed = True
        self._load_shed_threshold_ms = 220.0
        self._shed_face_frames = 0
        self._shed_qr_frames = 0
        self._shed_secondary_frames = 0

        self._frame_queue: Queue = Queue(maxsize=1)
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

        # QR detector paralelo al pipeline YOLO. Corre cada N frames para
        # no robar CPU a la inferencia principal. Si encuentra un QR, emite
        # una notificacion via callback registrado desde app.py.
        self._qr_detector = cv2.QRCodeDetector()
        self._qr_every_n = 6       # QR throttled y reducido para no robar CPU
        self._qr_scan_width = 480
        self._qr_frame_count = 0
        self._last_qr_text: Optional[str] = None
        self._last_qr_ts: float = 0.0
        self._last_qr_corners: Optional[list] = None
        self._qr_callback = None   # Optional[Callable[[str, list], None]]

        # Face recognition pipeline. It reuses the same camera frames and a
        # local dataset in data/faces/<person>/.
        self._face_every_n = 6
        self._face_scan_width = 512
        self._face_frame_count = 0
        self._last_face_detections: List[Dict] = []
        self._last_face_ts = 0.0
        self._last_face_count = 0
        self._face_cache_ttl_s = 1.2
        self._face_recognition_enabled = False
        self._person_attributes_enabled = True
        self._face_min_size_base = 32
        self._face_min_neighbors = 5

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
              model_name: str = "yolov8n.pt", conf: float = 0.35,
              imgsz: int = 320, with_objects: bool = False,
              target_fps: float = 6.0) -> Dict:
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
        self._imgsz = self._normalize_imgsz(imgsz)
        self._with_secondary_objects = bool(with_objects)
        self._target_fps = self._normalize_target_fps(target_fps)
        self._device, self._half = self._select_device()

        # Load/reload the local face database once before the first frames.
        # If there are no photos yet, this is a cheap no-op.
        try:
            face_recognition_service.reload_if_needed()
        except Exception as exc:
            print(f"[FACE] No se pudo cargar base facial: {exc}")

        if self._model is None or self._loaded_model_name != self._model_name:
            try:
                self._model = YOLO(self._model_name)
                self._loaded_model_name = self._model_name
                self._optimize_model(self._model, self._device)
            except Exception as exc:
                self._last_error = f"No se pudo cargar modelo YOLO: {exc}"
                return {"ok": False, "message": self._last_error}

        # Si el modelo primario es pose, el modelo secundario general queda
        # disponible solo bajo demanda porque duplica el costo de inferencia.
        self._secondary_model = None
        self._secondary_name = None
        self._secondary_frame_count = 0
        if self._with_secondary_objects and "pose" in self._model_name.lower():
            try:
                self._secondary_name = "yolov8n.pt"
                self._secondary_model = YOLO(self._secondary_name)
                self._optimize_model(self._secondary_model, self._device)
            except Exception as exc:
                # No es fatal — seguimos con sólo el modelo pose.
                print(f"[YOLO] No se pudo cargar modelo secundario: {exc}")
                self._secondary_model = None
                self._secondary_name = None

        self._running = True
        self._last_error = None
        self._face_frame_count = self._face_every_n - 1
        self._last_face_detections = []
        self._last_face_ts = 0.0
        self._last_face_count = 0
        self._drain_queue()

        self._inference_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._inference_thread.start()

        if self._source == self.SOURCE_WEBCAM:
            ok, msg = self._start_webcam_capture(self._camera_index)
            if not ok:
                self._running = False
                self._inference_thread = None
                return {"ok": False, "message": msg}
            return {"ok": True, "message": f"YOLO iniciado (webcam {self._camera_index}, modelo {self._model_name}, imgsz {self._imgsz}, {self._target_fps:g} FPS objetivo)"}

        return {"ok": True, "message": f"YOLO iniciado (robot, modelo {self._model_name}, imgsz {self._imgsz}, {self._target_fps:g} FPS objetivo)"}

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
        self._last_face_detections = []
        self._last_face_count = 0

        # Liberamos referencias al modelo secundario también
        self._secondary_model = None
        self._secondary_name = None
        self._secondary_frame_count = 0

        return {"ok": True, "message": "YOLO detenido"}

    def _drain_queue(self):
        while True:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                break

    def _get_latest_frame(self, timeout=0.5):
        frame = self._frame_queue.get(timeout=timeout)
        while True:
            try:
                frame = self._frame_queue.get_nowait()
            except Empty:
                return frame

    @staticmethod
    def _normalize_imgsz(value) -> int:
        try:
            imgsz = int(value)
        except Exception:
            imgsz = 320
        return max(256, min(960, imgsz))

    @staticmethod
    def _normalize_target_fps(value) -> float:
        try:
            fps = float(value)
        except Exception:
            fps = 6.0
        return max(1.0, min(30.0, fps))

    @staticmethod
    def _select_device() -> tuple[str, bool]:
        if torch is not None:
            try:
                if torch.cuda.is_available():
                    return "cuda", True
            except Exception:
                pass
        return "cpu", False

    @staticmethod
    def _optimize_model(model, device: str = "cpu") -> None:
        try:
            model.to(device)
        except Exception:
            pass
        try:
            model.fuse()
        except Exception:
            pass

    @staticmethod
    def _resize_for_scan(frame, max_width: int):
        if frame is None:
            return frame, 1.0
        h, w = frame.shape[:2]
        if not max_width or w <= max_width:
            return frame, 1.0
        scale = max_width / float(w)
        resized = cv2.resize(
            frame,
            (max_width, max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, 1.0 / scale

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

    def _run_prediction(self, model, frame, context: str = "YOLO"):
        if model is None:
            return []
        try:
            return model.predict(
                frame,
                conf=self._conf_threshold,
                imgsz=self._imgsz,
                max_det=self._max_det,
                device=self._device,
                half=self._half,
                verbose=False,
            )
        except Exception as exc:
            self._last_error = f"Error en inferencia {context}: {exc}"
            return []

    def _extract_pose_keypoints(self, result):
        kpts_obj = getattr(result, "keypoints", None)
        if kpts_obj is None or getattr(kpts_obj, "xy", None) is None:
            return None, None
        try:
            kpts_xy = kpts_obj.xy.cpu().numpy()
            kpts_conf = (
                kpts_obj.conf.cpu().numpy()
                if getattr(kpts_obj, "conf", None) is not None
                else None
            )
            return kpts_xy, kpts_conf
        except Exception:
            return None, None

    def _collect_primary_detections(self, frame, results):
        detections: List[Dict] = []
        annotated = frame
        if not results:
            return annotated, detections

        r = results[0]
        names = r.names if hasattr(r, "names") else {}
        boxes = getattr(r, "boxes", None)
        kpts_xy, kpts_conf = self._extract_pose_keypoints(r)

        annotated = frame.copy()
        if boxes is None or len(boxes) <= 0:
            return annotated, detections

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)

        for idx, ((x1, y1, x2, y2), conf, cls_id) in enumerate(zip(xyxy, confs, clss)):
            raw_label = names.get(int(cls_id), str(int(cls_id)))
            label_es = COCO_LABELS_ES.get(raw_label, raw_label)
            det = self._build_detection(
                label_es, float(conf),
                float(x1), float(y1), float(x2), float(y2)
            )

            gesture = None
            if kpts_xy is not None and idx < len(kpts_xy) and raw_label == "person":
                person_kpts = kpts_xy[idx]
                kp_conf = kpts_conf[idx] if kpts_conf is not None else None
                gesture = self._infer_gesture(person_kpts, kp_conf)
                det["keypoints"] = [
                    [round(float(px), 1), round(float(py), 1)]
                    for px, py in person_kpts
                ]
                det["gesture"] = gesture
                self._draw_skeleton(annotated, person_kpts, kp_conf)

            detections.append(det)

            xi1, yi1, xi2, yi2 = int(x1), int(y1), int(x2), int(y2)
            color = (0, 200, 0)
            cv2.rectangle(annotated, (xi1, yi1), (xi2, yi2), color, 2)
            text = f"{label_es} {conf:.2f}"
            if gesture:
                text += f" [{gesture}]"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(
                annotated, (xi1, max(0, yi1 - th - 6)),
                (xi1 + tw + 4, yi1), color, -1
            )
            cv2.putText(
                annotated, text, (xi1 + 2, yi1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA
            )

        return annotated, detections

    def _run_secondary_if_needed(self, frame, overloaded):
        if self._secondary_model is None:
            return []
        if overloaded:
            self._shed_secondary_frames += 1
            return []
        self._secondary_frame_count += 1
        if self._secondary_frame_count < self._secondary_every_n:
            return []
        self._secondary_frame_count = 0
        return self._run_prediction(self._secondary_model, frame, context="YOLO secundario")

    def _collect_secondary_detections(self, annotated, secondary_results, detections: List[Dict]) -> None:
        if not secondary_results:
            return
        sr = secondary_results[0]
        s_names = sr.names if hasattr(sr, "names") else {}
        s_boxes = getattr(sr, "boxes", None)
        if s_boxes is None or len(s_boxes) <= 0:
            return

        s_xyxy = s_boxes.xyxy.cpu().numpy()
        s_confs = s_boxes.conf.cpu().numpy()
        s_clss = s_boxes.cls.cpu().numpy().astype(int)
        for (sx1, sy1, sx2, sy2), s_conf, s_cls in zip(s_xyxy, s_confs, s_clss):
            s_raw = s_names.get(int(s_cls), str(int(s_cls)))
            if s_raw == "person":
                continue
            s_label_es = COCO_LABELS_ES.get(s_raw, s_raw)
            det = self._build_detection(
                s_label_es, float(s_conf),
                float(sx1), float(sy1), float(sx2), float(sy2)
            )
            detections.append(det)

            xi1, yi1, xi2, yi2 = int(sx1), int(sy1), int(sx2), int(sy2)
            color = (200, 130, 0)
            cv2.rectangle(annotated, (xi1, yi1), (xi2, yi2), color, 2)
            text = f"{s_label_es} {s_conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(
                annotated, (xi1, max(0, yi1 - th - 6)),
                (xi1 + tw + 4, yi1), color, -1
            )
            cv2.putText(
                annotated, text, (xi1 + 2, yi1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
            )

    def _process_qr(self, frame, annotated, overloaded) -> None:
        if overloaded:
            self._shed_qr_frames += 1
            return

        self._qr_frame_count += 1
        if self._qr_frame_count < self._qr_every_n:
            return
        self._qr_frame_count = 0

        try:
            qr_frame, qr_scale = self._resize_for_scan(frame, self._qr_scan_width)
            qr_text, qr_corners, _ = self._qr_detector.detectAndDecode(qr_frame)
            if qr_corners is not None and qr_scale != 1.0:
                qr_corners = qr_corners * qr_scale
        except Exception:
            qr_text, qr_corners = "", None

        if not qr_text:
            return

        self._last_qr_text = qr_text
        self._last_qr_ts = time.time()
        corners_list = None
        if qr_corners is not None:
            try:
                corners_list = qr_corners.reshape(-1, 2).astype(int).tolist()
            except Exception:
                corners_list = None
        self._last_qr_corners = corners_list

        if corners_list and annotated is not frame:
            pts = [(int(p[0]), int(p[1])) for p in corners_list]
            for i in range(len(pts)):
                cv2.line(annotated, pts[i], pts[(i + 1) % len(pts)], (0, 220, 255), 3)
            cv2.putText(
                annotated, f"QR: {qr_text[:24]}",
                (pts[0][0], max(20, pts[0][1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2, cv2.LINE_AA
            )

        if callable(self._qr_callback):
            try:
                self._qr_callback(qr_text, corners_list)
            except Exception:
                pass

    def _inference_loop(self):
        last_time = time.time()
        frame_count = 0

        while self._running:
            iteration_started = time.time()
            try:
                frame = self._get_latest_frame(timeout=0.5)
            except Empty:
                continue

            self._frame_height, self._frame_width = frame.shape[:2]

            results = self._run_prediction(self._model, frame, context="YOLO")
            overloaded = (
                self._adaptive_load_shed
                and self._last_inference_ms > self._load_shed_threshold_ms
            )
            secondary_results = self._run_secondary_if_needed(frame, overloaded)

            annotated, detections = self._collect_primary_detections(frame, results)
            self._collect_secondary_detections(annotated, secondary_results, detections)

            # --- Interacciones persona ↔ objeto ---
            # Si la muñeca de una persona está cerca/dentro del bbox de un
            # objeto, marcamos la persona con un campo "holding" para que el
            # frontend pueda decir "persona con celular", etc.
            face_detections = self._detect_faces_for_frame(frame)
            if face_detections:
                detections.extend(face_detections)
                self._draw_face_detections(annotated, face_detections)
            elif overloaded:
                self._shed_face_frames += 1

            self._add_person_object_interactions(detections)

            self._process_qr(frame, annotated, overloaded)

            ok_jpg, jpg = cv2.imencode(
                ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
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

            elapsed = time.time() - iteration_started
            self._last_inference_ms = elapsed * 1000.0
            target_interval = 1.0 / max(1.0, self._target_fps)
            if elapsed < target_interval:
                time.sleep(target_interval - elapsed)

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
    #  ROSTROS / IDENTIDAD LOCAL
    # ------------------------------------------------------------

    def _face_min_size_for_frame(self, frame) -> tuple[int, int]:
        try:
            h, w = frame.shape[:2]
            dynamic = int(min(h, w) * 0.06)
        except Exception:
            dynamic = self._face_min_size_base
        px = max(28, min(56, max(self._face_min_size_base, dynamic)))
        return (px, px)

    def _detect_faces_for_frame(self, frame) -> List[Dict]:
        """Detecta rostros y reconoce personas registradas localmente.

        Corre cada N frames y reutiliza resultados recientes para no tumbar
        FPS ni hacer parpadear la lista de detecciones.
        """
        attributes_available = False
        if self._person_attributes_enabled:
            try:
                attributes_available = face_recognition_service.attributes_available()
            except Exception:
                attributes_available = False
        # Siempre detectamos rostros para mantener la caja "rostro" visible
        # en pantalla. El reconocimiento por nombre solo corre cuando
        # _face_recognition_enabled esta activo.

        self._face_frame_count += 1
        now = time.time()
        should_run = self._face_frame_count >= self._face_every_n
        if not should_run and self._last_face_detections and now - self._last_face_ts < self._face_cache_ttl_s:
            return [dict(d) for d in self._last_face_detections]
        if not should_run:
            return []

        self._face_frame_count = 0
        raw_faces = []
        try:
            face_frame, face_scale = self._resize_for_scan(frame, self._face_scan_width)
            min_size = self._face_min_size_for_frame(face_frame)
            raw_faces = face_recognition_service.detect_and_recognize(
                face_frame,
                max_faces=4,
                min_size=min_size,
                scale_factor=1.14,
                min_neighbors=self._face_min_neighbors,
                include_profiles=False,
                max_detectors=1,
                with_recognition=self._face_recognition_enabled,
                with_attributes=self._person_attributes_enabled,
            )
        except Exception as exc:
            self._last_error = f"Error en reconocimiento facial: {exc}"
            face_scale = 1.0

        detections: List[Dict] = []
        for face in raw_faces:
            x1, y1, x2, y2 = face.get("bbox", [0, 0, 0, 0])
            if face_scale != 1.0:
                x1, y1, x2, y2 = (
                    float(x1) * face_scale,
                    float(y1) * face_scale,
                    float(x2) * face_scale,
                    float(y2) * face_scale,
                )
            det = self._build_detection(
                "rostro",
                1.0,
                float(x1), float(y1), float(x2), float(y2),
            )
            det["kind"] = "face"
            det["known"] = bool(face.get("known"))
            det["person_name"] = face.get("person_name")
            det["recognition_confidence"] = face.get("recognition_confidence", 0.0)
            det["recognition_score"] = face.get("recognition_score")
            det["recognition_distance"] = face.get("recognition_distance")
            det["recognition_backend"] = face.get("recognition_backend")
            det["apparent_gender"] = face.get("apparent_gender")
            det["apparent_gender_confidence"] = face.get("apparent_gender_confidence")
            det["age_group"] = face.get("age_group")
            det["age_bucket"] = face.get("age_bucket")
            det["age_confidence"] = face.get("age_confidence")
            det["person_category"] = face.get("person_category")
            detections.append(det)

        self._last_face_detections = [dict(d) for d in detections]
        self._last_face_ts = now
        self._last_face_count = len(detections)
        return detections

    def _draw_face_detections(self, img, detections: List[Dict]) -> None:
        try:
            for d in detections:
                x1, y1, x2, y2 = [int(v) for v in d.get("bbox", [0, 0, 0, 0])]
                known = bool(d.get("known"))
                name = d.get("person_name")
                color = (0, 190, 255) if known else (180, 180, 180)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                text = name if known and name else "rostro"
                category = d.get("person_category")
                if not known and category:
                    text = str(category)
                if known:
                    rc = d.get("recognition_confidence")
                    if isinstance(rc, (int, float)):
                        text = f"{text} {rc:.2f}"
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(
                    img, (x1, max(0, y1 - th - 6)),
                    (x1 + tw + 4, y1), color, -1
                )
                cv2.putText(
                    img, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 0) if known else (255, 255, 255),
                    1, cv2.LINE_AA
                )
        except Exception:
            pass

    # ------------------------------------------------------------
    #  POSE / GESTOS  (sólo activo con modelo *-pose.pt)
    # ------------------------------------------------------------
    #
    # Indices COCO-17 de keypoints:
    #   0=nose  1=L_eye  2=R_eye  3=L_ear  4=R_ear
    #   5=L_shoulder  6=R_shoulder  7=L_elbow  8=R_elbow
    #   9=L_wrist     10=R_wrist
    #   11=L_hip      12=R_hip
    #   13=L_knee     14=R_knee     15=L_ankle  16=R_ankle
    # Las imágenes están "flipped": L del esqueleto = derecha de la pantalla.
    #
    # Las heurísticas se basan en altura (Y) relativa de muñecas vs hombros
    # y nariz, más distancia horizontal entre muñecas y caderas.
    # Confianza mínima por keypoint para considerarlo válido.

    _SKELETON_PAIRS = [
        (5, 6),   (5, 7), (7, 9),
        (6, 8),   (8, 10),
        (5, 11),  (6, 12), (11, 12),
        (11, 13), (13, 15),
        (12, 14), (14, 16),
        (0, 1),   (0, 2), (1, 3), (2, 4),
    ]

    def _infer_gesture(self, kp_xy, kp_conf=None, min_conf=0.4):
        """A partir de 17 keypoints (xy) infiere un gesto humano.
        Devuelve un string corto en español o None si no hay nada claro.

        Heurísticas con tolerancias en píxeles. Si la imagen es muy chica,
        algunos thresholds no triggerean — preferible que devuelva None
        a etiquetar mal."""
        if kp_xy is None or len(kp_xy) < 17:
            return None

        def ok(i):
            if kp_conf is None: return True
            return float(kp_conf[i]) >= min_conf

        def y(i): return float(kp_xy[i][1])
        def x(i): return float(kp_xy[i][0])
        def pt(i): return (x(i), y(i)) if ok(i) else None

        nose = pt(0)
        l_sh, r_sh = pt(5), pt(6)
        l_el, r_el = pt(7), pt(8)
        l_wr, r_wr = pt(9), pt(10)
        l_hip, r_hip = pt(11), pt(12)
        l_kn, r_kn = pt(13), pt(14)

        # Distancia helper
        def dist(p1, p2):
            if p1 is None or p2 is None: return None
            return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2) ** 0.5

        # Hombros: ancho corporal de referencia para escalar thresholds.
        shoulder_w = dist(l_sh, r_sh) or 80
        # Threshold "cerca" relativo al ancho de hombros
        near_t = max(20, shoulder_w * 0.35)

        # ───── Manos juntas (rezando, agradeciendo) ─────
        if l_wr and r_wr and dist(l_wr, r_wr) < near_t:
            # ¿al frente del torso? (entre hombros y caderas)
            if (l_sh and r_sh and l_hip and r_hip):
                hand_avg_y = (l_wr[1] + r_wr[1]) / 2
                sh_y = (l_sh[1] + r_sh[1]) / 2
                hip_y = (l_hip[1] + r_hip[1]) / 2
                if sh_y - 20 < hand_avg_y < hip_y + 20:
                    return "manos_juntas"

        # ───── T-pose (brazos extendidos en cruz) ─────
        if (l_sh and l_el and l_wr and r_sh and r_el and r_wr):
            # ambos codos casi a la altura de los hombros, muñecas alejadas
            if (abs(l_el[1] - l_sh[1]) < shoulder_w * 0.25 and
                abs(r_el[1] - r_sh[1]) < shoulder_w * 0.25 and
                abs(l_wr[1] - l_sh[1]) < shoulder_w * 0.30 and
                abs(r_wr[1] - r_sh[1]) < shoulder_w * 0.30 and
                abs(l_wr[0] - l_sh[0]) > shoulder_w * 0.6 and
                abs(r_wr[0] - r_sh[0]) > shoulder_w * 0.6):
                return "t_pose"

        # ───── Brazos cruzados ─────
        # muñeca izquierda cerca del hombro derecho y viceversa
        if (l_wr and r_sh and r_wr and l_sh and
            dist(l_wr, r_sh) < near_t * 1.3 and
            dist(r_wr, l_sh) < near_t * 1.3):
            return "brazos_cruzados"

        # ───── Puños arriba (celebración / "salta") ─────
        # Prioriza este gesto sobre "ambas_manos_arriba" para que al levantar
        # ambos brazos se dispare el salto aunque los codos esten doblados O
        # extendidos (en camara real varia mucho por perspectiva).
        if (l_wr and r_wr and nose and l_sh and r_sh and
            l_wr[1] < nose[1] and r_wr[1] < nose[1]):
            return "puños_arriba"

        # ───── Ambas manos arriba (sobre la cabeza) ─────
        if (l_wr and r_wr and nose and
            l_wr[1] < nose[1] and r_wr[1] < nose[1]):
            return "ambas_manos_arriba"

        # ───── Brazos arriba (encima de los hombros) ─────
        if (l_wr and r_wr and l_sh and r_sh and
            l_wr[1] < l_sh[1] - 20 and r_wr[1] < r_sh[1] - 20):
            return "brazos_arriba"

        # ───── Mano arriba (una sola, saludo) ─────
        if l_wr and l_sh and l_wr[1] < l_sh[1] - 30:
            return "mano_arriba"
        if r_wr and r_sh and r_wr[1] < r_sh[1] - 30:
            return "mano_arriba"

        # ───── Manos en la cadera (akimbo) → sentarse ─────
        # Ambas muñecas cerca de su cadera del mismo lado, en altura y
        # en horizontal, con codo doblado (codo más arriba que la muñeca).
        # Tolerancia generosa porque la mano apoyada no siempre cae justo
        # sobre el hueso de la cadera.
        if (l_wr and r_wr and l_hip and r_hip and l_el and r_el):
            l_close = (
                abs(l_wr[0] - l_hip[0]) < shoulder_w * 0.6
                and abs(l_wr[1] - l_hip[1]) < shoulder_w * 0.5
                and l_el[1] < l_wr[1]
            )
            r_close = (
                abs(r_wr[0] - r_hip[0]) < shoulder_w * 0.6
                and abs(r_wr[1] - r_hip[1]) < shoulder_w * 0.5
                and r_el[1] < r_wr[1]
            )
            if l_close and r_close:
                return "manos_en_cadera"

        # ───── Mano abajo (señalando al suelo) ─────
        # Muñeca claramente más baja que la cadera + codo por debajo del
        # hombro. Para evitar falsos positivos por brazos en reposo, pedimos
        # que la muñeca esté MUY abajo (más de medio shoulder_w bajo cadera).
        if (l_wr and l_hip and l_el and l_sh and
            l_wr[1] > l_hip[1] + shoulder_w * 0.5 and l_el[1] > l_sh[1]):
            return "mano_abajo"
        if (r_wr and r_hip and r_el and r_sh and
            r_wr[1] > r_hip[1] + shoulder_w * 0.5 and r_el[1] > r_sh[1]):
            return "mano_abajo"

        # ───── Señalando (brazo extendido lateral) ─────
        if r_wr and r_sh and abs(r_wr[0] - r_sh[0]) > shoulder_w * 1.2 and abs(r_wr[1] - r_sh[1]) < shoulder_w * 0.5:
            return "señalando_derecha"
        if l_wr and l_sh and abs(l_wr[0] - l_sh[0]) > shoulder_w * 1.2 and abs(l_wr[1] - l_sh[1]) < shoulder_w * 0.5:
            return "señalando_izquierda"

        # ───── Agachado / cuclillas ─────
        if (l_hip and r_hip and l_kn and r_kn and l_sh and r_sh):
            sh_y = (l_sh[1] + r_sh[1]) / 2
            hip_y = (l_hip[1] + r_hip[1]) / 2
            kn_y = (l_kn[1] + r_kn[1]) / 2
            torso = hip_y - sh_y
            if torso > 0 and (kn_y - hip_y) < torso * 0.3:
                # rodillas muy cerca de las caderas verticalmente → agachado
                return "agachado"

        # ───── Sentado ─────
        if l_hip and l_kn and r_hip and r_kn:
            knee_avg = (l_kn[1] + r_kn[1]) / 2
            hip_avg  = (l_hip[1] + r_hip[1]) / 2
            if knee_avg < hip_avg + 30:
                return "sentado"

        return None

    def _add_person_object_interactions(self, detections):
        """Post-procesa detecciones para añadir el campo 'holding' a las
        personas cuya muñeca esté cerca/dentro del bbox de un objeto.
        Útil para que el frontend diga "persona con celular", etc."""
        try:
            persons = [d for d in detections if d.get("label") == "persona" and d.get("keypoints")]
            objects = [
                d for d in detections
                if d.get("label") not in ("persona", "rostro")
            ]
            if not persons or not objects:
                return

            for p in persons:
                kpts = p.get("keypoints") or []
                if len(kpts) < 17:
                    continue
                # Muñecas: índices 9 (izq) y 10 (der)
                wrists = []
                for idx in (9, 10):
                    try:
                        wx, wy = kpts[idx]
                        if wx > 0 and wy > 0:
                            wrists.append((wx, wy))
                    except Exception:
                        continue
                if not wrists:
                    continue

                holding = []
                for o in objects:
                    bbox = o.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    x1, y1, x2, y2 = bbox
                    # Margen de 20 px alrededor del bbox para "cerca"
                    pad = 20
                    for (wx, wy) in wrists:
                        if x1 - pad <= wx <= x2 + pad and y1 - pad <= wy <= y2 + pad:
                            holding.append(o.get("label"))
                            break
                if holding:
                    # Quitar duplicados conservando orden
                    seen = set()
                    p["holding"] = [h for h in holding if not (h in seen or seen.add(h))]
        except Exception:
            pass

    def _draw_skeleton(self, img, kp_xy, kp_conf=None, min_conf=0.4):
        """Dibuja líneas entre los keypoints (skeleton COCO-17)."""
        try:
            for a, b in self._SKELETON_PAIRS:
                if kp_conf is not None:
                    if kp_conf[a] < min_conf or kp_conf[b] < min_conf:
                        continue
                p1 = (int(kp_xy[a][0]), int(kp_xy[a][1]))
                p2 = (int(kp_xy[b][0]), int(kp_xy[b][1]))
                if p1 == (0, 0) or p2 == (0, 0):
                    continue
                cv2.line(img, p1, p2, (0, 255, 200), 2, cv2.LINE_AA)
            for i, (x, yk) in enumerate(kp_xy):
                if kp_conf is not None and kp_conf[i] < min_conf:
                    continue
                xi, yi = int(x), int(yk)
                if (xi, yi) == (0, 0):
                    continue
                cv2.circle(img, (xi, yi), 3, (0, 255, 255), -1, cv2.LINE_AA)
        except Exception:
            pass

    # ------------------------------------------------------------
    #  GETTERS / STREAM
    # ------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def set_face_recognition_enabled(self, enabled: bool) -> None:
        self._face_recognition_enabled = bool(enabled)
        if not enabled:
            self._last_face_detections = []
            self._last_face_count = 0

    def status(self) -> Dict:
        stale_for = time.time() - self._last_frame_ts if self._last_frame_ts else None
        return {
            "running": self._running,
            "source": self._source,
            "camera_index": self._camera_index,
            "model": self._model_name,
            "conf": self._conf_threshold,
            "imgsz": self._imgsz,
            "target_fps": self._target_fps,
            "with_objects": self._with_secondary_objects,
            "secondary_model": self._secondary_name,
            "fps": round(self._fps, 1),
            "inference_ms": round(self._last_inference_ms, 1),
            "device": self._device,
            "half": self._half,
            "torch_installed": torch is not None,
            "torch_error": _TORCH_IMPORT_ERROR,
            "frame_size": [self._frame_width, self._frame_height],
            "ultralytics_installed": YOLO is not None,
            "webcam_running": self._webcam_running,
            "seconds_since_last_frame": round(stale_for, 2) if stale_for is not None else None,
            "last_error": self._last_error,
            "faces": face_recognition_service.status(),
            "face_pipeline": {
                "face_recognition_enabled": self._face_recognition_enabled,
                "scan_width": self._face_scan_width,
                "every_n": self._face_every_n,
                "cache_ttl_s": self._face_cache_ttl_s,
                "min_size_base": self._face_min_size_base,
                "min_neighbors": self._face_min_neighbors,
                "attributes_enabled": self._person_attributes_enabled,
                "attributes_available": (
                    face_recognition_service.attributes_available()
                    if self._person_attributes_enabled else False
                ),
                "last_count": self._last_face_count,
                "last_age_s": round(time.time() - self._last_face_ts, 2)
                              if self._last_face_ts else None,
            },
            "adaptive_load_shed": {
                "enabled": self._adaptive_load_shed,
                "threshold_ms": self._load_shed_threshold_ms,
                "shed_face_frames": self._shed_face_frames,
                "shed_qr_frames": self._shed_qr_frames,
                "shed_secondary_frames": self._shed_secondary_frames,
            },
        }

    @staticmethod
    def _compact_detection(det: Dict) -> Dict:
        # El frontend no consume keypoints crudos (solo gesto/holding),
        # así que los omitimos para bajar payload de red.
        pruned: Dict = {}
        for k, v in det.items():
            if k == "keypoints":
                continue
            pruned[k] = v
        return pruned

    def get_detections(self, compact: bool = False, limit: Optional[int] = None) -> List[Dict]:
        with self._lock:
            dets = list(self._latest_detections)
        if compact:
            dets = [self._compact_detection(d) for d in dets]
        if isinstance(limit, int) and limit > 0:
            dets = dets[:limit]
        return dets

    def get_current_frame_jpeg(self) -> Optional[bytes]:
        """Devuelve los bytes JPEG del último frame anotado, o None si
        aún no hay frames. Lo usa el agente IA para enviárselo a Gemini
        como contexto visual (modo multimodal)."""
        with self._lock:
            return self._latest_frame_jpeg

    # ------------------------------------------------------------
    #  API DE QR (pipeline paralelo a YOLO)
    # ------------------------------------------------------------

    def set_qr_callback(self, cb):
        """Registra un callable(qr_text:str, corners:list) que se invoca
        cada vez que se detecta un QR en el frame actual. app.py usa esto
        para emitir `qr_detected` via Socket.IO con la pose del lidar."""
        self._qr_callback = cb

    def get_last_qr(self) -> Dict:
        """Ultimo QR detectado y su antiguedad en segundos. None si nunca."""
        if not self._last_qr_text:
            return {"text": None, "age_s": None, "corners": None}
        return {
            "text": self._last_qr_text,
            "age_s": round(time.time() - self._last_qr_ts, 2),
            "corners": self._last_qr_corners,
        }

    def get_last_qr_tracking(self) -> Dict:
        """Info derivada del ultimo QR, util para control de seguimiento.
        Devuelve:
          text      : texto del QR
          age_s     : antiguedad en segundos (None si nunca se detecto)
          norm_cx   : centro X normalizado en el frame [0=izq, 1=der]
          norm_cy   : centro Y normalizado [0=arriba, 1=abajo]
          area_ratio: fraccion del frame ocupada (proxy inverso de distancia)
        """
        if not self._last_qr_text or not self._last_qr_corners:
            return {"text": None, "age_s": None,
                    "norm_cx": None, "norm_cy": None, "area_ratio": None}
        fw = max(1, self._frame_width)
        fh = max(1, self._frame_height)
        xs = [p[0] for p in self._last_qr_corners]
        ys = [p[1] for p in self._last_qr_corners]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        # Area del poligono (shoelace), absoluta.
        n = len(self._last_qr_corners)
        area = 0.0
        for i in range(n):
            x1, y1 = self._last_qr_corners[i]
            x2, y2 = self._last_qr_corners[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        area = abs(area) * 0.5
        return {
            "text": self._last_qr_text,
            "age_s": round(time.time() - self._last_qr_ts, 3),
            "norm_cx": round(cx / fw, 4),
            "norm_cy": round(cy / fh, 4),
            "area_ratio": round(area / (fw * fh), 5),
        }

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
            time.sleep(0.08)


detector = YoloDetector()
