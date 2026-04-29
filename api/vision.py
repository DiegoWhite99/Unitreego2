"""Endpoints de YOLO (visión) y QR."""

from __future__ import annotations

import time

from flask import Blueprint, Response, jsonify, request

from yolo_detector import detector as yolo_detector

from core.logging_utils import emit_log
from core.state import qr_state, robot_state


bp = Blueprint("vision", __name__)


# ────────────────────────────────────────────────────────────────────
# YOLO
# ────────────────────────────────────────────────────────────────────
@bp.route("/api/yolo/status", methods=["GET"])
def api_yolo_status():
    return jsonify(yolo_detector.status())


@bp.route("/api/yolo/start", methods=["POST"])
def api_yolo_start():
    """Inicia inferencia YOLO. Source default: 'robot' (camara del Go2).

    Cuerpo: { "source": "robot"|"webcam", "camera_index": N, "model": ..., "conf": ... }"""
    data = request.get_json() or {}
    source = data.get("source", "robot")
    camera_index = int(data.get("camera_index", 0))
    model_name = data.get("model", "yolov8n.pt")
    conf = float(data.get("conf", 0.35))

    if source == "robot" and not robot_state["connected"]:
        msg = "Conecta primero el robot para usar su camara."
        emit_log("error", msg)
        return jsonify({"status": "error", "message": msg}), 400

    result = yolo_detector.start(
        source=source,
        camera_index=camera_index,
        model_name=model_name,
        conf=conf,
    )
    if result.get("ok"):
        emit_log("success", result.get("message", "YOLO iniciado"))
        return jsonify({"status": "ok", "message": result["message"]})
    emit_log("error", result.get("message", "Error YOLO"))
    return jsonify({"status": "error", "message": result.get("message")}), 500


@bp.route("/api/yolo/stop", methods=["POST"])
def api_yolo_stop():
    result = yolo_detector.stop()
    emit_log("info", result.get("message", "YOLO detenido"))
    return jsonify({"status": "ok", "message": result.get("message")})


@bp.route("/api/yolo/detections", methods=["GET"])
def api_yolo_detections():
    return jsonify({
        "status":     "ok",
        "running":    yolo_detector.is_running(),
        "detections": yolo_detector.get_detections(),
    })


@bp.route("/api/yolo/stream")
def api_yolo_stream():
    """Stream MJPEG con frames anotados en tiempo real."""
    if not yolo_detector.is_running():
        return jsonify({"status": "error",
                        "message": "YOLO no esta corriendo"}), 409
    return Response(
        yolo_detector.mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ────────────────────────────────────────────────────────────────────
# QR
# ────────────────────────────────────────────────────────────────────
@bp.route("/api/qr/last", methods=["GET"])
def api_qr_last():
    """Ultimo QR detectado por YOLO con su pose asociada."""
    return jsonify({
        "status":  "ok",
        "text":    qr_state["last_text"],
        "last_ts": qr_state["last_ts"],
        "age_s":   round(time.time() - qr_state["last_ts"], 2)
                   if qr_state["last_ts"] else None,
        "pose":    qr_state["last_pose"],
    })


@bp.route("/api/qr/image")
def api_qr_image():
    """Genera una imagen PNG del QR pedido via ?text=..."""
    try:
        import qrcode
        from io import BytesIO
    except ImportError:
        return jsonify({
            "status": "error",
            "message": "Falta la dependencia 'qrcode'. Instala: pip install qrcode[pil]",
        }), 500
    text = request.args.get("text", "DAIVER_WP").strip() or "DAIVER_WP"
    qr = qrcode.QRCode(
        version=None, box_size=10, border=3,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")
