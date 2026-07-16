"""Rutas que sirven HTML/CSS/JS estaticos del frontend.

Mantenemos los aliases que ya estaban (`/controlRemoto`, `/controlRemoto.html`,
`/auto-ruta`, etc.) para no romper bookmarks y el frontend existente.
"""

from __future__ import annotations

import os

from flask import Blueprint, send_from_directory


bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return send_from_directory("src", "index.html")


@bp.route("/user-end")
@bp.route("/user_end.hmtl")  # typo conservado por compatibilidad con bookmarks
def user_end():
    return send_from_directory("src", "user_end.html")


@bp.route("/control-remoto")
@bp.route("/controlRemoto")
@bp.route("/controlRemoto.html")
def control_remoto():
    return send_from_directory("src", "controlRemoto.html")


@bp.route("/agente")
@bp.route("/agente.html")
def page_agente():
    return send_from_directory("src", "agente.html")


@bp.route("/help")
@bp.route("/help.html")
def help_page():
    return send_from_directory("src", "help.html")


@bp.route("/rutaguiada")
def ruta_guiada():
    return send_from_directory("src", "rutaGuiada.html")


@bp.route("/autoroute")
@bp.route("/auto-ruta")
@bp.route("/autoroute.html")
def autoroute_page():
    return send_from_directory("src", "autoroute.html")


@bp.route("/save_img")
@bp.route("/save-img")
@bp.route("/save_img.html")
def save_img_page():
    return send_from_directory("src", "save_img.html")


_CONSOLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "console"
)


@bp.route("/console-ia")
@bp.route("/console_IA.html")
def console_ia():
    return send_from_directory(_CONSOLE_DIR, "console_IA.html")


@bp.route("/console-ia/<path:filename>")
def console_assets(filename: str):
    return send_from_directory(_CONSOLE_DIR, filename)


@bp.route("/img/<path:filename>")
def serve_img(filename):
    return send_from_directory("src/img", filename)


@bp.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory("src/css", filename)


@bp.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory("src/js", filename)


@bp.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory("src/assets", filename)


@bp.route("/informes/")
@bp.route("/informes/<path:filename>")
def informes_page(filename: str | None = None):
    """Sirve los informes técnicos. Sin filename: lista los disponibles."""
    informes_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "informes"
    )
    if filename:
        return send_from_directory("informes", filename)
    try:
        files = sorted(
            [f for f in os.listdir(informes_dir) if f.endswith(".html")],
            reverse=True,
        )
    except FileNotFoundError:
        files = []
    items = "".join(
        f'<li><a href="/informes/{f}">{f}</a></li>' for f in files
    ) or "<li><em>No hay informes disponibles.</em></li>"
    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        "<title>Informes técnicos</title>"
        "<style>body{font-family:Calibri,Segoe UI,Arial,sans-serif;"
        "max-width:720px;margin:3rem auto;padding:0 1rem;color:#222;}"
        "h1{color:#1a3a6b;border-bottom:3px double #1a3a6b;padding-bottom:.5rem;}"
        "ul{list-style:none;padding:0;}li{padding:.6rem 0;border-bottom:1px solid #eee;}"
        "a{color:#1a3a6b;text-decoration:none;font-weight:600;}"
        "a:hover{text-decoration:underline;}"
        ".back{display:inline-block;margin-bottom:1rem;color:#666;}</style>"
        "</head><body>"
        '<a class="back" href="/">← Volver al sistema</a>'
        "<h1>Informes técnicos</h1>"
        f"<ul>{items}</ul></body></html>"
    )
