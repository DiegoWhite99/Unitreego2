"""Limpieza de chain-of-thought y meta-fugas en las respuestas del modelo.

El agente Diver a veces escupe razonamiento interno, ingles, o "Plan: 1. 2.".
Este modulo elimina esa basura y deja solo la respuesta natural.

NO modifiques estos regex sin ejecutar pruebas — son resultado de mucho
tuning empirico contra Gemma 4, GPT-4o y Gemini Flash.
"""

from __future__ import annotations

import json as _json
import re

from .prompts import DIVER_CHAT_FALLBACK


# ────────────────────────────────────────────────────────────────────
# Regex
# ────────────────────────────────────────────────────────────────────
_ACTION_BLOCK_RE = re.compile(r"```action\s*(\{.*?\})\s*```", re.DOTALL)

_PROMPT_LEAK_RE = re.compile(
    r"(natural conversation|1\s*-\s*4 sentences|natural personality|"
    r"loyal,\s*alert,\s*playful|playful but serious|"
    r"reglas duras|hard rules|system instruction|"
    r"responde siempre en espa[nñ]ol|conversa como un agente real)",
    re.IGNORECASE
)

_LEAK_KEYWORDS = re.compile(
    r"^[\s>*\-•\)\(]*[\*\s]*(user\s*('?s)?\s*(asks?|says?|requests?|"
    r"input|message|prompt|question)|user\s*'?s?\s*request|"
    r"mensaje\s*del\s*usuario|petici[oó]n\s*del\s*usuario|"
    r"contexto\s*de\s*(tu\s*)?c[aá]mara|datos\s*(de\s*tu\s*)?c[aá]mara|"
    r"instruction[s]?|behaviou?r|constraints?|examples?|"
    r"tool[s]?\s*:|text\s*:|action\s*:|response\s*:|reasoning\s*:|"
    r"thinking\s*:|step\s*\d+|note\s*:|format\s*:|plan\s*:|"
    r"max\s*(one|1|un)?\s*emoji|natural,?\s*(latin\s*)?(spanish|español)|"
    r"in\s*(spanish|english)|respond\s*(in|with))",
    re.IGNORECASE
)

_META_LEAK = re.compile(
    r"\b("
    r"max\s*(one|1|un)?\s*emoji|"
    r"natural,?\s*(latin\s*)?(spanish|español)|"
    r"spanish\s*\(?\s*latin\s*\)?|latin\s*\(?\s*spanish\s*\)?|"
    r"conversational(,|\s)|"
    r"no\s*(lists?|jargon|technical\s*jargon)|"
    r"short\s*response|brief\s*response|"
    r"\d+\s*[-–]\s*\d+\s*sentences?|"
    r"user\s*('?s)?\s*(request|input|message|prompt|question)\s*:?|"
    r"user\s*asks?|user\s*says?|"
    r"mensaje\s*del\s*usuario\s*:?|petici[oó]n\s*del\s*usuario\s*:?|"
    r"contexto\s*de\s*(tu\s*)?c[aá]mara|datos\s*(de\s*tu\s*)?c[aá]mara|"
    r"plan\s*:\s*\d|"
    r"respond\s*(in|with)\s*(a\s*)?(short|brief|spanish|english)|"
    r"system\s*(instruction|prompt)|"
    r"hard\s*rules?|reglas\s*duras|"
    r"chain\s*of\s*thought|cadena\s*de\s*pensamiento"
    r")\b",
    re.IGNORECASE
)

_REASONING_LEAK = re.compile(
    r"\b("
    r"the user (wants|asks|says|requested)|"
    r"i (should|will|'ll|am going|'m going|need to|have the tools?|have the function)|"
    r"i'll (call|invoke|respond|greet|use)|"
    r"let me (call|invoke|use|think|respond)|"
    r"respond with (a |an )?short|in (spanish|english|both languages)|"
    r"(short|brief|friendly|simple),? (friendly )?confirmation|"
    r"call both tools|both tools|tool[s]? (to|will be|are) (call|use|invoke)|"
    r"greet them|sit down\.|stand up\.|"
    r"el usuario (quiere|pide|pidi[oó]|solicita|solicit[oó])|"
    r"debo (responder|llamar|usar|invocar)|"
    r"responde siempre en espa[nñ]ol|conversa como un agente real|"
    r"voy a (llamar|invocar|usar) (la|las|el|los) (herramienta|función|funciones)|"
    r"tengo (la|las) (herramienta|herramientas|función|funciones)|"
    r"llamar(é|emos|án) (a|al) (saludar|sentarse|mover)|"
    r"primero (llamaré|llamo|invoco|invoc[oó]|saludaré)"
    r")\b",
    re.IGNORECASE
)

_BACKTICK_CODE = re.compile(r"`[a-zA-Z_][\w]*\s*\(?\s*\)?`")

_SPANISH_SIGNAL_RE = re.compile(
    r"[¡¿ñáéíóúü]|"
    r"\b(el|la|los|las|un|una|unos|unas|de|del|al|que|por|para|con|sin|"
    r"ahora|aqui|aquí|alli|allí|listo|lista|voy|vamos|marchando|mirando|"
    r"ver|veo|mira|miro|hay|estoy|estas|estás|esta|está|hola|si|sí|no|"
    r"claro|vale|bien|hecho|hecha|orden|puedo|puede|puedes|espera|"
    r"persona|personas|silla|mesa|robot|camara|cámara|adelante|atras|atrás|"
    r"derecha|izquierda|sentado|sentada|saludo|saludando|quieto|quieta|"
    r"detenido|detenida|atento|atenta|paro|parado|parada)\b",
    re.IGNORECASE
)

_ENGLISH_SIGNAL_RE = re.compile(
    r"\b(i|i'm|ill|i'll|you|your|the|an|is|are|was|were|will|would|"
    r"ready|done|okay|ok|sure|hello|hi|thanks|please|yes|"
    r"see|seeing|look|looking|watch|watching|move|moving|turn|turning|"
    r"sit|sitting|stand|standing|stop|stopping|person|people|chair|table|"
    r"room|there|here|near|front|back|left|right)\b",
    re.IGNORECASE
)


# ────────────────────────────────────────────────────────────────────
# Detectores
# ────────────────────────────────────────────────────────────────────
def _looks_english_only(s: str) -> bool:
    """True si la frase parece predominantemente inglesa."""
    s_lower = s.lower()
    if re.search(r"[¡¿ñáéíóúü]", s_lower):
        return False
    en_words = re.findall(
        r"\b(the|a|an|is|are|was|were|been|being|"
        r"i|i'm|i'll|you|he|she|we|they|"
        r"will|should|would|could|can|may|might|"
        r"have|has|had|having|"
        r"tool|tools|user|wants|going|call|both|short|friendly|"
        r"confirmation|spanish|english|then|sit|down|sitting|standing|"
        r"greet|respond|with|that|this|these|those|"
        r"and|or|but|so|because|while|"
        r"in|on|at|to|of|from|"
        r"chair|chairs|laptop|computer|phone|table|room|office|"
        r"using|holding|wearing|seeing|looking|"
        r"people|person|someone|something|"
        r"me|him|her|them|us|your|my|his|her|their|our|"
        r"what|when|where|how|why|"
        r"yes|not|don't|doesn't|isn't|aren't|"
        r"ready|done|okay|sure|hello|hi|thanks|thank|please|"
        r"stop|stopping|move|moving|turn|turning|look|looking|"
        r"watch|watching|sit|sitting|stand|standing|"
        r"indoor|outdoor|setting|background)\b",
        s_lower)
    es_words = re.findall(
        r"\b(el|la|los|las|que|por|para|con|sin|ahora|aquí|allí|listo|voy|"
        r"estoy|estás|está|estamos|hola|sí|esto|eso|aquel|donde|cuando|"
        r"mientras|también|pero|porque|como|si|no|hay|haya|hace|tiene|"
        r"tengo|tienes|tenemos|tener|veo|miro|escucho|alguien|persona|"
        r"silla|mesa|laptop|teléfono|cuarto|oficina|interior|exterior)\b",
        s_lower)
    return len(en_words) >= 2 and len(es_words) <= 1


def _looks_not_spanish_enough(s: str) -> bool:
    """Detecta respuestas cortas que quedaron en inglés tipo Ready/Done/I see."""
    if not s:
        return False
    plain = re.sub(r"[^\w\sáéíóúüñ¡¿]", " ", s.lower()).strip()
    if not plain:
        return False
    if _SPANISH_SIGNAL_RE.search(plain):
        english_hits = [
            hit for hit in _ENGLISH_SIGNAL_RE.findall(plain)
            if hit.lower() not in {"ok", "okay"}
        ]
        return bool(english_hits)
    return bool(_ENGLISH_SIGNAL_RE.search(plain) or _looks_english_only(plain))


def _is_uppercase_blip(s: str) -> bool:
    """Detecta 'palabras sueltas en MAYÚSCULAS' tipo 'TAZA' o 'NORTE.'"""
    plain = re.sub(r"[\s.!?¡¿,;:()\-–—\"'`*]+", " ", s).strip()
    if not plain:
        return False
    words = plain.split()
    if len(words) > 2:
        return False
    return all(
        w.upper() == w and any(c.isalpha() for c in w) and len(w) >= 2
        for w in words
    )


def _strip_meta_prefix(s: str) -> str:
    """Elimina prefijos de meta-fuga al inicio de una respuesta."""
    if not s:
        return s
    s = re.sub(r"^[\s\)\(\*\-•>#\"']+", "", s).strip()
    s = re.sub(r"^(plan\s*:\s*(\d+\s*\.\s*)+)", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(max\s*(one|1|un)?\s*emoji[\s🐾.,!?]*)+",
               "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(natural,?\s*(latin\s*)?(spanish|español)[\s.,!?]*)",
               "", s, flags=re.IGNORECASE).strip()
    return s


# ────────────────────────────────────────────────────────────────────
# API publica
# ────────────────────────────────────────────────────────────────────
def sanitize_reply(text: str | None, fallback: str | None = None) -> str:
    """Limpia chain-of-thought y meta-fugas. Devuelve solo lo natural."""
    fallback = fallback or DIVER_CHAT_FALLBACK
    if not text:
        return fallback

    text = _strip_meta_prefix(text)
    if not text:
        return fallback

    # Pasada 1: filtrar lineas con bullets/headings de plan
    line_filtered: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _PROMPT_LEAK_RE.search(s):
            continue
        if _LEAK_KEYWORDS.match(s):
            continue
        if _META_LEAK.search(s) and len(s.split()) <= 8:
            continue
        if s.startswith(("**", "##", "###")):
            stripped = re.sub(r"^[*#\s]+", "", s).strip()
            if len(stripped.split()) > 8 or ":" in stripped[:20]:
                continue
            line_filtered.append(stripped)
            continue
        if s.startswith(("* ", "- ", "• ")):
            stripped = re.sub(r"^[\*\-•\s]+", "", s).strip()
            if len(stripped.split()) > 8 or ":" in stripped[:20]:
                continue
            line_filtered.append(stripped)
            continue
        line_filtered.append(s)

    joined = " ".join(line_filtered).strip()
    if not joined:
        return fallback

    # Pasada 2: filtrar oraciones con leaks
    sentences = re.findall(r"[^.!?]+[.!?]?", joined)
    keep: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if _REASONING_LEAK.search(s):  continue
        if _META_LEAK.search(s):       continue
        if _BACKTICK_CODE.search(s):   continue
        if _looks_english_only(s):     continue
        if _is_uppercase_blip(s):      continue
        keep.append(s)

    out = " ".join(keep).strip()

    # Si filtramos demasiado: intentar quedarse con la ultima frase ES.
    if not out:
        m = re.search(r"([¡¿][^.!?]*[.!?]?\s*[A-ZÁÉÍÓÚÑ][^.!?]*[.!?]?\s*)$",
                      joined, re.DOTALL)
        if m:
            out = m.group(1).strip()
        elif re.search(r"[ñáéíóúü]", joined.lower()):
            parts = re.split(r"(?<=[.!?])\s+", joined)
            for p in reversed(parts):
                if re.search(r"[ñáéíóúü]", p.lower()):
                    out = p.strip()
                    break
        else:
            out = fallback

    if _looks_not_spanish_enough(out):
        out = fallback

    if len(out) > 900:
        m = re.search(r"[.!?](?:\s|$)", out[500:])
        if m:
            out = out[:500 + m.end()].strip()
        else:
            out = out[:850].strip() + "…"

    return out or fallback or "🐾"


def reply_fallback(executed: list[dict] | None = None) -> str:
    """Respuesta segura cuando el modelo se va al inglés / responde vacío."""
    executed = executed or []
    for item in executed:
        msg = (item.get("msg") or "").strip()
        if item.get("name") == "mirar_alrededor" and msg:
            return msg
    if executed:
        for item in executed:
            msg = (item.get("msg") or "").strip()
            if not item.get("ok") and msg and not _looks_not_spanish_enough(msg):
                return msg
        if any(not item.get("ok") for item in executed):
            return "No pude hacerlo."
        return "Listo."
    return DIVER_CHAT_FALLBACK


def parse_gemma_actions(text: str) -> tuple[str, list[dict]]:
    """Extrae los bloques ```action {...}``` del texto del modelo."""
    actions: list[dict] = []
    for m in _ACTION_BLOCK_RE.finditer(text or ""):
        raw = m.group(1).strip()
        try:
            obj = _json.loads(raw)
            name = obj.get("name", "").strip()
            args = obj.get("args", {}) or {}
            if name:
                actions.append({"name": name, "args": args})
        except Exception:
            continue
    cleaned = _ACTION_BLOCK_RE.sub("", text or "").strip()
    return cleaned, actions


def extract_model_text(resp) -> str:
    """Extrae texto visible de una respuesta del SDK Gemini sin inventar fallback."""
    if not resp:
        return ""
    try:
        text = resp.text or ""
        if text:
            return text
    except Exception:
        pass
    chunks: list[str] = []
    try:
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                t = getattr(part, "text", None)
                if t:
                    chunks.append(t)
    except Exception:
        pass
    return "".join(chunks).strip()
