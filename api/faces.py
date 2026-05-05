"""Endpoints for local face registration and greeting state."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from core.agents.face_greetings import face_greeting_reactor
from core.perception.faces import (
    FACE_IMAGES_DIR,
    SUPPORTED_IMAGE_EXTS,
    face_recognition_service,
)


bp = Blueprint("faces", __name__)


@bp.route("/api/faces/status", methods=["GET"])
def api_faces_status():
    return jsonify({
        "status": "ok",
        "faces": face_recognition_service.status(),
        "greetings": face_greeting_reactor.state(),
    })


@bp.route("/api/faces/reload", methods=["POST"])
def api_faces_reload():
    result = face_recognition_service.reload()
    return jsonify({"status": "ok", "faces": result})


@bp.route("/api/faces/upload", methods=["POST"])
def api_faces_upload():
    """Upload one or more photos for a person.

    Multipart form fields:
      - person: display/folder name
      - photos: one or more image files
    """
    person_raw = (request.form.get("person") or "").strip()
    person_slug = secure_filename(person_raw).strip("._-")
    if not person_slug:
        return jsonify({
            "status": "error",
            "message": "Envia el campo 'person' con el nombre de la persona.",
        }), 400

    files = request.files.getlist("photos") or request.files.getlist("photo")
    if not files:
        return jsonify({
            "status": "error",
            "message": "Adjunta al menos una imagen en el campo 'photos'.",
        }), 400

    root = FACE_IMAGES_DIR.resolve()
    target_dir = (FACE_IMAGES_DIR / person_slug).resolve()
    if root != target_dir and root not in target_dir.parents:
        return jsonify({"status": "error", "message": "Ruta invalida."}), 400

    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    rejected: list[str] = []

    for file in files:
        original_name = file.filename or "foto.jpg"
        safe_name = secure_filename(original_name) or "foto.jpg"
        ext = Path(safe_name).suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTS:
            rejected.append(original_name)
            continue
        dest = _next_available_path(target_dir / safe_name)
        file.save(dest)
        saved.append(str(dest.relative_to(FACE_IMAGES_DIR)))

    result = face_recognition_service.reload()
    return jsonify({
        "status": "ok",
        "person": person_slug,
        "saved": saved,
        "rejected": rejected,
        "faces": result,
    })


@bp.route("/api/faces/greetings/state", methods=["GET"])
def api_face_greetings_state():
    return jsonify({"status": "ok", **face_greeting_reactor.state()})


@bp.route("/api/faces/greetings/start", methods=["POST"])
def api_face_greetings_start():
    face_greeting_reactor.start()
    return jsonify({"status": "ok", **face_greeting_reactor.state()})


@bp.route("/api/faces/greetings/stop", methods=["POST"])
def api_face_greetings_stop():
    face_greeting_reactor.stop()
    return jsonify({"status": "ok", **face_greeting_reactor.state()})


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
