# Informe de conexión Unitree Go2 Air — 2026-05-19

> Documento de cierre de jornada. Se logró handshake WebRTC LAN completo con el robot.
> Para retomar el viernes: salta al final, sección **"Cómo levantar todo desde cero"**.

---

## 1. Objetivo

Conseguir que la app web del proyecto se conecte por WebRTC al Go2 Air `B42D1000PAHBJ3K5` y reciba video + control. El bloqueo principal era no tener la **clave AES-128** que el firmware nuevo del robot (≥ Go2 1.1.15) exige para descifrar el handshake LAN (`data2=3`).

---

## 2. Configuración final (lo que dejamos funcionando)

| Variable | Valor | Dónde vive |
|---|---|---|
| Cuenta Unitree | `divergencyai@gmail.com` | nube Unitree |
| Password Unitree | `Diver.123` | nube Unitree (no es la `=WAs}r5iz5g5h/0`, esa estaba mal) |
| SN robot | `B42D1000PAHBJ3K5` | físico |
| MAC WiFi robot | `fe:23:cd:99:74:49` | cloud Unitree |
| MAC BLE robot | `FC:23:CD:99:74:4A` | BLE peripheral |
| Nombre BLE | `Go2_46481` | BLE advertisement |
| **AES-128 key** | **`cf083d2536fb3c9b02966c1c584daecb`** | [config/config.py](config/config.py:4) y cloud |
| **IP robot en LAN** | **`192.168.123.161`** | [config/config.py](config/config.py:3) — Ethernet directo |
| Subnet Ethernet | `192.168.123.0/24` | el robot actúa como DHCP server por Ethernet |
| Modo firmware | `data2: 3` (v3, AES-128 per-device) | descubierto en `con_notify` |
| Modelo / alias | `Go2 Air` / "Diver" | cloud |

### Archivos modificados / creados

- [config/config.py](config/config.py) — `ROBOT_IP` y `ROBOT_AES_128_KEY` con los valores reales
- [core/runtime.py](core/runtime.py) — fix `WindowsSelectorEventLoopPolicy` (esencial para ICE en Windows)
- [get_key.py](get_key.py) — script que pide la AES key a la cloud Unitree (login + `device/bind/list`)
- [configurar_wifi_robot.py](configurar_wifi_robot.py) — config WiFi por BLE (no aplicó por firmware nuevo, **queda como referencia**)
- [ble_scan_robot.py](ble_scan_robot.py) — escanea BLE buscando Go2/Unitree
- [test_con_notify.py](test_con_notify.py) — prueba mínima del handshake LAN
- [CONTEXTO_AES_KEY.md](CONTEXTO_AES_KEY.md) — bitácora previa (cuando aún no funcionaba)

### Dependencias nuevas instaladas

```powershell
pip install curl_cffi cloudscraper python-socketio[client] websocket-client
```

(`curl_cffi` para pasar Cloudflare TLS fingerprint del cloud Unitree; el resto ya eran auxiliares)

---

## 3. Paso a paso de lo que se hizo

### Paso 1 — Validar credenciales y obtener la AES key del cloud
- Primera contraseña probada (`=WAs}r5iz5g5h/0`) → login OK pero `device/bind/list` vacío.
- Con la contraseña correcta **`Diver.123`** → `device/bind/list` devolvió el robot con su `key: cf083d2536fb3c9b02966c1c584daecb`.
- Comando: `python get_key.py` (ya lleva las credenciales hardcoded internamente).
- Detalle técnico: el cloud Unitree está detrás de Cloudflare con JA3 fingerprinting. Hay que usar `curl_cffi` con `impersonate="chrome120"`, headers de Android (`AppVersion: 1.11.4`, `DeviceId: Samsung/...SM-S931B`, `AppSign = md5("XyvkwK45hp5PHfA8"+ts+nonce)`), endpoint correcto **`device/bind/list`** (no `robot/list`, ese da catch-all 13003).

### Paso 2 — Detectar el robot por BLE
- `python ble_scan_robot.py` (o el snippet de BleakScanner.discover) encontró:
  - **`Go2_46481`** en `FC:23:CD:99:74:4A`, RSSI ~-69 dBm.
- Útil para confirmar que el robot está cerca y vivo, no para configurarlo.

### Paso 3 — Intento fallido: configurar WiFi por BLE
- Script `configurar_wifi_robot.py` con protocolo UniPwn (clave AES `df98b715...`).
- **No funcionó**: 0 respuestas del robot, no aplicó la config. Firmware nuevo del Go2 parchó el protocolo de UniPwn (cambió la clave/formato).
- Se descartó esta ruta.

### Paso 4 — Conexión por Ethernet (la que sí funcionó)
- Cable RJ-45 del robot al **mismo router** que la laptop.
- El robot abrió subnet propia `192.168.123.0/24` haciendo de DHCP server por Ethernet.
- La laptop tomó IP `192.168.123.100` por su Ethernet.
- Ping sweep en `192.168.123.0/24` encontró al robot en **`192.168.123.161`** (esa misma IP es la que históricamente usaba `test_con_notify.py`).

### Paso 5 — Verificar la AES key contra el robot real
- POST `http://192.168.123.161:9991/con_notify` → HTTP 200, `data2: 3` (modo v3).
- `data1` descifrado con la AES key devolvió la clave pública RSA del robot → **AES key validada end-to-end**.

### Paso 6 — Arrancar el backend Flask y conectar
- `python app.py` → server en `http://localhost:5000` con `ROBOT_IP=192.168.123.161`.
- Primer intento desde el browser: `POST /api/connect` → 500. Handshake LAN OK pero **ICE no convergía**.
- Diagnóstico con `aioice` en DEBUG: Windows tiraba `WinError 10022` al mandar UDP IPv6 (bug conocido de `aiortc/aioice + ProactorEventLoop`).

### Paso 7 — Fix: WindowsSelectorEventLoopPolicy
- En [core/runtime.py:56](core/runtime.py#L56) (`ensure_event_loop`), antes de `new_event_loop()`, se setea:
  ```python
  if sys.platform == "win32":
      asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  ```
- Con eso ICE converge (todos los IPv6 candidate pairs → `SUCCEEDED`).
- Conexión WebRTC LAN completa.

---

## 4. Hallazgos clave (para no repetir aprendizajes)

1. **El cloud Unitree (`global-robot-api.unitree.com`) está protegido con Cloudflare JA3.** `requests` plano se bloquea con HTTP 567. Hay que usar `curl_cffi` con `impersonate="chrome120"` (eso ya lo hace el SDK oficial `unitree_webrtc_connect.unitree_cloud`).
2. **Code `13003 "request invalid"` del API es el catch-all del servidor** para paths que no existen. No es "params malos". Los endpoints reales son: `login/email`, `device/bind/list`, `user/info`, `webrtc/account`, `webrtc/connect`, `system/pubKey`, `token/refresh`.
3. **`AppVersion: 2.1.0` dispara una regla Cloudflare distinta** que bloquea con HTML page. Usar `1.11.4` (lo que usa el apk del SDK).
4. **`time.strftime("%Z")` en Windows ES devuelve `"Hora estándar de Colombia"`** (con `á`) y `curl_cffi` lo rechaza por no-ASCII en headers. Hardcodear `"GMT-05:00"`.
5. **El protocolo UniPwn fue parchado** en firmware reciente del Go2. La clave AES `df98b715d5c6ed2b25817b6f2554124a` ya no funciona para config BLE. Si en algún momento se quiere configurar WiFi por PC, hay que reverse-engineerear la nueva, o usar la app oficial.
6. **`Robot Connection Mode: 📡 4G`** en los logs del SDK es informativo del modo de upstream del robot al cloud — no significa que la conexión local esté usando 4G. La señalización LAN funciona igual.
7. **`aiortc` + `ProactorEventLoop` + IPv6 en Windows = bug `WinError 10022`** que mata ICE. Fix obligatorio: `WindowsSelectorEventLoopPolicy`. Esto aplica a cualquier app del proyecto que use aiortc.
8. **El Go2 Air sí tiene puerto Ethernet expuesto** (bajo tapa). Al conectarlo a un router, abre su propia subnet 192.168.123.x y hace DHCP — no toma IP del router. La laptop debe estar en el mismo switch para entrar a esa subnet.
9. **La AES key per-device es aleatoria, no se deriva del SN o MAC.** Probamos 15 fórmulas (MD5/SHA256/HMAC con combinaciones de SN+MAC) y ninguna funciona. Solo se obtiene desde el cloud (o leyendo el firmware con SSH).

---

## 5. Cómo levantar todo desde cero (para el viernes)

### Pre-requisitos físicos
1. Robot Go2 Air encendido (LEDs activos).
2. Cable Ethernet conectando el robot al router del Starlink.
3. Laptop conectada al mismo router (cualquier interfaz, WiFi o Ethernet).
4. LED verde en el puerto del router donde está el robot.

### Verificar IP del robot
```powershell
# Tu adaptador Ethernet debería tomar IP 192.168.123.x del DHCP del robot
ipconfig
# (buscar IPv4 que empiece con 192.168.123.)
```

Si **no** tomas IP en 192.168.123.x, el robot no está enchufado al mismo segmento; revisa cable.

Para confirmar la IP del robot (debería ser `192.168.123.161`):
```powershell
python -c "import requests; print(requests.post('http://192.168.123.161:9991/con_notify', timeout=3).status_code)"
# Debe imprimir 200
```

### Arrancar el backend
Desde la raíz del repo, con el venv activado:
```powershell
cd "d:\Documentos\Unitree_lab2\unitreeWebRTC"
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
python -X utf8 -u app.py
```

Deberías ver:
```
==================================================
  Daiver Control CUN — Flask Backend
  Robot IP: 192.168.123.161
  Server:   http://localhost:5000
==================================================
```

### Conectar desde la UI
1. Abrir navegador en `http://localhost:5000/`
2. En la UI, dar clic en **"Conectar Robot"**.
3. En el log del server debería verse:
   ```
   Data Channel Verification: ✅ OK
   ICE Connection State: 🟢 connected
   Peer Connection State: 🟢 connected
   ```

### Si algo falla — checklist rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| HTTP 500 en `/api/connect` con mensaje vacío | event loop policy | Verificar que [core/runtime.py:61-65](core/runtime.py#L61-L65) tiene el `WindowsSelectorEventLoopPolicy` |
| `con_notify` timeout | robot apagado o cable | encender / reenchufar |
| `AES KEY RECHAZADA` | key cambió (improbable) | re-correr `python get_key.py` |
| Robot no aparece en `192.168.123.161` | DHCP del robot dio otra IP | `arp -a | findstr 23-cd` o ping sweep `192.168.123.0/24` |
| `device/bind/list` vacío al correr `get_key.py` | cuenta cambió, robot desvinculado | re-vincular en app oficial Go2 |
| Otro WebRTC client holding slot | la app móvil oficial estaba abierta | cerrarla, esperar 20s |

### Si hay que regenerar la AES key
```powershell
python get_key.py
# Imprime: AES key: cf083d2536fb3c9b02966c1c584daecb
# Pega esa cadena en config/config.py línea 4
```

---

## 6. Para el viernes — ideas de continuación

- **Probar el control efectivo del robot**: comandos `BalanceStand`, `Hello`, `SitDown` desde la UI y ver respuesta física.
- **Probar el canal de video**: que YOLO reciba frames del Go2 (fuente "robot" en `user_end.html`).
- **Probar el canal de audio bidireccional** si la app lo necesita.
- **Restaurar el modo WiFi del robot**: si en el futuro quieres usarlo sin cable, hay que configurar STA via app oficial (BLE ya no sirve por el parche).
- **Limpiar credenciales hardcoded** de [get_key.py](get_key.py): mover a env vars (`UNITREE_EMAIL`, `UNITREE_PASSWORD`).
- **Considerar mover el fix del event loop a un punto más alto** ([app.py](app.py)) para que aplique aunque se use Flask sin pasar por `ensure_event_loop`.

---

## 7. Resumen ejecutivo

> Login cloud OK → AES key obtenida (`cf083d…aecb`) → robot en LAN por Ethernet en `192.168.123.161` → handshake `con_notify` valida la key → fix de `WindowsSelectorEventLoopPolicy` para que ICE convergiera en Windows → conexión WebRTC LAN establecida → server Flask listo.

Todo el bloqueador histórico (no tener la AES key + no poder conectarse) **está resuelto**. El viernes solo hay que arrancar `app.py` y darle Conectar.

Buen descanso, gracias a ti.
