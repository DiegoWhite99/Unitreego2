"""Face detection and local recognition for Diver.

The dataset lives in ``data/faces/<person name>/``. Each folder can contain
several photos of the same person. At runtime we turn those photos into a
small local face database and compare camera faces against it.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACE_IMAGES_DIR = PROJECT_ROOT / "data" / "faces"
PERSON_ATTRIBUTE_MODELS_DIR = PROJECT_ROOT / "models"
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_DNN_MEAN_VALUES = (78.4263377603, 87.7689143744, 114.895847746)


def _display_name_from_folder(folder_name: str) -> str:
    return folder_name.replace("_", " ").replace("-", " ").strip() or folder_name


class FaceAttributeEstimator:
    """Optional OpenCV DNN age/gender estimator.

    It is intentionally lazy: if the model files are not present under
    models/, the live pipeline continues with no extra cost.
    """

    AGE_BUCKETS = ("0-2", "4-6", "8-12", "15-20", "25-32", "38-43", "48-53", "60+")
    GENDER_LABELS = ("hombre", "mujer")

    def __init__(self, model_dir: Path = PERSON_ATTRIBUTE_MODELS_DIR) -> None:
        self.model_dir = model_dir
        self._lock = threading.RLock()
        self._loaded_once = False
        self._age_net = None
        self._gender_net = None
        self._last_error: str | None = None
        self._age_files: tuple[str, str] | None = None
        self._gender_files: tuple[str, str] | None = None

    def status(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            return {
                "enabled": True,
                "available": bool(self._age_net or self._gender_net),
                "age_available": self._age_net is not None,
                "gender_available": self._gender_net is not None,
                "model_dir": str(self.model_dir),
                "age_files": self._age_files,
                "gender_files": self._gender_files,
                "last_error": self._last_error,
            }

    def available(self) -> bool:
        self._ensure_loaded()
        with self._lock:
            return bool(self._age_net or self._gender_net)

    def estimate(self, face_bgr) -> dict[str, Any]:
        self._ensure_loaded()
        if face_bgr is None:
            return {}
        h, w = face_bgr.shape[:2]
        if h < 24 or w < 24:
            return {}

        with self._lock:
            if self._age_net is None and self._gender_net is None:
                return {}

            try:
                blob = cv2.dnn.blobFromImage(
                    face_bgr,
                    1.0,
                    (227, 227),
                    _DNN_MEAN_VALUES,
                    swapRB=False,
                    crop=False,
                )
            except Exception as exc:
                self._last_error = f"No se pudo preparar rostro para atributos: {exc}"
                return {}

            attrs: dict[str, Any] = {}
            if self._gender_net is not None:
                try:
                    self._gender_net.setInput(blob)
                    preds = self._gender_net.forward()[0]
                    idx = int(np.argmax(preds))
                    if 0 <= idx < len(self.GENDER_LABELS):
                        attrs["apparent_gender"] = self.GENDER_LABELS[idx]
                        attrs["apparent_gender_confidence"] = round(float(preds[idx]), 3)
                except Exception as exc:
                    self._last_error = f"Error estimando genero aparente: {exc}"

            if self._age_net is not None:
                try:
                    self._age_net.setInput(blob)
                    preds = self._age_net.forward()[0]
                    idx = int(np.argmax(preds))
                    if 0 <= idx < len(self.AGE_BUCKETS):
                        bucket = self.AGE_BUCKETS[idx]
                        attrs["age_bucket"] = bucket
                        attrs["age_group"] = self._bucket_to_group(bucket)
                        attrs["age_confidence"] = round(float(preds[idx]), 3)
                except Exception as exc:
                    self._last_error = f"Error estimando edad aparente: {exc}"

            group = attrs.get("age_group")
            gender = attrs.get("apparent_gender")
            if group == "nino":
                attrs["person_category"] = "nino"
            elif gender in {"hombre", "mujer"}:
                attrs["person_category"] = gender
            elif group:
                attrs["person_category"] = group
            return attrs

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded_once:
                return
            self._loaded_once = True
            self.model_dir.mkdir(parents=True, exist_ok=True)

            age_proto = self._first_existing(
                "age_deploy.prototxt",
                "deploy_age.prototxt",
                "age.prototxt",
            )
            age_weights = self._first_existing(
                "age_net.caffemodel",
                "age.caffemodel",
            )
            gender_proto = self._first_existing(
                "gender_deploy.prototxt",
                "deploy_gender.prototxt",
                "gender.prototxt",
            )
            gender_weights = self._first_existing(
                "gender_net.caffemodel",
                "gender.caffemodel",
            )

            errors: list[str] = []
            if age_proto and age_weights:
                try:
                    self._age_net = cv2.dnn.readNetFromCaffe(str(age_proto), str(age_weights))
                    self._age_files = (age_proto.name, age_weights.name)
                except Exception as exc:
                    errors.append(f"edad: {exc}")
            if gender_proto and gender_weights:
                try:
                    self._gender_net = cv2.dnn.readNetFromCaffe(str(gender_proto), str(gender_weights))
                    self._gender_files = (gender_proto.name, gender_weights.name)
                except Exception as exc:
                    errors.append(f"genero: {exc}")

            if errors:
                self._last_error = "; ".join(errors)
            elif self._age_net is None and self._gender_net is None:
                self._last_error = (
                    "Modelos de atributos no encontrados. Coloca age/gender "
                    "deploy.prototxt y .caffemodel en models/ para activar."
                )

    def _first_existing(self, *names: str) -> Path | None:
        for name in names:
            path = self.model_dir / name
            if path.exists():
                return path
        return None

    @staticmethod
    def _bucket_to_group(bucket: str) -> str:
        if bucket in {"0-2", "4-6", "8-12"}:
            return "nino"
        if bucket == "15-20":
            return "joven"
        if bucket in {"25-32", "38-43", "48-53"}:
            return "adulto"
        return "adulto_mayor"


class FaceRecognitionService:
    """Small local face recognizer.

    Preferred backend: OpenCV LBPH (requires opencv-contrib-python).
    Fallback backend: local LBP histograms implemented with numpy. The fallback
    keeps the app useful with the normal opencv-python package.
    """

    def __init__(self, data_dir: Path = FACE_IMAGES_DIR) -> None:
        self.data_dir = data_dir
        self.face_size = (112, 112)
        # Umbrales mas conservadores para reducir falsos positivos.
        self.lbph_threshold = 105.0
        self.lbph_min_confidence = 0.33
        self.lbp_threshold = 1.25
        # El mejor match debe ser claramente mejor que el segundo.
        self.lbp_margin_ratio = 0.95
        self._lock = threading.RLock()
        self._last_error: str | None = None
        self._cascades = self._load_cascades()
        self._cascade = self._cascades[0][1] if self._cascades else None
        self._recognizer = None
        self._backend = "none"
        self._trained = False
        self._loaded_once = False
        self._sample_count = 0
        self._skipped_images: list[str] = []
        self._skipped_reasons: dict[str, str] = {}
        self._dropped_outlier_samples = 0
        self._label_to_name: dict[int, str] = {}
        self._prototypes: dict[int, np.ndarray] = {}
        self._gallery_samples: list[tuple[int, np.ndarray]] = []
        self._attribute_estimator = FaceAttributeEstimator()
        # Calidad minima para que una foto sirva en entrenamiento.
        self._dataset_min_face_px = 72
        self._dataset_min_face_area_ratio = 0.012
        # Para evitar identificar por nombre con recortes demasiado pequeños.
        self._runtime_min_recognition_px = 52

    def _load_cascades(self):
        cascade_dir = Path(cv2.data.haarcascades)
        names = [
            "haarcascade_frontalface_default.xml",
            "haarcascade_frontalface_alt2.xml",
            "haarcascade_profileface.xml",
        ]
        cascades = []
        missing = []
        for name in names:
            cascade_path = cascade_dir / name
            cascade = cv2.CascadeClassifier(str(cascade_path))
            if cascade.empty():
                missing.append(str(cascade_path))
                continue
            cascades.append((name, cascade))
        if not cascades:
            self._last_error = "No se pudo cargar cascade de rostros: " + "; ".join(missing)
        return cascades

    def reload_if_needed(self) -> dict[str, Any]:
        with self._lock:
            if self._loaded_once:
                return self.status()
        return self.reload()

    def reload(self) -> dict[str, Any]:
        """Rebuilds the in-memory face database from data/faces."""
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._recognizer = None
            self._backend = "none"
            self._trained = False
            self._last_error = None
            self._sample_count = 0
            self._skipped_images = []
            self._skipped_reasons = {}
            self._dropped_outlier_samples = 0
            self._label_to_name = {}
            self._prototypes = {}
            self._gallery_samples = []
            self._loaded_once = True

            if not self._cascades:
                self._last_error = "Detector de rostros no disponible"
                return self.status()

            samples: list[np.ndarray] = []
            labels: list[int] = []

            person_dirs = sorted(p for p in self.data_dir.iterdir() if p.is_dir())
            for label_id, person_dir in enumerate(person_dirs):
                person_name = _display_name_from_folder(person_dir.name)
                self._label_to_name[label_id] = person_name

                images = sorted(
                    p for p in person_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS
                )
                for image_path in images:
                    img = self._read_bgr_image(image_path)
                    if img is None:
                        rel = str(image_path.relative_to(PROJECT_ROOT))
                        self._skipped_images.append(rel)
                        self._skipped_reasons[rel] = "no se pudo leer"
                        continue
                    face, meta = self._largest_face_crop_with_meta(img)
                    if face is None or meta is None:
                        rel = str(image_path.relative_to(PROJECT_ROOT))
                        self._skipped_images.append(rel)
                        self._skipped_reasons[rel] = "sin rostro util"
                        continue
                    fw = int(meta.get("w", 0))
                    fh = int(meta.get("h", 0))
                    area_ratio = float(meta.get("area_ratio", 0.0))
                    faces_found = int(meta.get("faces_found", 0))
                    if faces_found != 1:
                        rel = str(image_path.relative_to(PROJECT_ROOT))
                        self._skipped_images.append(rel)
                        self._skipped_reasons[rel] = (
                            f"imagen ambigua: se detectaron {faces_found} rostros"
                        )
                        continue
                    if (
                        min(fw, fh) < self._dataset_min_face_px
                        or area_ratio < self._dataset_min_face_area_ratio
                    ):
                        rel = str(image_path.relative_to(PROJECT_ROOT))
                        self._skipped_images.append(rel)
                        self._skipped_reasons[rel] = (
                            f"rostro muy pequeno ({fw}x{fh}, area={area_ratio:.4f})"
                        )
                        continue
                    samples.append(face)
                    labels.append(label_id)

            self._sample_count = len(samples)
            if not samples or not self._label_to_name:
                return self.status()

            labels_np = np.asarray(labels, dtype=np.int32)
            face_module = getattr(cv2, "face", None)
            create_lbph = getattr(face_module, "LBPHFaceRecognizer_create", None) if face_module else None

            if callable(create_lbph):
                try:
                    recognizer = create_lbph(radius=1, neighbors=8, grid_x=8, grid_y=8)
                    recognizer.train(samples, labels_np)
                    self._recognizer = recognizer
                    self._backend = "lbph"
                    self._trained = True
                    return self.status()
                except Exception as exc:
                    self._last_error = f"LBPH fallo, usando fallback: {exc}"

            grouped: dict[int, list[np.ndarray]] = {}
            for sample, label_id in zip(samples, labels):
                grouped.setdefault(label_id, []).append(self._lbp_histogram(sample))

            grouped = self._drop_lbp_outliers(grouped)
            self._gallery_samples = [
                (int(label_id), vec)
                for label_id, vecs in grouped.items()
                for vec in vecs
            ]
            self._prototypes = {
                label_id: self._normalize_hist(np.mean(vecs, axis=0))
                for label_id, vecs in grouped.items()
                if vecs
            }
            if self._prototypes:
                self._backend = "lbp"
                self._trained = True
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "trained": self._trained,
                "backend": self._backend,
                "dataset_dir": str(self.data_dir),
                "known_people": list(self._label_to_name.values()),
                "people_count": len(self._label_to_name),
                "sample_count": self._sample_count,
                "skipped_images": list(self._skipped_images),
                "skipped_reasons": dict(self._skipped_reasons),
                "dropped_outlier_samples": self._dropped_outlier_samples,
                "last_error": self._last_error,
                "lbph_threshold": self.lbph_threshold,
                "lbph_min_confidence": self.lbph_min_confidence,
                "lbp_threshold": self.lbp_threshold,
                "lbp_margin_ratio": self.lbp_margin_ratio,
                "dataset_min_face_px": self._dataset_min_face_px,
                "dataset_min_face_area_ratio": self._dataset_min_face_area_ratio,
                "runtime_min_recognition_px": self._runtime_min_recognition_px,
                "detectors": [name for name, _ in self._cascades],
                "attributes": self._attribute_estimator.status(),
            }

    def detect_and_recognize(
        self,
        frame_bgr,
        max_faces: int = 6,
        min_size: tuple[int, int] = (42, 42),
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        include_profiles: bool = True,
        max_detectors: int | None = None,
        with_recognition: bool = True,
        with_attributes: bool = False,
    ) -> list[dict[str, Any]]:
        if frame_bgr is None:
            return []
        with self._lock:
            if not self._cascades:
                return []
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = self._detect_faces(
                gray,
                scale_factor=scale_factor,
                min_neighbors=min_neighbors,
                min_size=min_size,
                include_profiles=include_profiles,
                max_detectors=max_detectors,
            )
            faces = sorted(faces, key=lambda r: int(r[2]) * int(r[3]), reverse=True)
            detections: list[dict[str, Any]] = []
            for (x, y, w, h) in faces[:max_faces]:
                crop = self._preprocess_gray(gray[y:y + h, x:x + w])
                can_recognize = with_recognition and min(int(w), int(h)) >= self._runtime_min_recognition_px
                identity = (
                    self._recognize_face(crop)
                    if can_recognize
                    else {"known": False, "person_name": None, "confidence": 0.0}
                )
                det = {
                    "bbox": [float(x), float(y), float(x + w), float(y + h)],
                    "known": bool(identity.get("known")),
                    "person_name": identity.get("person_name"),
                    "recognition_confidence": identity.get("confidence", 0.0),
                    "recognition_score": identity.get("score"),
                    "recognition_distance": identity.get("distance"),
                    "recognition_backend": self._backend,
                }
                if with_recognition and not can_recognize:
                    det["recognition_blocked_reason"] = (
                        f"face_too_small_{int(w)}x{int(h)}"
                    )
                if with_attributes:
                    face_bgr = self._crop_with_padding(frame_bgr, x, y, w, h, pad_ratio=0.15)
                    det.update(self._attribute_estimator.estimate(face_bgr))
                detections.append(det)
            return detections

    def _recognize_face(self, face_gray: np.ndarray) -> dict[str, Any]:
        if face_gray is None or not self._trained:
            return {"known": False, "person_name": None, "confidence": 0.0}

        lbp_meta = self._lbp_identity(face_gray)

        if self._backend == "lbph" and self._recognizer is not None:
            try:
                label_id, distance = self._recognizer.predict(face_gray)
                name = self._label_to_name.get(int(label_id))

                # Regla de aceptacion: LBPH + chequeo de ambiguedad por LBP.
                lbph_conf = max(0.0, min(1.0, 1.0 - (float(distance) / self.lbph_threshold)))
                lbph_ok = bool(
                    name
                    and distance <= self.lbph_threshold
                    and lbph_conf >= self.lbph_min_confidence
                )

                same_label = True
                lbp_ok = True
                if lbp_meta:
                    lbp_best_label = lbp_meta.get("best_label")
                    lbp_best_dist = float(lbp_meta.get("best_distance", float("inf")))
                    lbp_second_dist = float(lbp_meta.get("second_distance", float("inf")))
                    same_label = lbp_best_label == int(label_id)
                    lbp_ok = lbp_best_dist <= self.lbp_threshold
                    if np.isfinite(lbp_second_dist) and lbp_second_dist > 1e-9:
                        lbp_ok = lbp_ok and (lbp_best_dist / lbp_second_dist) <= self.lbp_margin_ratio

                known = bool(lbph_ok and same_label and lbp_ok)
                confidence = lbph_conf if known else 0.0
                return {
                    "known": known,
                    "person_name": name if known else None,
                    "confidence": round(confidence, 3),
                    "distance": round(float(distance), 3),
                    "score": round(confidence, 3),
                }
            except Exception as exc:
                self._last_error = f"Error reconociendo rostro: {exc}"
                return {"known": False, "person_name": None, "confidence": 0.0}

        if self._backend == "lbp" and self._gallery_samples:
            knn = self._lbp_knn_identity(face_gray, top_k=5)
            best_label = knn.get("best_label") if knn else None
            best_distance = float(knn.get("best_distance", float("inf"))) if knn else float("inf")
            second_distance = float(knn.get("second_distance", float("inf"))) if knn else float("inf")
            vote_ratio = float(knn.get("vote_ratio", 0.0)) if knn else 0.0
            name = self._label_to_name.get(int(best_label)) if best_label is not None else None
            known = bool(name and best_distance <= self.lbp_threshold)
            if known and np.isfinite(second_distance) and second_distance > 1e-9:
                known = (best_distance / second_distance) <= self.lbp_margin_ratio
            if known:
                known = vote_ratio >= 1.08
            confidence = 0.0
            if known:
                confidence = 1.0 - (best_distance / self.lbp_threshold)
                confidence = max(0.0, min(1.0, confidence))
            return {
                "known": known,
                "person_name": name if known else None,
                "confidence": round(confidence, 3),
                "distance": round(best_distance, 3),
                "score": round(1.0 - best_distance, 3),
            }

        return {"known": False, "person_name": None, "confidence": 0.0}

    def _lbp_identity(self, face_gray: np.ndarray) -> dict[str, Any] | None:
        if face_gray is None or not self._prototypes:
            return None
        hist = self._lbp_histogram(face_gray)
        ranked: list[tuple[int, float]] = []
        for label_id, proto in self._prototypes.items():
            distance = self._chi_square_distance(hist, proto)
            ranked.append((int(label_id), float(distance)))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[1])
        best_label, best_distance = ranked[0]
        second_distance = ranked[1][1] if len(ranked) > 1 else float("inf")
        return {
            "best_label": best_label,
            "best_distance": best_distance,
            "second_distance": second_distance,
        }

    def _lbp_knn_identity(self, face_gray: np.ndarray, top_k: int = 5) -> dict[str, Any] | None:
        if face_gray is None or not self._gallery_samples:
            return None
        hist = self._lbp_histogram(face_gray)
        ranked: list[tuple[float, int]] = []
        for label_id, proto in self._gallery_samples:
            ranked.append((self._chi_square_distance(hist, proto), int(label_id)))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0])
        k = max(1, min(int(top_k), len(ranked)))
        top = ranked[:k]

        votes: dict[int, float] = {}
        for distance, label_id in top:
            weight = 1.0 / (distance + 1e-9)
            votes[label_id] = votes.get(label_id, 0.0) + weight

        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        best_label, best_vote = sorted_votes[0]
        second_vote = sorted_votes[1][1] if len(sorted_votes) > 1 else 0.0
        best_distance = min(d for d, lid in ranked if lid == best_label)
        second_distance = min(d for d, lid in ranked if lid != best_label) if len(votes) > 1 else float("inf")
        vote_ratio = best_vote / (second_vote + 1e-9) if second_vote > 0 else 999.0
        return {
            "best_label": int(best_label),
            "best_distance": float(best_distance),
            "second_distance": float(second_distance),
            "vote_ratio": float(vote_ratio),
        }

    def attributes_available(self) -> bool:
        return self._attribute_estimator.available()

    def _read_bgr_image(self, path: Path):
        try:
            data = np.fromfile(str(path), dtype=np.uint8)
            if data.size == 0:
                return None
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def _largest_face_crop(self, img_bgr):
        crop, _ = self._largest_face_crop_with_meta(img_bgr)
        return crop

    def _largest_face_crop_with_meta(self, img_bgr):
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        scan_gray, scale_back = self._resize_gray_for_detection(gray, max_side=900)
        faces = self._detect_faces(
            scan_gray,
            scaleFactor=1.08,
            min_neighbors=3,
            min_size=(40, 40),
        )
        if len(faces) == 0:
            return None, None
        x, y, w, h = max(faces, key=lambda r: int(r[2]) * int(r[3]))
        if scale_back != 1.0:
            x = int(x * scale_back)
            y = int(y * scale_back)
            w = int(w * scale_back)
            h = int(h * scale_back)
        ih, iw = gray.shape[:2]
        crop = self._preprocess_gray(gray[y:y + h, x:x + w])
        meta = {
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "area_ratio": float((max(1, w) * max(1, h)) / max(1, iw * ih)),
            "faces_found": int(len(faces)),
        }
        return crop, meta

    @staticmethod
    def _resize_gray_for_detection(gray: np.ndarray, max_side: int = 900):
        h, w = gray.shape[:2]
        longest = max(h, w)
        if longest <= max_side:
            return gray, 1.0
        scale = max_side / float(longest)
        resized = cv2.resize(
            gray,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, 1.0 / scale

    def _detect_faces(
        self,
        gray: np.ndarray,
        scale_factor: float = 1.1,
        min_neighbors: int = 3,
        min_size: tuple[int, int] = (32, 32),
        include_profiles: bool = True,
        max_detectors: int | None = None,
        **legacy_kwargs,
    ) -> list[tuple[int, int, int, int]]:
        if "scaleFactor" in legacy_kwargs:
            scale_factor = legacy_kwargs["scaleFactor"]
        if "minNeighbors" in legacy_kwargs:
            min_neighbors = legacy_kwargs["minNeighbors"]
        if "minSize" in legacy_kwargs:
            min_size = legacy_kwargs["minSize"]
        include_profiles = bool(legacy_kwargs.get("include_profiles", include_profiles))
        max_detectors = legacy_kwargs.get("max_detectors", max_detectors)

        found: list[tuple[int, int, int, int]] = []
        width = int(gray.shape[1])
        used = 0
        for name, cascade in self._cascades:
            is_profile = "profileface" in name
            if is_profile and not include_profiles:
                continue
            if max_detectors is not None and used >= int(max_detectors):
                break
            used += 1
            detections = cascade.detectMultiScale(
                gray,
                scaleFactor=scale_factor,
                minNeighbors=min_neighbors,
                minSize=min_size,
            )
            found.extend((int(x), int(y), int(w), int(h)) for x, y, w, h in detections)

            if is_profile:
                flipped = cv2.flip(gray, 1)
                flipped_detections = cascade.detectMultiScale(
                    flipped,
                    scaleFactor=scale_factor,
                    minNeighbors=min_neighbors,
                    minSize=min_size,
                )
                for x, y, w, h in flipped_detections:
                    found.append((width - int(x) - int(w), int(y), int(w), int(h)))

        return self._dedupe_faces(found)

    @staticmethod
    def _crop_with_padding(img_bgr, x: int, y: int, w: int, h: int, pad_ratio: float = 0.0):
        ih, iw = img_bgr.shape[:2]
        pad_x = int(w * pad_ratio)
        pad_y = int(h * pad_ratio)
        x1 = max(0, int(x) - pad_x)
        y1 = max(0, int(y) - pad_y)
        x2 = min(iw, int(x + w) + pad_x)
        y2 = min(ih, int(y + h) + pad_y)
        if x2 <= x1 or y2 <= y1:
            return None
        return img_bgr[y1:y2, x1:x2]

    @staticmethod
    def _dedupe_faces(faces: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
        ordered = sorted(faces, key=lambda r: int(r[2]) * int(r[3]), reverse=True)
        kept: list[tuple[int, int, int, int]] = []
        for face in ordered:
            if all(FaceRecognitionService._face_iou(face, prev) < 0.35 for prev in kept):
                kept.append(face)
        return kept

    @staticmethod
    def _face_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        union = aw * ah + bw * bh - inter
        return float(inter / union) if union > 0 else 0.0

    def _preprocess_gray(self, face_gray: np.ndarray) -> np.ndarray:
        resized = cv2.resize(face_gray, self.face_size, interpolation=cv2.INTER_AREA)
        return cv2.equalizeHist(resized)

    def _lbp_histogram(self, face_gray: np.ndarray) -> np.ndarray:
        """Builds a grid LBP histogram for a normalized face image."""
        img = face_gray.astype(np.uint8)
        center = img[1:-1, 1:-1]
        code = np.zeros(center.shape, dtype=np.uint8)
        neighbors = [
            img[:-2, :-2], img[:-2, 1:-1], img[:-2, 2:],
            img[1:-1, 2:], img[2:, 2:], img[2:, 1:-1],
            img[2:, :-2], img[1:-1, :-2],
        ]
        for bit, neighbor in enumerate(neighbors):
            code |= ((neighbor >= center).astype(np.uint8) << bit)

        grid_x = 7
        grid_y = 7
        h, w = code.shape
        parts: list[np.ndarray] = []
        for gy in range(grid_y):
            y1 = int(gy * h / grid_y)
            y2 = int((gy + 1) * h / grid_y)
            for gx in range(grid_x):
                x1 = int(gx * w / grid_x)
                x2 = int((gx + 1) * w / grid_x)
                cell = code[y1:y2, x1:x2]
                hist = np.bincount(cell.reshape(-1), minlength=256).astype(np.float32)
                parts.append(self._normalize_hist(hist))
        return self._normalize_hist(np.concatenate(parts))

    def _drop_lbp_outliers(self, grouped: dict[int, list[np.ndarray]]) -> dict[int, list[np.ndarray]]:
        """Descarta muestras ambiguas que contaminan el prototipo de su clase.

        Criterio: una muestra se conserva si esta claramente mas cerca del
        centroide de su propia clase que de cualquier otra clase.
        """
        labels = [k for k, vecs in grouped.items() if vecs]
        if len(labels) < 2:
            return grouped

        centroids = {
            label_id: self._normalize_hist(np.mean(grouped[label_id], axis=0))
            for label_id in labels
        }

        kept: dict[int, list[np.ndarray]] = {label_id: [] for label_id in labels}
        dropped = 0
        margin = 0.98
        for label_id in labels:
            for vec in grouped[label_id]:
                own = self._chi_square_distance(vec, centroids[label_id])
                other = min(
                    self._chi_square_distance(vec, centroids[o])
                    for o in labels if o != label_id
                )
                if own <= (other * margin):
                    kept[label_id].append(vec)
                else:
                    dropped += 1

        # Evita dejar una persona sin muestras; en ese caso recupera originales.
        for label_id in labels:
            if not kept[label_id]:
                kept[label_id] = grouped[label_id]

        self._dropped_outlier_samples = int(dropped)
        return kept

    @staticmethod
    def _normalize_hist(hist: np.ndarray) -> np.ndarray:
        hist = hist.astype(np.float32)
        total = float(np.sum(hist))
        if total <= 1e-9:
            return hist
        return hist / total

    @staticmethod
    def _chi_square_distance(a: np.ndarray, b: np.ndarray) -> float:
        denom = a + b + 1e-9
        return float(0.5 * np.sum(((a - b) ** 2) / denom))


face_recognition_service = FaceRecognitionService()
