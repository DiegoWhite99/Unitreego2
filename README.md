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
├── app.py                   # Servidor Flask principal (rutas, WebRTC, Socket.IO)
├── yolo_detector.py         # Detector YOLOv8 (webcam + cámara del robot)
├── requirements.txt         # Dependencias Python
│
├── config/                  # Configuración (IP del robot, parámetros)
├── scripts/                 # Rutinas estáticas del robot
│   ├── saludo.py, corazon.py, pata.py, pie.py, sentarse.py …
│   └── 01_test_connection.py, 02_basic_motion.py …
├── tests/                   # Tests de integración
│
├── website/                 # Frontend servido por Flask
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
├── informes/                # Informes técnicos (HTML imprimibles)
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

# 3. Configurar la IP del robot
# Editar config/config.py: ROBOT_IP = "10.3.16.11"
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
