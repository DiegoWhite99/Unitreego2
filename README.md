# Diver Control — Unitree Go2 Air (WebRTC)

Sistema de control web para el robot cuadrúpedo **Unitree Go2 Air** desarrollado para el Laboratorio 2 de la CUN. La aplicación combina:

- Un **backend Flask + Socket.IO** que se conecta al robot vía WebRTC.
- Una **interfaz web** responsive con gestión de usuarios, control remoto y reconocimiento de objetos con YOLO.
- Scripts de rutinas estáticas pre-programadas.
- Detector de proximidad por lidar integrado.

---

## Estructura del proyecto

```
unitreeWebRTC/
├── app.py                   # Bootstrap: arma app+socketio, registra blueprints y handlers
├── yolo_detector.py         # Detector YOLOv8 (cámara del robot / webcam / URL)
├── requirements.txt         # Dependencias Python
│
├── config/                  # Configuración (lee del .env: IP, claves, modelos)
│
├── api/                     # Blueprints Flask (capa HTTP / Socket.IO)
│   ├── connection.py, motion.py, vision.py, sensor.py, autoroute.py
│   ├── follow.py, agent.py, gestures.py, faces.py, map_ai.py
│   └── sockets.py, pages.py, unitree_cloud.py, ble.py
│
├── core/                    # Lógica de dominio (sin Flask)
│   ├── runtime.py           # App/Socket.IO + event loop asyncio compartido
│   ├── connection.py        # Conexión WebRTC al Go2 + video → YOLO
│   ├── primitives.py        # Envío de SPORT_CMD / Move
│   ├── poses.py, routines.py, autoroute.py, follow.py, state.py
│   ├── agents/              # Agente Diver (chat, tools, prompts, identidad)
│   └── perception/          # lidar, qr, faces
│
├── scripts/                 # Scripts sueltos (no los usa el backend)
│   ├── saludo.py, corazon.py … 01_test_connection.py …  # rutinas/demos
│   ├── aes/                 # Recuperación de la clave AES del robot
│   └── setup/               # Setup del robot (BLE, WiFi, SSH, con_notify)
│
├── tests/                   # Tests de integración
│
├── src/                     # Frontend servido por Flask
│   ├── index.html           # Panel principal (login, conexión, usuarios)
│   ├── user_end.html        # Landing de acciones + cámara YOLO
│   ├── controlRemoto.html   # Control remoto en vivo
│   ├── rutaGuiada.html      # Ruta guiada por QR
│   ├── autoroute.html       # Ruta autónoma
│   ├── help.html            # Centro de ayuda
│   ├── css/                 # Estilos separados por página
│   ├── js/                  # Lógica cliente
│   └── assets/, img/        # Imágenes
│
├── console/                 # Consola IA (panel de diagnóstico)
├── data/faces/              # Dataset local de rostros (reconocimiento)
├── docs/                    # Guías técnicas (AES, SSH)
├── informes/                # Informes técnicos (HTML/MD)
├── models/                  # Pesos YOLO (.pt) — auto-descargados
├── logs/                    # Logs del sistema
└── unitree_env/             # Virtualenv (no en git)
```

---

## Instalación

```bash
# 1. Crear y activar entorno virtual
python -m venv unitree_env
unitree_env\Scripts\activate          # Windows
# source unitree_env/bin/activate     # Linux / macOS

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar credenciales y la IP del robot
#    Copiar .env.example a .env y rellenar: ROBOT_IP, ROBOT_AES_128_KEY,
#    OPENAI_API_KEY / GEMINI_API_KEY. La IP también se puede cambiar desde
#    la UI (se guarda en .env, no en config.py).
copy .env.example .env                 # Windows  (cp en Linux/macOS)
```

---

## Uso

```bash
python app.py
```

Luego abrir en el navegador: `http://localhost:5000`

- **Usuario por defecto:** `admin` / `admin123`.
- El primer ingreso muestra un tutorial de 6 pasos.
- Asegurar que el computador y el robot estén **en la misma red WiFi**.

### Rutas principales

| Ruta | Descripción |
|---|---|
| `/` | Panel principal (login, conexión, estado, usuarios) |
| `/user-end` | Landing de acciones y reconocimiento de objetos |
| `/control-remoto` | Control remoto con joystick y video |
| `/autoroute` | Ruta autónoma |
| `/help` | Centro de ayuda |
| `/informes/` | Índice de informes técnicos |
| `/api/ping` | Medición de latencia |
| `/api/status` | Estado actual del robot |

---

## Tecnologías

- **Backend:** Python 3.12, Flask, Flask-SocketIO, `unitree_webrtc_connect`, aiortc.
- **Frontend:** HTML5/CSS3/JS vanilla, Socket.IO cliente, sin frameworks.
- **IA:** Ultralytics YOLOv8 (modelos `yolov8n.pt` / `yolov8s.pt` / `yolov8m.pt`).

---

## Notas técnicas

- El firmware del Go2 Air **no expone el SoC de batería** por WebRTC en la versión disponible; se retiró ese indicador.
- La medición de calidad de señal se hace vía ping activo cada 3 s.
- La gestión de usuarios se persiste en `localStorage` del navegador (frontend puro).
- Los tickets de soporte del formulario de ayuda se guardan localmente; pendiente endpoint `POST /api/help`.

---

## Licencia

Proyecto académico — Corporación Unificada Nacional, Laboratorio 2.
