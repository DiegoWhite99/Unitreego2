# Informe Técnico: Unitree WebRTC — Sistema de Agentes IA

**Fecha:** 10 de mayo de 2026  
**Proyecto:** Diver Control CUN — Robot Unitree Go2 Air  
**Enfoque:** Librerías, Entornos y Configuración de Agentes

---

## 1. Resumen Ejecutivo

Este documento proporciona un análisis técnico completo del sistema **Diver Control CUN**, enfocado en:

1. **Stack de tecnologías y librerías** utilizadas
2. **Configuración del entorno Python**
3. **Arquitectura y configuración del agente IA**
4. **Integración con proveedores LLM** (OpenAI, Google Gemini)
5. **Sistema de herramientas (Tools/Function Calling)**

El proyecto implementa un **agente de diálogo conversacional** que controla un robot cuadrúpedo mediante una interfaz web y WebRTC, con capacidades de visión, movimiento y reconocimiento de objetos.

---

## 2. Stack Tecnológico y Librerías

### 2.1 Dependencias Core (`requirements.txt`)

```
flask>=3.0                    # Framework web principal
flask-socketio>=5.3           # Comunicación en tiempo real (WebSockets)
ultralytics>=8.0              # YOLOv8 para detección de objetos
opencv-python>=4.8            # Procesamiento de imágenes y video
numpy>=1.24                   # Operaciones numéricas
qrcode[pil]>=7.4              # Generación/lectura de códigos QR
```

### 2.2 Dependencias Opcionales (no en requirements.txt)

Aunque no están listadas explícitamente, se importan condicionalmente:

| Librería | Versión | Propósito | Instalación |
|----------|---------|----------|-------------|
| `openai` | Latest | Cliente API de OpenAI (ChatGPT, GPT-4o) | `pip install openai` |
| `google-generativeai` | Latest | Cliente API de Google Gemini | `pip install google-generativeai` |

**Nota:** Estas se importan con manejo de excepciones para que el backend funcione incluso sin ellas.

### 2.3 Paquetes del Entorno Virtual

Ubicación: `unitree_env/` (virtualenv aislado)

El proyecto usa un entorno virtual de Python independiente para evitar conflictos con el sistema operativo.

---

## 3. Estructura del Entorno

### 3.1 Configuración del Entorno

**Archivo:** `config/config.py`

```python
ROBOT_IP = os.environ.get("ROBOT_IP", "192.168.1.36")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "...")  # Almacenado en config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")
```

**Resolución de credenciales (por prioridad):**

1. Variables de entorno (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.)
2. Configuración en `config/config.py` (fallback)
3. Vacío (si no se configuran)

### 3.2 Estructura de Directorios Relevantes

```
unitreeWebRTC/
├── config/                      # Configuración global
│   └── config.py               # API keys, IP del robot
│
├── core/                        # Lógica del dominio
│   ├── agents/                 # MÓDULO DEL AGENTE
│   │   ├── chat.py             # Handler del chat conversacional
│   │   ├── config.py           # Configuración IA (OpenAI vs Gemini)
│   │   ├── tools.py            # Catálogo de herramientas
│   │   ├── prompts.py          # System prompts y personalidad
│   │   ├── sanitize.py         # Limpieza de respuestas
│   │   ├── identity/           # Personalidad modular (.md)
│   │   │   ├── 00_identity.md
│   │   │   ├── 01_soul.md
│   │   │   ├── 02_purpose.md
│   │   │   ├── 03_capabilities.md
│   │   │   ├── 04_rules.md
│   │   │   └── 05_style.md
│   │   └── __init__.py
│   │
│   ├── runtime.py              # Flask app, Socket.IO, event loop asyncio
│   ├── connection.py           # WebRTC al robot
│   ├── perception/             # Detección: caras, LIDAR, QR
│   ├── state.py                # Estado global del robot
│   └── ...
│
├── api/                        # Blueprints Flask (endpoints)
│   ├── agent.py                # Rutas: /api/agente/chat, /api/agente/health
│   ├── sockets.py              # Manejadores Socket.IO
│   └── ...
│
├── app.py                      # Punto de entrada principal
└── requirements.txt            # Dependencias base
```

### 3.3 Activación del Entorno Virtual

**Windows:**
```powershell
unitree_env\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
source unitree_env/bin/activate
```

---

## 4. Arquitectura del Agente IA (Diver)

### 4.1 Flujo General del Chat

```
Usuario → /api/agente/chat (POST) 
  ↓
core/agents/chat.py::chat()
  ├─ [OPCIONAL] Auto-trigger visión (YOLO) si pregunta sobre objetos
  ├─ Construir user message (con imagen si está disponible)
  ├─ Llamar al modelo LLM (OpenAI o Google Gemini)
  │  ├─ OpenAI: function_calling nativo
  │  └─ Gemini: tools nativos / JSON inline (según modelo)
  ├─ Ejecutar herramientas invocadas (dispatch)
  └─ Devolver respuesta limpia + lista de acciones
  ↓
Frontend → Socket.IO → Usuario
```

### 4.2 Selección Automática de Proveedor

**Archivo:** `core/agents/config.py`

El sistema detecta automáticamente qué proveedor usar según las claves configuradas:

```python
# Resolución de proveedor
if is_openai_model(GEMINI_MODEL):
    # Usa OpenAI
    proveedor = "openai"
else:
    # Usa Google Generative AI (Gemini)
    proveedor = "google"
```

**Función helper:**
```python
def is_openai_model(name: str) -> bool:
    """Detecta si el nombre del modelo es de OpenAI (gpt-*, o1-*, etc.)"""
    return name.startswith(('gpt-', 'o1-'))
```

### 4.3 Modelos Soportados

#### OpenAI (si `OPENAI_API_KEY` configurado)
- `gpt-4o` (Recomendado)
- `gpt-4-turbo`
- `gpt-3.5-turbo`
- Cualquier modelo con prefijo `gpt-*` u `o1-*`

#### Google Gemini
- `gemini-2.0-flash` (Recomendado por velocidad)
- `gemini-1.5-pro` (Más potente)
- `gemini-1.5-flash` (Balance)
- Modelos locales: `gemma:7b`, `gemma2:9b`, etc.

### 4.4 Capacidades Multimodales

**Visión automática:**
- Si YOLO está ejecutándose, adjunta el **frame actual** de la cámara
- El modelo puede ver lo que el robot ve en tiempo real
- La imagen se envía como `data:image/jpeg` en base64

**Auto-trigger de visión:**
Cuando el usuario pregunta sobre objetos/visión:
```
"¿Qué ves?"
"Describe lo que hay alrededor"
"Hay alguien cerca?"
→ Se ejecuta automáticamente look_around() antes de consultar al modelo
```

---

## 5. Configuración de Agentes (Detallada)

### 5.1 Configuración del Sistema Prompt

**Archivo:** `core/agents/prompts.py`

El `system prompt` (instrucciones base del agente) se construye **dinámicamente**:

1. **Primero intenta cargar archivos modulares:**
   ```
   core/agents/identity/*.md (en orden alfabético)
   ```

2. **Si no existen, usa fallback hardcoded:**
   ```python
   _DIVER_SYSTEM_FALLBACK = """Eres **Diver**, un perro guardián robótico..."""
   ```

**Ventaja:** Puedes editar la personalidad del agente **sin tocar Python** — solo modifica los `.md` en `identity/`.

#### 5.1.1 Archivos de Identidad Modular

| Archivo | Propósito |
|---------|-----------|
| `00_identity.md` | Quién es Diver (identidad base) |
| `01_soul.md` | Personalidad y características |
| `02_purpose.md` | Objetivo y misión |
| `03_capabilities.md` | Qué puede hacer |
| `04_rules.md` | Restricciones y normas |
| `05_style.md` | Estilo de comunicación |

**Importante:** `README.md` en identity/ se ignora, los demás se concatenan.

#### 5.1.2 Regla de Oro del Sistema Prompt

```
"TÚ TODO LO PUEDES. La frase 'no puedo' está PROHIBIDA."
```

El agente NO usa condicionales como:
- ❌ "Si voy a la derecha podría chocar..."
- ❌ "Intentaré moverme..."
- ❌ "Quizás..."

En lugar de eso:
- ✅ "Voy." (acción) → "Hecho." (confirmación)
- ✅ "Aquí estoy." (presente directo)

### 5.2 Limpieza de Respuestas

**Archivo:** `core/agents/sanitize.py`

El modelo a veces "filtra" información del prompt (meta-fugas) o genera pasos internos innecesarios. El sanitizador elimina:

1. **Bloques de razonamiento interno:**
   ```
   ```action
   {"tool": "...", "args": {...}}
   ```
   ```

2. **Fugas de prompt:**
   ```
   "responde siempre en español"
   "natural conversation"
   "system instruction"
   ```

3. **Palabras clave de meta-razonamiento:**
   ```
   "User asks:", "Instruction:", "Plan: 1. 2. 3."
   ```

**Resultado:** Respuesta limpia y natural.

### 5.3 Health Check

**Endpoint:** `GET /api/agente/health`

Valida la configuración del agente:

```json
{
  "ok": true,
  "model": "gpt-4o",
  "provider": "openai"
}
```

O si hay problemas:
```json
{
  "ok": false,
  "message": "Falta OPENAI_API_KEY en config/config.py"
}
```

---

## 6. Sistema de Herramientas (Function Calling)

### 6.1 Catálogo de Herramientas

**Archivo:** `core/agents/tools.py`

El agente tiene acceso a **13+ herramientas** para controlar el robot:

#### Gestos y Posturas

| Herramienta | Descripción |
|-------------|-------------|
| `saludar` | Alza una pata (saludo amigable) |
| `sentarse` | Se sienta de forma estable |
| `levantarse` | Se levanta desde sentada |
| `acostarse` | Se acuesta (StandDown) |
| `recuperarse` | Recuperación a posición de pie |
| `corazon` | Gesto de corazón con patas |

#### Movimiento

| Herramienta | Parámetros |
|-------------|-----------|
| `mover` | `direccion`: adelante, atrás, izquierda, derecha, girar_izquierda, girar_derecha |
|  | `duracion_s`: 0.5 a 5 segundos (opcional) |
|  | `grados`: ángulo de giro (5-720°) si es giro |
| `saltar_adelante` | Salto frontal corto |
| `menear_caderas` | Gesto juguetón |
| `parar` | Detiene movimiento |

#### Visión

| Herramienta | Descripción |
|-------------|-------------|
| `mirar_alrededor` | Resumen YOLO de lo que ve la cámara |

**Ejemplo de invocación (OpenAI format):**
```json
{
  "type": "function",
  "function": {
    "name": "mover",
    "arguments": {
      "direccion": "adelante",
      "duracion_s": 2.5
    }
  }
}
```

### 6.2 Dispatcher

**Función:** `core/agents/tools.py::dispatch()`

Traduce el nombre de herramienta → comando Python real:

```python
def dispatch(tool_name: str, args: dict) -> dict:
    if tool_name == "sentarse":
        return call_robot_action("sit")
    elif tool_name == "mover":
        return move_robot(args["direccion"], args.get("duracion_s"))
    # ... más herramientas
```

### 6.3 Diferentes Protocolos según el Modelo

#### OpenAI (gpt-*, o1-*)
```
Usa native function_calling
```

#### Google Gemini (con native tools)
```
Usa el protocolo de tools nativos de Google
```

#### Gemma y otros modelos sin function calling
```
Usa protocolo JSON inline:

```action
{"name": "mover", "args": {"direccion": "adelante"}}
```
```

La librería `core/agents/chat.py` maneja automáticamente la conversión entre formatos.

---

## 7. Endpoints del Agente

### 7.1 Ruta de Chat

**Endpoint:** `POST /api/agente/chat`

**Parámetros:**
```json
{
  "message": "¿Cuántos objetos ves alrededor?",
  "history": [
    {"role": "user", "content": "Hola"},
    {"role": "assistant", "content": "¡Ey! Estoy aquí..."}
  ]
}
```

**Respuesta:**
```json
{
  "reply": "Veo 3 personas y una puerta...",
  "actions": [
    {
      "name": "mirar_alrededor",
      "args": {},
      "ok": true,
      "msg": "3 personas, 1 puerta, 2 sillas"
    }
  ]
}
```

### 7.2 Ruta de Health

**Endpoint:** `GET /api/agente/health`

Valida credenciales y disponibilidad de librerías.

---

## 8. Flujo Detallado de una Solicitud de Chat

### 8.1 Caso: Usuario pregunta "¿Qué ves?"

```
1. POST /api/agente/chat
   {
     "message": "¿Qué ves?",
     "history": []
   }

2. api/agent.py::api_agente_chat()
   └─ chat_handler(user_msg, history)

3. core/agents/chat.py::chat()
   ├─ Valida que LLM esté configurado ✓
   ├─ Detecta "ves" → Regex _VISION_QUERY_RE coincide
   ├─ Ejecuta AUTO-TRIGGER: look_around()
   │  └─ Llama core/agents/tools.py::look_around()
   │     └─ Analiza frames YOLO → resumen texto
   │        (ej: "1 persona, 2 sillas, 1 plantas")
   ├─ Adjunta frame actual de YOLO (si disponible)
   ├─ Llamada al modelo:
   │  - Incluye system prompt (Diver)
   │  - Incluye historial
   │  - Incluye tools disponibles
   │  - Envía user message + frame + resumen visión
   │  └─ OpenAI /chat/completions OR Google generativeai.generate_content()
   ├─ Modelo responde (ej: "Veo 1 persona y 2 sillas...")
   ├─ Sanitiza respuesta → remove meta-tags, etc.
   └─ Devuelve:
      {
        "reply": "Veo 1 persona y 2 sillas...",
        "actions": [
          {
            "name": "mirar_alrededor",
            "ok": true,
            "msg": "resumen interno"
          }
        ]
      }

4. Socket.IO emite respuesta → Frontend
   └─ Usuario ve: "Veo 1 persona y 2 sillas..."
```

### 8.2 Caso: Usuario pide movimiento

```
Usuario: "Gira 90 grados a la derecha"

→ Modelo responde (invoca tool):
  {
    "type": "function",
    "function": {
      "name": "mover",
      "arguments": {
        "direccion": "girar_derecha",
        "grados": 90
      }
    }
  }

→ dispatch() traduce y ejecuta:
  mover_robot(
    direccion="girar_derecha",
    grados=90
  )
  → Calcula duracion_s = (90° / 0.7 rad/s) * 1.05
  → Envía comando Move(0, 0, 0.7) por X segundos

→ Respuesta final:
  {
    "reply": "Girado. Listo.",
    "actions": [
      {
        "name": "mover",
        "args": {"direccion": "girar_derecha", "grados": 90},
        "ok": true,
        "msg": ""
      }
    ]
  }
```

---

## 9. Configuración Avanzada

### 9.1 Cambiar el Modelo LLM

**Opción 1: Variable de entorno (antes de iniciar)**
```powershell
$env:GEMINI_MODEL="gpt-4o"
$env:OPENAI_API_KEY="sk-..."
python app.py
```

**Opción 2: Editar `config/config.py`**
```python
OPENAI_API_KEY = "sk-..."
GEMINI_API_KEY = "..."
GEMINI_MODEL = "gpt-4o"  # o "gemini-2.0-flash", etc.
```

### 9.2 Editar la Personalidad del Agente

**Solo modifica archivos `.md` en `core/agents/identity/`**

Ejemplo: editar `01_soul.md`
```markdown
Eres **Diver**, un perro guardián robótico con:
- Lealtad inquebrantable
- Alerta ante cualquier movimiento
- Sentido del humor juguetón
```

→ El archivo se carga automáticamente al importar `prompts.py`.

### 9.3 Agregar Nuevas Herramientas

**Pasos:**

1. **Declarar en `tools.py`:**
```python
{
    "name": "tu_herramienta",
    "description": "Qué hace",
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"]
    }
}
```

2. **Implementar dispatcher:**
```python
def dispatch(tool_name: str, args: dict):
    if tool_name == "tu_herramienta":
        return tu_funcion_helper(args["param1"])
```

3. **Implementar función helper:**
```python
def tu_funcion_helper(param: str) -> dict:
    # Lógica del robot
    return {"ok": True, "msg": "..."}
```

### 9.4 Cambiar los Parámetros de Generación

**Archivo:** `core/agents/config.py`

```python
AGENT_GENERATION_CONFIG = {
    "temperature": 0.8,      # Creatividad (0.0-1.0)
    "top_p": 0.95,           # Nucleus sampling
    "max_output_tokens": 500 # Límite de respuesta
}
```

---

## 10. Dependencias de Terceros (Análisis Profundo)

### 10.1 Flask (>=3.0)

**Rol:** Framework web ligero para HTTP y routing

```python
from flask import Flask, request, jsonify
app = Flask(__name__)
```

**Usado para:**
- Servir archivos estáticos (`src/`)
- Rutas API (`/api/...`)
- Configuración de `root_path`

### 10.2 Flask-SocketIO (>=5.3)

**Rol:** WebSockets en tiempo real

```python
from flask_socketio import SocketIO
socketio = SocketIO(app, async_mode="threading")
```

**Usado para:**
- Comunicación bidireccional con frontend
- Eventos: `connect`, `disconnect`, `qr_detected`
- Actualización en vivo de estado del robot

### 10.3 Ultralytics (>=8.0)

**Rol:** YOLOv8 para detección de objetos

```python
from ultralytics import YOLO
model = YOLO("yolov8m.pt")
```

**Modelos descargados:**
- `yolov8n.pt` (nano)
- `yolov8s.pt` (small)
- `yolov8m.pt` (medium)
- `yolov8n-pose.pt`, `yolov8s-pose.pt` (estimación de pose)

**Usados en:**
- `yolo_detector.py` — detección en webcam
- `look_around()` — resumen de objetos para el agente

### 10.4 OpenCV (>=4.8)

**Rol:** Procesamiento de imágenes y video

```python
import cv2
frame = cv2.imread("image.jpg")
```

**Usados para:**
- Captura de cámara
- Conversión de formatos (BGR ↔ RGB, JPG encoding)
- Redimensionamiento de frames

### 10.5 NumPy (>=1.24)

**Rol:** Operaciones numéricas

```python
import numpy as np
```

**Usados para:**
- Álgebra lineal (transformaciones de pose)
- Procesamiento de arrays de píxeles

### 10.6 QRCode (>=7.4)

**Rol:** Lectura/generación de QR

```python
import qrcode
```

**Usado en:**
- Ruta guiada (rutaGuiada.html)
- Detección de puntos de referencia

### 10.7 OpenAI (importación condicional)

**Rol:** Cliente API de OpenAI

```python
from openai import OpenAI
client = OpenAI(api_key="sk-...")
response = client.chat.completions.create(...)
```

**Requisito:** Solo si `OPENAI_API_KEY` está configurada

### 10.8 Google Generative AI (importación condicional)

**Rol:** Cliente API de Google Gemini

```python
import google.generativeai as genai
genai.configure(api_key="...")
model = genai.GenerativeModel("gemini-2.0-flash")
```

**Requisito:** Solo si `GEMINI_API_KEY` está configurada

---

## 11. Event Loop Asyncio

### 11.1 Runtime Asyncio

**Archivo:** `core/runtime.py`

```python
def ensure_event_loop() -> None:
    """Crea un event loop en thread dedicado."""
    global _event_loop, _loop_thread
    if _event_loop is None or not _event_loop.is_running():
        _event_loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_start_event_loop, args=(_event_loop,), daemon=True
        )
        _loop_thread.start()
```

**Propósito:**
- Soportar operaciones asyncio (WebRTC, comunicación con robot)
- Evitar bloqueos en el thread de Flask

**Uso en chat del agente:**
```python
# En tools.py
ok = run_async(robot_send_command("BalanceStand"))
```

---

## 12. Manejo de Errores

### 12.1 Health Check

Antes de procesar un chat, se valida:

```python
def health() -> dict[str, Any]:
    if is_openai_model(GEMINI_MODEL):
        if not OPENAI_AVAILABLE:
            return {"ok": False, "message": "Falta el paquete: pip install openai"}
        if not openai_client:
            return {"ok": False, "message": "Falta OPENAI_API_KEY..."}
    else:
        if not GENAI_AVAILABLE:
            return {"ok": False, "message": "Falta el paquete: pip install google-generativeai"}
        if not GEMINI_API_KEY:
            return {"ok": False, "message": "Falta GEMINI_API_KEY..."}
```

### 12.2 Fallbacks

Si el modelo no responde o hay error:

```python
reply_fallback = "Estoy aquí contigo. Cuéntame un poco más..."
```

### 12.3 Try-Except en Importaciones

```python
try:
    from openai import OpenAI as _OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    _OpenAI = None
    OPENAI_AVAILABLE = False
```

Permite que el backend arranque sin OpenAI/Google si no están instalados.

---

## 13. Flujo de Integración Completo

### 13.1 Diagrama de Flujo del Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (HTML/JS)                       │
│  index.html → user_end.html → /api/agente/chat (AJAX)      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    FLASK APP (app.py)                       │
│  ├─ register_blueprints()                                  │
│  │  └─ Incluye: api/agent.py (rutas /api/agente/*)         │
│  ├─ register_socket_handlers()                             │
│  │  └─ Manejadores Socket.IO en tiempo real                │
│  └─ socketio.run(host="0.0.0.0", port=5000)               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              /api/agente/chat (POST)                         │
│                                                              │
│  api/agent.py::api_agente_chat()                            │
│    └─ core/agents/chat.py::chat(user_msg, history)         │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
    ┌──────────────┐        ┌──────────────────┐
    │  Health Check│        │   Load Models    │
    │              │        │  (OpenAI/Gemini) │
    └────────┬─────┘        └────────┬─────────┘
             │                       │
             └───────────┬───────────┘
                         ▼
          ┌──────────────────────────────┐
          │  Auto-trigger Vision YOLO    │
          │  (si es pregunta sobre ver)  │
          └────────────┬─────────────────┘
                       │
                       ▼
          ┌──────────────────────────────┐
          │  Construir User Message      │
          │  + Frame (si YOLO running)   │
          │  + Vision summary (si auto)  │
          └────────────┬─────────────────┘
                       │
                       ▼
    ┌──────────────────────────────────────┐
    │  Call LLM API                         │
    │  ├─ OpenAI: /chat/completions        │
    │  └─ Gemini: /generateContent         │
    │                                       │
    │  Con:                                │
    │  ├─ System prompt (Diver identity)   │
    │  ├─ Tools disponibles (Gemini/OpenAI)│
    │  ├─ Chat history                    │
    │  └─ Vision context                  │
    └────────────┬─────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
    ┌──────────────┐  ┌──────────────┐
    │  Tool Call?  │  │  Plain Text? │
    │              │  │              │
    └────────┬─────┘  └──────┬───────┘
             │                │
             ▼                │
    ┌──────────────────────┐  │
    │  dispatch()          │  │
    │  └─ Ejecutar tool    │  │
    │     (mover, sit,     │  │
    │     look_around,etc.)│  │
    └────────┬─────────────┘  │
             │                │
             └────────┬───────┘
                      ▼
         ┌──────────────────────────┐
         │  Sanitize Response       │
         │  (remove meta-leaks,     │
         │  action blocks, etc.)    │
         └────────────┬─────────────┘
                      │
                      ▼
         ┌──────────────────────────┐
         │  Return JSON:            │
         │  {                       │
         │    "reply": "...",       │
         │    "actions": [...]      │
         │  }                       │
         └────────────┬─────────────┘
                      │
                      ▼
      ┌─────────────────────────────────┐
      │   Socket.IO emit('chat_reply')  │
      │   o JSON response HTTP          │
      └─────────────────────────────────┘
                      │
                      ▼
         ┌──────────────────────────┐
         │  Frontend renderiza      │
         │  respuesta + acciones    │
         └──────────────────────────┘
```

---

## 14. Checklist de Instalación y Configuración

### 14.1 Setup Inicial

- [ ] Crear virtualenv: `python -m venv unitree_env`
- [ ] Activar: `unitree_env\Scripts\Activate.ps1` (Windows)
- [ ] Instalar dependencias: `pip install -r requirements.txt`

### 14.2 Configurar LLM

**Para OpenAI:**
- [ ] `pip install openai`
- [ ] Editar `config/config.py` o setear `$env:OPENAI_API_KEY`
- [ ] Setear `$env:GEMINI_MODEL` = `gpt-4o`

**Para Google Gemini:**
- [ ] `pip install google-generativeai`
- [ ] Editar `config/config.py` o setear `$env:GEMINI_API_KEY`
- [ ] Setear `$env:GEMINI_MODEL` = `gemini-2.0-flash`

### 14.3 Verificar Health

```bash
python -c "from core.agents.chat import health; print(health())"
```

### 14.4 Iniciar Server

```bash
python app.py
```

Servidor disponible en: `http://localhost:5000`

---

## 15. Diagnóstico y Troubleshooting

### 15.1 "Falta google-generativeai"

```
Solución: pip install google-generativeai
```

### 15.2 "Falta OPENAI_API_KEY"

```
Solución: Editar config/config.py o:
$env:OPENAI_API_KEY="sk-..."
```

### 15.3 "El agente no responde"

1. Verificar health: `GET /api/agente/health`
2. Ver logs en terminal (buscar `[AGENTE]`)
3. Verificar que el robot está conectado: `robot_state['connected'] == True`

### 15.4 "Las herramientas no se ejecutan"

1. Verificar que `robot_state['connected'] == True`
2. Ver logs de `dispatch()` en terminal
3. Confirmar que el comando WebRTC llega al robot

---

## 16. Resumen Técnico

| Aspecto | Detalles |
|--------|----------|
| **Lenguaje** | Python 3.9+ |
| **Framework Web** | Flask 3.0+ |
| **WebSockets** | Flask-SocketIO 5.3+ |
| **LLM** | OpenAI ChatGPT / Google Gemini (seleccionable) |
| **Visión** | YOLOv8 (ultralytics 8.0+) |
| **Procesamiento de imágenes** | OpenCV 4.8+ |
| **Type hints** | `from __future__ import annotations` |
| **Async** | asyncio + threading |
| **Frontend** | HTML5 + JavaScript + Socket.IO |
| **Estado Global** | `core/state.py` (robot_state dict) |
| **Personalidad Modular** | Archivos `.md` en `core/agents/identity/` |
| **Herramientas** | 13+ (gestos, movimiento, visión) |

---

## 17. Conclusión

El sistema **Diver Control CUN** implementa un **agente conversacional robusto y flexible** con:

✅ **Selección automática** de proveedor LLM (OpenAI vs Gemini)  
✅ **Multimodal** — visión integrada con el robot  
✅ **Function calling** nativo en todos los proveedores  
✅ **Personalidad configurable** sin tocar Python  
✅ **Arquitectura modular** — fácil de extender  
✅ **Manejo de errores** robusto y graceful  
✅ **Integración WebRTC** con el robot Unitree Go2 Air  

El enfoque de **configuración por archivos** (prompts en `.md`, credenciales en env vars) permite iterar rápidamente sin recompilar código.

---

**Fin del Informe**  
*Unitree WebRTC — Diver Control CUN — 2026*
