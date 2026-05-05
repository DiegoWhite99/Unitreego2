"""Diagnostico de Face ID sobre dataset local.

Objetivo: verificar si el problema viene del recognizer/dataset o del
pipeline en vivo (configuracion/toggle/rendimiento).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from core.perception.faces import (
    FACE_IMAGES_DIR,
    SUPPORTED_IMAGE_EXTS,
    face_recognition_service,
)
from yolo_detector import detector as yolo_detector


def _display_name(folder_name: str) -> str:
    return folder_name.replace("_", " ").replace("-", " ").strip() or folder_name


class TestFaceIdDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status = face_recognition_service.reload()

    def test_face_db_is_trained(self):
        self.assertTrue(self.status.get("trained"), f"Face DB no entrenada: {self.status}")
        self.assertGreaterEqual(int(self.status.get("sample_count", 0)), 3)
        self.assertGreaterEqual(int(self.status.get("people_count", 0)), 1)

    def test_dataset_images_match_expected_person(self):
        """Cada foto util del dataset debe reconocerse como su persona.

        Si hay fotos ambiguas (varios rostros o rostro muy pequeno), el test
        falla explicando exactamente cuales son para depurar dataset.
        """
        invalid_images: list[str] = []
        failures: list[str] = []

        for person_dir in sorted(Path(FACE_IMAGES_DIR).iterdir()):
            if not person_dir.is_dir():
                continue
            expected = _display_name(person_dir.name)

            for img_path in sorted(person_dir.iterdir()):
                if img_path.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                    continue
                img = face_recognition_service._read_bgr_image(img_path)
                if img is None:
                    failures.append(f"{img_path.name}: no se pudo leer")
                    continue

                dets = face_recognition_service.detect_and_recognize(
                    img,
                    max_faces=2,
                    min_size=(32, 32),
                    scale_factor=1.12,
                    min_neighbors=5,
                    include_profiles=False,
                    max_detectors=1,
                    with_recognition=True,
                    with_attributes=False,
                )
                if not dets:
                    failures.append(f"{img_path.name}: no detecta rostro")
                    continue

                h, w = img.shape[:2]
                primary = dets[0]
                x1, y1, x2, y2 = [float(v) for v in primary.get("bbox", [0, 0, 0, 0])]
                fw = max(1.0, x2 - x1)
                fh = max(1.0, y2 - y1)
                area_ratio = (fw * fh) / max(1.0, float(w * h))
                if len(dets) != 1 or area_ratio < 0.012:
                    invalid_images.append(
                        f"{img_path.name}: rostros={len(dets)}, area={area_ratio:.4f}"
                    )
                    continue

                best = max(dets, key=lambda d: float(d.get("recognition_confidence", 0.0)))
                if not best.get("known"):
                    failures.append(f"{img_path.name}: detecta rostro pero queda desconocido")
                    continue
                got = best.get("person_name")
                if got != expected:
                    failures.append(
                        f"{img_path.name}: esperado={expected}, obtenido={got}, "
                        f"conf={best.get('recognition_confidence')}"
                    )

        if invalid_images:
            self.fail(
                "Dataset con fotos ambiguas/no aptas para Face ID:\n- "
                + "\n- ".join(invalid_images)
            )
        if failures:
            self.fail("Fallas Face ID en dataset local:\n- " + "\n- ".join(failures))

    def test_blank_frame_is_not_recognized_as_known_person(self):
        blank = np.zeros((360, 640, 3), dtype=np.uint8)
        dets = face_recognition_service.detect_and_recognize(
            blank,
            max_faces=2,
            with_recognition=True,
            with_attributes=False,
        )
        known_count = sum(1 for d in dets if d.get("known"))
        self.assertEqual(known_count, 0, f"Falsos positivos en frame vacio: {dets}")

    def test_runtime_note_face_id_starts_disabled(self):
        """Documenta el requisito operativo para producción."""
        self.assertFalse(
            yolo_detector._face_recognition_enabled,
            "Face ID deberia iniciar desactivado y encenderse via /api/faces/greetings/start",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
