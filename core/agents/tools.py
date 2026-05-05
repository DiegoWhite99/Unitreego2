"""Catalogo de herramientas (function calling) del agente Diver y dispatcher.

Las declaraciones se entregan al modelo en formato Gemini/OpenAI; el
dispatcher traduce nombre -> llamada Python real al robot.
"""

from __future__ import annotations

import math
import time
from typing import Any

from yolo_detector import detector as yolo_detector

from ..primitives import robot_send_command
from ..poses import (
    robot_heart_safe,
    robot_lie_safe,
    robot_recovery_safe,
    robot_rise_safe,
    robot_scrape_safe,
    robot_sit_safe,
    robot_wiggle_safe,
)
from ..runtime import run_async
from ..state import proximity_sensor, robot_state


# ────────────────────────────────────────────────────────────────────
# Catalogo de tools (formato Gemini; el handler convierte a OpenAI)
# ────────────────────────────────────────────────────────────────────
AGENT_TOOL_DECLARATIONS = [
    {
        "name": "saludar",
        "description": "Saluda alzando una pata; gesto amigable.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "sentarse",
        "description": "Se sienta de forma estable.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "levantarse",
        "description": "Se levanta desde la posición sentada (rise).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "recuperarse",
        "description": "Se recupera/reincorpora a posición de pie estable.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "acostarse",
        "description": "Se acuesta (StandDown).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "corazon",
        "description": "Hace un gesto de corazón con las patas. Cariñoso.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mover",
        "description": (
            "Mueve al robot en una dirección por una duración. "
            "Direcciones: adelante, atras, izquierda, derecha, "
            "girar_izquierda, girar_derecha. "
            "Para giros con un ángulo específico (ej: 'gira 360 "
            "grados', 'media vuelta', 'gira 180°'), pasa el "
            "parámetro `grados` en lugar de `duracion_s`."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direccion": {
                    "type": "string",
                    "description": "Dirección del movimiento.",
                },
                "duracion_s": {
                    "type": "number",
                    "description": (
                        "Segundos a moverse (0.5 a 5). Para giros con "
                        "ángulo, usa `grados` y deja esto vacío."
                    ),
                },
                "grados": {
                    "type": "number",
                    "description": (
                        "Solo para girar_izquierda/derecha: ángulo a "
                        "girar en grados (5 a 720). Una vuelta completa = 360."
                    ),
                },
            },
            "required": ["direccion"],
        },
    },
    {
        "name": "saltar_adelante",
        "description": "Salto frontal corto.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "menear_caderas",
        "description": "Menea las caderas (juguetón).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "parar",
        "description": "Detiene cualquier movimiento (parada de emergencia suave).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "mirar_alrededor",
        "description": (
            "Devuelve un resumen de lo que la cámara YOLO está "
            "detectando AHORA. Úsala cuando el usuario pregunte "
            "qué ves o qué hay alrededor."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


# ────────────────────────────────────────────────────────────────────
# Helpers que ejecutan acciones reales sobre el robot
# ────────────────────────────────────────────────────────────────────
def call_robot_action(action_name: str) -> dict[str, Any]:
    """Reusa los helpers seguros del robot (mismos que /api/action)."""
    if not robot_state.get("connected"):
        return {"ok": False, "msg": "El robot no está conectado."}
    try:
        if   action_name == "sit":      ok = run_async(robot_sit_safe())
        elif action_name == "rise":     ok = run_async(robot_rise_safe())
        elif action_name == "recovery": ok = run_async(robot_recovery_safe())
        elif action_name == "lie":      ok = run_async(robot_lie_safe())
        elif action_name == "heart":    ok = run_async(robot_heart_safe())
        elif action_name == "wiggle":   ok = run_async(robot_wiggle_safe())
        elif action_name == "scrape":   ok = run_async(robot_scrape_safe())
        else:
            cmd_map = {
                "hello":       "Hello",
                "stretch":     "Stretch",
                "stand":       "BalanceStand",
                "frontjump":   "FrontJump",
                "frontpounce": "FrontPounce",
                "frontflip":   "FrontFlip",
                "dance1":      "Dance1",
                "dance2":      "Dance2",
            }
            cmd = cmd_map.get(action_name)
            if not cmd:
                return {"ok": False, "msg": f"Acción desconocida: {action_name}"}
            ok = run_async(robot_send_command(cmd))
        return {"ok": bool(ok)}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


_AGENT_TURN_RATE = 0.7  # rad/s


def move_robot(
    direccion: str,
    duracion_s: float = 1.0,
    velocidad: float = 0.4,
    grados: float | None = None,
) -> dict[str, Any]:
    """Mueve el robot por X segundos en una dirección.
    Si `grados` se provee y la dirección es giro, calcula la duración a 0.7 rad/s."""
    if not robot_state.get("connected"):
        return {"ok": False, "msg": "El robot no está conectado."}

    direccion = (direccion or "").lower().strip()
    is_turn = direccion in (
        "girar_izquierda", "girar izquierda", "turn left",
        "girar_derecha",   "girar derecha",   "turn right",
    )

    if grados is not None and is_turn:
        try:
            grados_f = abs(float(grados))
        except (TypeError, ValueError):
            grados_f = 0.0
        grados_f = max(5.0, min(720.0, grados_f))
        # 5% de margen para compensar el último tick de 0.2 s antes del Move(0)
        duracion_s = (grados_f * math.pi / 180.0) / _AGENT_TURN_RATE * 1.05
        duracion_s = max(0.2, min(15.0, duracion_s))
    else:
        duracion_s = max(0.2, min(5.0, float(duracion_s)))

    velocidad = max(0.1, min(0.6, float(velocidad)))

    x, y, z = 0.0, 0.0, 0.0
    if   direccion in ("adelante", "frente",  "forward",  "north"):  x = velocidad
    elif direccion in ("atras", "atrás",      "reversa",  "back", "backward"): x = -velocidad
    elif direccion in ("izquierda",           "left"):               y = velocidad
    elif direccion in ("derecha",             "right"):              y = -velocidad
    elif direccion in ("girar_izquierda", "girar izquierda", "turn left"):  z = _AGENT_TURN_RATE
    elif direccion in ("girar_derecha",   "girar derecha",   "turn right"): z = -_AGENT_TURN_RATE
    else:
        return {"ok": False, "msg": f"Dirección desconocida: {direccion}"}

    # Cuando es el agente quien decide mover, el sensor de proximidad NO
    # debe abortarle el comando: el agente ya razonó si tenía sentido. El
    # frenado físico por obstáculo a <30cm sigue siendo la última línea de
    # defensa, pero la ventana FORCE evita que el alerta de "veo persona
    # cerca" cancele la orden. La ventana cubre la duración + un margen.
    try:
        proximity_sensor["_force_until"] = time.time() + float(duracion_s) + 0.5
        proximity_sensor["_alert_active"] = False
    except Exception:
        pass

    try:
        steps = max(1, int(duracion_s * 5))
        for _ in range(steps):
            run_async(robot_send_command("Move", {"x": x, "y": y, "z": z}))
            time.sleep(0.2)
        run_async(robot_send_command("Move", {"x": 0.0, "y": 0.0, "z": 0.0}))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def emergency_stop() -> dict[str, Any]:
    if not robot_state.get("connected"):
        return {"ok": False, "msg": "El robot no está conectado."}
    try:
        run_async(robot_send_command("Damp"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def look_around() -> dict[str, Any]:
    """Devuelve un resumen de lo que YOLO esta detectando ahora,
    incluyendo gestos humanos cuando hay modelo pose activo."""
    try:
        try:
            dets = yolo_detector.get_detections() or []
        except Exception:
            dets = []
        if not dets:
            return {"ok": True, "summary": "ahora mismo no veo nada destacable",
                    "classes": [], "gestures": []}

        groups: dict[str, int] = {}
        gestures: list[str] = []
        known_faces: list[str] = []
        unknown_faces = 0
        person_types: dict[str, int] = {}
        for d in dets:
            cls = d.get("label") or d.get("class_name") or "algo"
            groups[cls] = groups.get(cls, 0) + 1
            g = d.get("gesture")
            if g:
                gestures.append(g)
            category = d.get("person_category")
            if category:
                person_types[str(category)] = person_types.get(str(category), 0) + 1
            if d.get("kind") == "face" or cls == "rostro":
                if d.get("known") and d.get("person_name"):
                    known_faces.append(str(d.get("person_name")))
                else:
                    unknown_faces += 1

        items = sorted(groups.items(), key=lambda kv: -kv[1])
        obj_parts = [f"{n} {cls}{'s' if n>1 else ''}" for cls, n in items[:5]]

        gesture_names_es = {
            "mano_arriba":          "alguien con la mano arriba",
            "ambas_manos_arriba":   "alguien con ambas manos arriba",
            "brazos_arriba":        "alguien con los brazos arriba",
            "puños_arriba":         "alguien con los puños arriba (celebrando)",
            "manos_en_cadera":      "alguien con las manos en la cadera (le pide al robot sentarse)",
            "mano_abajo":           "alguien con la mano bajo la cadera (le pide al robot acostarse)",
            "señalando_derecha":    "alguien señalando a la derecha",
            "señalando_izquierda":  "alguien señalando a la izquierda",
            "sentado":              "alguien sentado",
            "t_pose":               "alguien con los brazos en cruz",
            "manos_juntas":         "alguien con las manos juntas",
            "brazos_cruzados":      "alguien con los brazos cruzados",
            "agachado":             "alguien agachado",
        }
        gest_parts = [gesture_names_es.get(g, g) for g in set(gestures)]
        person_type_names_es = {
            "nino": "niño/a",
            "joven": "joven",
            "adulto": "adulto/a",
            "adulto_mayor": "adulto/a mayor",
            "hombre": "hombre",
            "mujer": "mujer",
        }
        person_type_plural_es = {
            "nino": "niños/as",
            "joven": "jovenes",
            "adulto": "adultos/as",
            "adulto_mayor": "adultos/as mayores",
            "hombre": "hombres",
            "mujer": "mujeres",
        }
        person_type_parts = [
            f"{n} {(person_type_names_es if n == 1 else person_type_plural_es).get(cls, cls)}"
            for cls, n in sorted(person_types.items(), key=lambda kv: -kv[1])
        ]

        interactions: list[str] = []
        for d in dets:
            for obj in (d.get("holding") or []):
                interactions.append(f"persona con {obj}")
        interactions = list(set(interactions))

        chunks: list[str] = []
        if known_faces:
            names = sorted(set(known_faces))
            chunks.append("reconozco a " + ", ".join(names))
        elif unknown_faces:
            chunks.append(
                f"{unknown_faces} rostro{'s' if unknown_faces != 1 else ''} visible"
            )
        if gest_parts:
            chunks.append(", ".join(gest_parts))
        if person_type_parts:
            chunks.append(", ".join(person_type_parts))
        if interactions:
            chunks.append(", ".join(interactions))
        if obj_parts:
            chunks.append(", ".join(obj_parts))
        summary = "veo " + " — ".join(chunks) if chunks else "no veo nada claro"

        return {
            "ok":           True,
            "summary":      summary,
            "classes":      dict(items),
            "gestures":     list(set(gestures)),
            "interactions": interactions,
            "person_types":  person_types,
        }
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def dispatch(name: str, args: dict | None) -> dict[str, Any]:
    """Mapping interno: nombre de tool -> funcion Python."""
    args = args or {}
    if name == "saludar":          return call_robot_action("hello")
    if name == "sentarse":         return call_robot_action("sit")
    if name == "levantarse":       return call_robot_action("rise")
    if name == "recuperarse":      return call_robot_action("recovery")
    if name == "acostarse":        return call_robot_action("lie")
    if name == "corazon":          return call_robot_action("heart")
    if name == "saltar_adelante":  return call_robot_action("frontjump")
    if name == "menear_caderas":   return call_robot_action("wiggle")
    if name == "parar":            return emergency_stop()
    if name == "mover":
        return move_robot(
            direccion=args.get("direccion", ""),
            duracion_s=args.get("duracion_s", 1.0),
            grados=args.get("grados"),
        )
    if name == "mirar_alrededor":  return look_around()
    return {"ok": False, "msg": f"Herramienta no implementada: {name}"}
