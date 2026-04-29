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
        # Secundario opcional: cuando el primario es pose, cargamos también
        # yolov8n.pt para detectar las 80 clases COCO en paralelo (más
        # objetos visibles para el agente IA).
        self._secondary_model = None
        self._secondary_name = None
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

        # QR detector paralelo al pipeline YOLO. Corre cada N frames para
        # no robar CPU a la inferencia principal. Si encuentra un QR, emite
        # una notificacion via callback registrado desde app.py.
        self._qr_detector = cv2.QRCodeDetector()
        self._qr_every_n = 4       # corre QR 1 de cada 4 frames (~5 Hz)
        self._qr_frame_count = 0
        self._last_qr_text: Optional[str] = None
        self._last_qr_ts: float = 0.0
        self._last_qr_corners: Optional[list] = None
        self._qr_callback = None   # Optional[Callable[[str, list], None]]

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

        # Si el modelo primario es pose (sólo detecta personas), cargamos
        # un segundo modelo de detección general para no perder los demás
        # objetos COCO. Si el usuario ya pidió un modelo non-pose, no
        # cargamos secundario.
        self._secondary_model = None
        self._secondary_name = None
        if "pose" in self._model_name.lower():
            try:
                self._secondary_name = "yolov8n.pt"
                self._secondary_model = YOLO(self._secondary_name)
            except Exception as exc:
                # No es fatal — seguimos con sólo el modelo pose.
                print(f"[YOLO] No se pudo cargar modelo secundario: {exc}")
                self._secondary_model = None
                self._secondary_name = None

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

        # Liberamos referencias al modelo secundario también
        self._secondary_model = None
        self._secondary_name = None

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

            # Modelo secundario: si lo tenemos, corremos detección general
            # para añadir las 80 clases COCO (mesa, silla, celular, botella…)
            secondary_results = []
            if self._secondary_model is not None:
                try:
                    secondary_results = self._secondary_model.predict(
                        frame, conf=self._conf_threshold, verbose=False
                    )
                except Exception as exc:
                    print(f"[YOLO] secundario falló: {exc}")
                    secondary_results = []

            if results:
                r = results[0]
                names = r.names if hasattr(r, "names") else {}
                boxes = getattr(r, "boxes", None)
                # Si el modelo es pose, también obtenemos keypoints (17 por persona).
                kpts_obj = getattr(r, "keypoints", None)
                kpts_xy = None
                kpts_conf = None
                if kpts_obj is not None and getattr(kpts_obj, "xy", None) is not None:
                    try:
                        kpts_xy = kpts_obj.xy.cpu().numpy()        # (N, 17, 2)
                        kpts_conf = kpts_obj.conf.cpu().numpy() if getattr(kpts_obj, "conf", None) is not None else None
                    except Exception:
                        kpts_xy = None
                annotated = frame.copy()
                if boxes is not None and len(boxes) > 0:
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

                        # Si es modelo pose y la detección es persona, extraer
                        # keypoints + inferir gesto.
                        gesture = None
                        person_kpts = None
                        if kpts_xy is not None and idx < len(kpts_xy) and raw_label == "person":
                            person_kpts = kpts_xy[idx]              # (17, 2)
                            kp_conf = kpts_conf[idx] if kpts_conf is not None else None
                            gesture = self._infer_gesture(person_kpts, kp_conf)
                            det["keypoints"] = [[round(float(x), 1), round(float(y), 1)] for x, y in person_kpts]
                            det["gesture"] = gesture
                            self._draw_skeleton(annotated, person_kpts, kp_conf)

                        detections.append(det)

                        xi1, yi1, xi2, yi2 = int(x1), int(y1), int(x2), int(y2)
                        color = (0, 200, 0)
                        cv2.rectangle(annotated, (xi1, yi1), (xi2, yi2), color, 2)
                        # Texto del label: si hay gesto, lo añadimos
                        text = f"{label_es} {conf:.2f}"
                        if gesture:
                            text += f" [{gesture}]"
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

            # --- Detecciones del modelo secundario (objetos COCO) ---
            # Sumamos sólo clases que NO sean "person" para no duplicar
            # con las detecciones pose del primario.
            if secondary_results:
                sr = secondary_results[0]
                s_names = sr.names if hasattr(sr, "names") else {}
                s_boxes = getattr(sr, "boxes", None)
                if s_boxes is not None and len(s_boxes) > 0:
                    s_xyxy = s_boxes.xyxy.cpu().numpy()
                    s_confs = s_boxes.conf.cpu().numpy()
                    s_clss = s_boxes.cls.cpu().numpy().astype(int)
                    for (sx1, sy1, sx2, sy2), s_conf, s_cls in zip(s_xyxy, s_confs, s_clss):
                        s_raw = s_names.get(int(s_cls), str(int(s_cls)))
                        if s_raw == "person":
                            continue   # ya viene del modelo pose
                        s_label_es = COCO_LABELS_ES.get(s_raw, s_raw)
                        det = self._build_detection(
                            s_label_es, float(s_conf),
                            float(sx1), float(sy1), float(sx2), float(sy2)
                        )
                        detections.append(det)
                        # Dibujamos con color distinto (azul) para diferenciar
                        xi1, yi1, xi2, yi2 = int(sx1), int(sy1), int(sx2), int(sy2)
                        cv2.rectangle(annotated, (xi1, yi1), (xi2, yi2), (200, 130, 0), 2)
                        text = f"{s_label_es} {s_conf:.2f}"
                        (tw, th), _ = cv2.getTextSize(
                            text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                        )
                        cv2.rectangle(
                            annotated, (xi1, max(0, yi1 - th - 6)),
                            (xi1 + tw + 4, yi1), (200, 130, 0), -1
                        )
                        cv2.putText(
                            annotated, text, (xi1 + 2, yi1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
                        )

            # --- Interacciones persona ↔ objeto ---
            # Si la muñeca de una persona está cerca/dentro del bbox de un
            # objeto, marcamos la persona con un campo "holding" para que el
            # frontend pueda decir "persona con celular", etc.
            self._add_person_object_interactions(detections)

            # --- Deteccion de QR en paralelo (throttled) ---
            self._qr_frame_count += 1
            if self._qr_frame_count >= self._qr_every_n:
                self._qr_frame_count = 0
                try:
                    qr_text, qr_corners, _ = self._qr_detector.detectAndDecode(frame)
                except Exception:
                    qr_text, qr_corners = "", None
                if qr_text:
                    self._last_qr_text = qr_text
                    self._last_qr_ts = time.time()
                    corners_list = None
                    if qr_corners is not None:
                        try:
                            corners_list = qr_corners.reshape(-1, 2).astype(int).tolist()
                        except Exception:
                            corners_list = None
                    self._last_qr_corners = corners_list
                    # Dibuja el QR detectado en el frame anotado.
                    if corners_list and annotated is not frame:
                        pts = [(int(p[0]), int(p[1])) for p in corners_list]
                        for i in range(len(pts)):
                            cv2.line(annotated, pts[i], pts[(i + 1) % len(pts)],
                                     (0, 220, 255), 3)
                        cv2.putText(annotated, f"QR: {qr_text[:24]}",
                                    (pts[0][0], max(20, pts[0][1] - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                    (0, 220, 255), 2, cv2.LINE_AA)
                    # Notifica al exterior (app.py registra aqui un emit Socket.IO)
                    if callable(self._qr_callback):
                        try:
                            self._qr_callback(qr_text, corners_list)
                        except Exception:
                            pass

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
            objects = [d for d in detections if d.get("label") != "persona"]
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
            time.sleep(0.04)


detector = YoloDetector()
