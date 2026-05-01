# Identidad de Diver

Cada archivo `.md` aquí es una sección del system prompt del agente. Se cargan en orden alfabético (por eso el prefijo numérico) y se concatenan al construir `DIVER_SYSTEM` en `core/agents/prompts.py`.

## Archivos

| Archivo | Sección |
|---------|---------|
| `00_identity.md` | Quién es Diver, cuerpo físico |
| `01_soul.md` | Personalidad, tono emocional, latino colombiano |
| `02_purpose.md` | Misión, para qué existe |
| `03_capabilities.md` | Tools disponibles, equivalencias |
| `04_rules.md` | Reglas duras (no condicionales, "es una orden", etc.) |
| `05_style.md` | Forma, longitud, ejemplos buenos/malos |

## Cómo iterar

1. Editá el `.md` que corresponda — sin tocar Python.
2. Reiniciá el backend (`python app.py` o como lo arranques) — los archivos se leen al importar el módulo.
3. Si querés agregar una sección nueva, creá `06_xxx.md` (numera para mantener orden).

## Cómo desactivar uno

Renombralo a `_NN_xxx.md.disabled` o movélo fuera de esta carpeta. El loader solo lee `*.md`.

## Fallback

Si la carpeta no existe o está vacía, el agente usa el prompt hardcoded de respaldo en `prompts.py` (`_DIVER_SYSTEM_FALLBACK`). Así nunca queda mudo aunque borres todo.

## Compatibilidad

Estos archivos forman SOLO el system prompt principal. Otras piezas siguen en `prompts.py`:
- `DIVER_LANGUAGE_GUARD` — guía corta inyectada por turno
- `DIVER_GEMMA_TOOL_PROMPT` — protocolo JSON para Gemma 1/2/3 (sin function calling)
- `DIVER_CHAT_FALLBACK` — respuesta de emergencia
