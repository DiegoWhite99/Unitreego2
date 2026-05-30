"""Configuracion del agente Diver: detectar proveedor (OpenAI vs Google),
cargar API keys con prioridad env > config/config.py > vacio, y exponer
clientes lazy.

Variables exportadas:
  GEMINI_API_KEY, OPENAI_API_KEY, GEMINI_MODEL
  GENAI_AVAILABLE, OPENAI_AVAILABLE
  openai_client (None si no aplica)
  is_openai_model(name) helper

`genai` y `_OpenAI` se importan condicionalmente para que el backend
arranque aunque falte alguna libreria.
"""

from __future__ import annotations

import os


# ────────────────────────────────────────────────────────────────────
# Imports condicionales
# ────────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    GENAI_AVAILABLE = False

try:
    from openai import OpenAI as _OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    _OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────
# Resolucion de credenciales: env > config/config.py > vacio
# ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "").strip()

try:
    from config import config as _user_cfg
    if not GEMINI_API_KEY:
        GEMINI_API_KEY = getattr(_user_cfg, "GEMINI_API_KEY", "").strip()
    if not OPENAI_API_KEY:
        OPENAI_API_KEY = getattr(_user_cfg, "OPENAI_API_KEY", "").strip()
    if not GEMINI_MODEL:
        GEMINI_MODEL = getattr(_user_cfg, "GEMINI_MODEL", "").strip()
except Exception:
    pass

if not GEMINI_MODEL:
    # Auto-seleccion robusta: prioriza OpenAI si hay key OpenAI y no hay
    # key Gemini; de lo contrario usa Gemini por defecto.
    if OPENAI_API_KEY and not GEMINI_API_KEY:
        GEMINI_MODEL = "gpt-5.3-medium"
    else:
        GEMINI_MODEL = "gemini-2.5-flash"

def is_openai_model(name: str | None) -> bool:
    """True si el ID corresponde a un modelo OpenAI (gpt-*, o1-*, o3-*, o4-*)."""
    n = (name or "").lower()
    return (
        n.startswith("gpt-") or n.startswith("gpt5") or n.startswith("gpt4")
        or n.startswith("o1") or n.startswith("o3") or n.startswith("o4")
    )


def needs_json_tool_protocol(name: str | None) -> bool:
    """True si el modelo NO soporta function calling nativo y debemos
    usar el protocolo JSON inline. Aplica a Gemma 1/2/3.
    Gemma 4+ y todos los Gemini soportan tools nativos -> ruta normal."""
    n = (name or "").lower()
    if n.startswith("gemma"):
        return True
    return False


def _looks_like_gemini_key(k: str | None) -> bool:
    return bool((k or "").strip().startswith("AIza"))


# Corrección automática de proveedor si el modelo elegido no tiene key.
if is_openai_model(GEMINI_MODEL) and (not OPENAI_API_KEY) and GEMINI_API_KEY:
    GEMINI_MODEL = "gemini-2.5-flash"
elif (not is_openai_model(GEMINI_MODEL)) and (not GEMINI_API_KEY) and OPENAI_API_KEY:
    GEMINI_MODEL = "gpt-4.1-mini"
elif (not is_openai_model(GEMINI_MODEL)) and OPENAI_API_KEY and (not _looks_like_gemini_key(GEMINI_API_KEY)):
    # Key Gemini presente pero con formato no valido -> usamos OpenAI.
    GEMINI_MODEL = "gpt-4.1-mini"
elif (not is_openai_model(GEMINI_MODEL)) and OPENAI_API_KEY and (not GENAI_AVAILABLE):
    # Si no está el SDK de Gemini pero sí OpenAI, evitamos dejar el agente caído.
    GEMINI_MODEL = "gpt-4.1-mini"

# Preferencia operativa: DESHABILITADA para usar Gemini 1.5 Flash
# (No forzar OpenAI si tenemos Gemini disponible)
_prefer_openai = os.environ.get("PREFER_OPENAI", "0").strip().lower() in {"1", "true", "yes", "on"}
if _prefer_openai and OPENAI_API_KEY and not is_openai_model(GEMINI_MODEL):
    GEMINI_MODEL = "gpt-4.1-mini"


# ────────────────────────────────────────────────────────────────────
# Cliente OpenAI lazy
# ────────────────────────────────────────────────────────────────────
openai_client = None
if is_openai_model(GEMINI_MODEL):
    if not OPENAI_AVAILABLE:
        print("[AGENTE] Modelo OpenAI elegido pero falta `openai`. "
              "Instala con: pip install openai")
    elif not OPENAI_API_KEY:
        print("[AGENTE] Modelo OpenAI elegido pero falta OPENAI_API_KEY en config.")
    else:
        try:
            openai_client = _OpenAI(api_key=OPENAI_API_KEY)  # type: ignore[misc]
            print(f"[AGENTE] OpenAI listo con modelo: {GEMINI_MODEL}")
        except Exception as _e:
            print(f"[AGENTE] No se pudo configurar OpenAI: {_e}")
elif GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)  # type: ignore[union-attr]
        print(f"[AGENTE] Gemini listo con modelo: {GEMINI_MODEL}")
    except Exception as _e:
        print(f"[AGENTE] No se pudo configurar Gemini: {_e}")
else:
    print("[AGENTE] Falta GEMINI_API_KEY — el agente Diver responderá con un aviso al frontend.")


AGENT_GENERATION_CONFIG = {
    "temperature":       0.7,
    "top_p":             0.9,
    "max_output_tokens": 400,
}
