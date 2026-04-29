"""Handler completo del chat del agente Diver.

Tres ramas segun el modelo configurado:
  1. OpenAI (gpt-*, o*-*): tools nativos.
  2. Gemma 1/2/3 (sin tools nativos): protocolo JSON inline ```action.
  3. Gemini + Gemma 4+: tools nativos via google-generativeai.

Multimodal: si YOLO esta corriendo, adjunta el frame actual al mensaje.
Auto-disparo de `mirar_alrededor`: si el usuario pregunta algo de vision,
pre-ejecutamos el resumen y lo metemos en el contexto del modelo.
"""

from __future__ import annotations

import base64
import json as _json
import re
from typing import Any

from yolo_detector import detector as yolo_detector

from ..state import robot_state
from .config import (
    AGENT_GENERATION_CONFIG,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GENAI_AVAILABLE,
    OPENAI_AVAILABLE,
    is_openai_model,
    needs_json_tool_protocol,
    openai_client,
)
from .prompts import DIVER_GEMMA_TOOL_PROMPT, DIVER_LANGUAGE_GUARD, DIVER_SYSTEM
from .sanitize import (
    extract_model_text,
    parse_gemma_actions,
    reply_fallback,
    sanitize_reply,
)
from .tools import (
    AGENT_TOOL_DECLARATIONS,
    dispatch,
    look_around,
)


# Imports tardios del SDK Google
def _genai():
    import google.generativeai as genai
    return genai


# ────────────────────────────────────────────────────────────────────
# Pre-trigger de vision (auto mirar_alrededor)
# ────────────────────────────────────────────────────────────────────
_VISION_QUERY_RE = re.compile(
    r"\b(qu[eé]\s+(ves|estas?|est[aá]s|hay|miras?|observas?|"
    r"detect[ao]s?|hay\s+cerca|hay\s+alrededor)|"
    r"que\s+(ves|miras?|observas?)|"
    r"describe(me)?(\s+(lo\s+que|el|la|esto))?|"
    r"qu[eé]\s+puedes\s+ver|"
    r"mira\s+(alrededor|cerca|a\s+tu\s+alrededor)|"
    r"alrededor\s+(tuy[oa]|de\s+ti)|"
    r"hay\s+alguien|cu[eé]ntame\s+(qu[eé]|lo\s+que))\b",
    re.IGNORECASE
)


def _agent_result_context(user_msg: str, executed: list[dict]) -> str:
    """Contexto privado para que el modelo cierre una accion conversando."""
    if not executed:
        return ""
    parts: list[str] = []
    for item in executed:
        name = (item.get("name") or "accion").replace("_", " ")
        msg = (item.get("msg") or "").strip()
        if item.get("ok"):
            if name == "mirar alrededor" and msg:
                parts.append(f"vision: {msg}")
            else:
                parts.append(f"{name}: realizado")
        elif msg:
            parts.append(f"{name}: no realizado ({msg})")
        else:
            parts.append(f"{name}: no realizado")
    return (
        f"{DIVER_LANGUAGE_GUARD}\n\n"
        "Contexto privado para responder al usuario como Diver.\n"
        f"Mensaje original del usuario: {user_msg}\n"
        f"Resultado interno: {'; '.join(parts)}\n\n"
        "Dale al usuario una respuesta natural de chat. No menciones este "
        "contexto privado ni nombres de herramientas."
    )


# ────────────────────────────────────────────────────────────────────
# Health check (lo usa /api/agente/health)
# ────────────────────────────────────────────────────────────────────
def health() -> dict[str, Any]:
    if is_openai_model(GEMINI_MODEL):
        if not OPENAI_AVAILABLE:
            return {"ok": False, "message": "Falta el paquete: pip install openai"}
        if not openai_client:
            return {"ok": False, "message": "Falta OPENAI_API_KEY en config/config.py."}
        return {"ok": True, "model": GEMINI_MODEL, "provider": "openai"}
    if not GENAI_AVAILABLE:
        return {"ok": False,
                "message": "Falta el paquete: pip install google-generativeai"}
    if not GEMINI_API_KEY:
        return {"ok": False, "message": "Falta GEMINI_API_KEY en config/config.py."}
    return {"ok": True, "model": GEMINI_MODEL, "provider": "google"}


# ────────────────────────────────────────────────────────────────────
# Chat handler — devuelve el dict que el endpoint serializa
# ────────────────────────────────────────────────────────────────────
def chat(user_msg: str, history: list[dict]) -> dict[str, Any]:
    use_openai = is_openai_model(GEMINI_MODEL)

    # Validaciones segun proveedor.
    if use_openai:
        if not OPENAI_AVAILABLE:
            return {"reply": "⚠ Modelo OpenAI elegido pero falta `openai`. "
                             "Instala con: pip install openai",
                    "actions": []}
        if not openai_client:
            return {"reply": "⚠ Falta configurar `OPENAI_API_KEY` en config/config.py.",
                    "actions": []}
    else:
        if not GENAI_AVAILABLE:
            return {"reply": "⚠ El backend no tiene `google-generativeai`. "
                             "Instala con: pip install google-generativeai",
                    "actions": []}
        if not GEMINI_API_KEY:
            return {"reply": "⚠ Falta configurar `GEMINI_API_KEY` en config/config.py.",
                    "actions": []}

    if not user_msg:
        return {"reply": "🐾", "actions": []}

    use_json_protocol = (not use_openai) and needs_json_tool_protocol(GEMINI_MODEL)

    print(f"\n[AGENTE] ─── Nuevo mensaje ───")
    print(f"[AGENTE] modelo:  {GEMINI_MODEL}")
    print(f"[AGENTE] usuario: {user_msg!r}")
    print(f"[AGENTE] robot conectado: {robot_state.get('connected', False)}")
    try:
        print(f"[AGENTE] yolo running:    {yolo_detector.is_running()}")
    except Exception:
        pass
    print(f"[AGENTE] historial turnos: {len(history)}")

    # Visión multimodal: frame actual de YOLO si esta corriendo.
    camera_image_part = None
    camera_image_jpg: bytes | None = None
    try:
        if yolo_detector.is_running():
            jpg = yolo_detector.get_current_frame_jpeg()
            if jpg:
                camera_image_jpg = jpg
                camera_image_part = {
                    "inline_data": {"mime_type": "image/jpeg", "data": jpg}
                }
    except Exception:
        camera_image_part = None
        camera_image_jpg = None

    # Pre-trigger de vision para preguntas obvias.
    auto_executed_pre: list[dict] = []
    auto_vision_summary: str | None = None
    auto_vision_pretrigger = False
    if _VISION_QUERY_RE.search(user_msg):
        auto_vision_pretrigger = True
        try:
            res = look_around()
            if res.get("ok") and res.get("summary"):
                auto_vision_summary = res["summary"]
                auto_executed_pre.append({
                    "name": "mirar_alrededor", "args": {},
                    "ok":   True, "msg": auto_vision_summary,
                })
                print(f"[AGENTE] auto mirar_alrededor → {auto_vision_summary!r}")
        except Exception as ex:
            print(f"[AGENTE] auto mirar_alrededor falló: {ex}")

    # Construye el "user message" como str o list-of-parts segun haya imagen.
    def _build_user_message(text: str):
        msg = text
        if auto_vision_summary:
            msg = (f"{text}\n\n"
                   f"(Contexto de tu cámara: {auto_vision_summary}. "
                   f"Responde en una frase natural, no cites este contexto.)")
        elif auto_vision_pretrigger:
            msg = (f"{text}\n\n"
                   f"(Contexto: la visión está apagada — pídele al usuario "
                   f"que toque 'Activar visión' para que puedas ver.)")
        if camera_image_part is None:
            return msg
        return [msg, camera_image_part]

    try:
        # ───── Rama OPENAI ─────
        if use_openai:
            return _chat_openai(
                user_msg, history,
                auto_executed_pre, auto_vision_summary, auto_vision_pretrigger,
                camera_image_jpg,
            )

        # ───── Rama JSON PROTOCOL (Gemma 1/2/3) ─────
        if use_json_protocol:
            return _chat_gemma_json(
                user_msg, history, auto_executed_pre, _build_user_message,
            )

        # ───── Rama TOOLS NATIVOS (Gemini + Gemma 4+) ─────
        return _chat_gemini_native(
            user_msg, history, auto_executed_pre, _build_user_message,
        )
    except Exception as e:
        return {"reply": f"⚠ Diver tuvo un error: {str(e)[:200]}",
                "actions": []}


# ────────────────────────────────────────────────────────────────────
# Implementaciones por rama (privadas)
# ────────────────────────────────────────────────────────────────────
def _chat_openai(
    user_msg: str,
    history: list[dict],
    auto_executed_pre: list[dict],
    auto_vision_summary: str | None,
    auto_vision_pretrigger: bool,
    camera_image_jpg: bytes | None,
) -> dict[str, Any]:
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("parameters",
                                    {"type": "object", "properties": {}}),
            },
        }
        for t in AGENT_TOOL_DECLARATIONS
    ]

    messages: list[dict] = [{"role": "system", "content": DIVER_SYSTEM}]
    for h in history[:-1]:
        role = "user" if h.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": h.get("text", "")})

    user_text = user_msg
    if auto_vision_summary:
        user_text = (f"{user_msg}\n\n"
                     f"(Contexto de tu cámara: {auto_vision_summary}. "
                     f"Responde en una frase natural, no cites este "
                     f"contexto.)")
    elif auto_vision_pretrigger:
        user_text = (f"{user_msg}\n\n"
                     f"(Contexto: la visión está apagada — pídele al "
                     f"usuario que toque 'Activar visión'.)")

    if camera_image_jpg:
        b64 = base64.b64encode(camera_image_jpg).decode("ascii")
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        })
    else:
        messages.append({"role": "user", "content": user_text})

    executed = list(auto_executed_pre)
    latest_text: list[str] = []

    for iteration in range(4):
        try:
            resp = openai_client.chat.completions.create(  # type: ignore[union-attr]
                model=GEMINI_MODEL,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=600,
            )
        except Exception as e:
            err = f"⚠ OpenAI API error: {str(e)[:200]}"
            print(f"[AGENTE] {err}")
            return {"reply": err, "actions": executed}

        msg_obj = resp.choices[0].message
        tool_calls = getattr(msg_obj, "tool_calls", None) or []
        content_text = msg_obj.content or ""

        if content_text:
            latest_text = [content_text]
            snippet = content_text[:120].replace("\n", " ")
            print(f"[AGENTE] iter {iteration}: texto = {snippet!r}")

        if not tool_calls:
            print(f"[AGENTE] iter {iteration}: sin tools — fin")
            break

        names = ", ".join(tc.function.name for tc in tool_calls)
        print(f"[AGENTE] iter {iteration}: tools = {names}")

        messages.append({
            "role": "assistant",
            "content": content_text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                } for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            try:
                targs = _json.loads(tc.function.arguments or "{}")
            except Exception:
                targs = {}
            result = dispatch(tc.function.name, targs)
            ok = result.get("ok")
            rmsg = result.get("msg") or result.get("summary") or ""
            print(f"[AGENTE]    → {tc.function.name}({targs}) "
                  f"→ ok={ok} msg={rmsg[:120]!r}")
            executed.append({
                "name": tc.function.name, "args": targs,
                "ok": ok, "msg": rmsg,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _json.dumps(result, ensure_ascii=False),
            })

    raw_reply = "\n".join(latest_text)
    final_reply = sanitize_reply(raw_reply, fallback=reply_fallback(executed))
    if raw_reply and not final_reply.strip():
        print(f"[AGENTE] sanitizer DESCARTÓ todo. raw={raw_reply[:200]!r}")
    print(f"[AGENTE] reply final: {final_reply[:160]!r}")
    print(f"[AGENTE] acciones ejecutadas: {[e['name'] for e in executed]}")

    return {"reply": final_reply or "🐾", "actions": executed}


def _chat_gemma_json(
    user_msg: str,
    history: list[dict],
    auto_executed_pre: list[dict],
    build_user_message,
) -> dict[str, Any]:
    genai = _genai()
    system_text = DIVER_SYSTEM + DIVER_GEMMA_TOOL_PROMPT
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        generation_config=AGENT_GENERATION_CONFIG,
    )

    gemma_history = []
    gemma_history.append({"role": "user",
                          "parts": [{"text": system_text}]})
    gemma_history.append({"role": "model",
                          "parts": [{"text": "Entendido. Soy Diver, tu perro guardián. 🐾"}]})
    for h in history[:-1]:
        role = "user" if h.get("role") == "user" else "model"
        gemma_history.append({"role": role,
                              "parts": [{"text": h.get("text", "")}]})

    chat_session = model.start_chat(history=gemma_history)
    resp = chat_session.send_message(build_user_message(user_msg))
    raw_text = extract_model_text(resp)

    cleaned_text, actions_requested = parse_gemma_actions(raw_text)

    executed = list(auto_executed_pre)
    for a in actions_requested:
        result = dispatch(a["name"], a.get("args") or {})
        executed.append({
            "name": a["name"], "args": a.get("args") or {},
            "ok": result.get("ok"),
            "msg": result.get("msg") or result.get("summary"),
        })
        if a["name"] == "mirar_alrededor" and result.get("summary"):
            cleaned_text = (cleaned_text + " " + result["summary"]).strip()

    if actions_requested:
        try:
            final_resp = chat_session.send_message(
                _agent_result_context(user_msg, executed)
            )
            final_text, _ = parse_gemma_actions(extract_model_text(final_resp))
            if final_text.strip():
                cleaned_text = final_text.strip()
        except Exception:
            pass

    cleaned_text = sanitize_reply(cleaned_text, fallback=reply_fallback(executed))
    return {"reply": cleaned_text or "🐾", "actions": executed}


def _chat_gemini_native(
    user_msg: str,
    history: list[dict],
    auto_executed_pre: list[dict],
    build_user_message,
) -> dict[str, Any]:
    genai = _genai()
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=DIVER_SYSTEM,
        generation_config=AGENT_GENERATION_CONFIG,
        tools=[{"function_declarations": AGENT_TOOL_DECLARATIONS}],
    )

    gemini_history = []
    for h in history[:-1]:
        role = "user" if h.get("role") == "user" else "model"
        gemini_history.append({"role": role,
                               "parts": [{"text": h.get("text", "")}]})
    chat_session = model.start_chat(
        history=gemini_history,
        enable_automatic_function_calling=False,
    )

    resp = chat_session.send_message(build_user_message(user_msg))
    executed = list(auto_executed_pre)
    latest_text: list[str] = []

    for iteration in range(4):
        tool_calls: list[tuple[str, dict]] = []
        iter_text: list[str] = []
        try:
            cand = resp.candidates[0]
            for part in cand.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    args = {
                        k: v for k, v in (
                            fc.args.items() if hasattr(fc.args, "items") else []
                        )
                    }
                    tool_calls.append((fc.name, args))
                elif getattr(part, "text", None):
                    iter_text.append(part.text)
        except Exception as ex:
            print(f"[AGENTE] error parseando respuesta (iter {iteration}): {ex}")

        if iter_text:
            latest_text = iter_text
            snippet = (" ".join(iter_text)[:120]).replace("\n", " ")
            print(f"[AGENTE] iter {iteration}: texto = {snippet!r}")

        if tool_calls:
            names = ", ".join(t[0] for t in tool_calls)
            print(f"[AGENTE] iter {iteration}: tools  = {names}")
        else:
            print(f"[AGENTE] iter {iteration}: sin tools — fin del razonamiento")
            break

        tool_responses = []
        for (tname, targs) in tool_calls:
            result = dispatch(tname, targs)
            ok = result.get("ok")
            msg = result.get("msg") or result.get("summary") or ""
            print(f"[AGENTE]    → {tname}({targs}) → ok={ok} msg={msg[:120]!r}")
            executed.append({
                "name": tname, "args": targs, "ok": ok, "msg": msg,
            })
            tool_responses.append({
                "function_response": {
                    "name": tname,
                    "response": {"result": result},
                }
            })

        try:
            resp = chat_session.send_message(tool_responses)
        except Exception as e:
            print(f"[AGENTE] fallo al continuar tras tools: {e}")
            latest_text.append(f"\n(no pude continuar: {e})")
            break

    if not latest_text:
        extracted = extract_model_text(resp)
        if extracted:
            latest_text.append(extracted)
            print(f"[AGENTE] texto extraído de fallback: {extracted[:120]!r}")

    if not latest_text and executed:
        try:
            final_resp = chat_session.send_message(
                _agent_result_context(user_msg, executed)
            )
            extracted = extract_model_text(final_resp)
            if extracted:
                latest_text.append(extracted)
                print(f"[AGENTE] reformulado tras tools: {extracted[:120]!r}")
        except Exception as e:
            print(f"[AGENTE] no pude reformular: {e}")

    raw_reply = "".join(latest_text)
    final_reply = sanitize_reply(raw_reply, fallback=reply_fallback(executed))
    if raw_reply and not final_reply.strip():
        print(f"[AGENTE] sanitizer DESCARTÓ todo. raw={raw_reply[:200]!r}")
    print(f"[AGENTE] reply final: {final_reply[:160]!r}")
    print(f"[AGENTE] acciones ejecutadas: {[e['name'] for e in executed]}")

    return {"reply": final_reply or "🐾", "actions": executed}
