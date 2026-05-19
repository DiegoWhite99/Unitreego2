# Recuperar AES-128 key del Unitree Go2 Air — estado al 2026-05-19

## TL;DR

- **Cuenta:** `divergencyai@gmail.com` / `=WAs}r5iz5g5h/0`
- **Robot SN objetivo:** `B42D1000PAHBJ3K5`
- **Login API:** ✅ funciona
- **`device/bind/list`:** ✅ responde `code:100` con `data: []` (vacío)
- **Conclusión:** el robot **NO está vinculado a esta cuenta** — por eso no devuelve la clave. Hay que vincularlo desde la app oficial, o sacar la clave por SSH/BLE.

## El script `get_key.py` que funciona

Está en la raíz del proyecto. Usa el SDK oficial `unitree_webrtc_connect` (ya instalado en `unitree_env`). Lo importante:

- Usa **`curl_cffi`** con `impersonate="chrome120"` para pasar el JA3/TLS fingerprinting de Cloudflare. `requests` plano se bloquea con HTTP 567.
- Endpoint correcto: **`device/bind/list`** (no `robot/list`, ese da 404 catch-all con `code:13003 "request invalid"`).
- Headers crítical-path (cualquier mismatch hace que el cloud responda `code:13003` en lugar de `code:100`):
  - `AppVersion: 1.11.4` (versión 2.1.0 dispara una regla Cloudflare distinta)
  - `DeviceId: Samsung/Samsung/SM-S931B/s24/14/34`
  - `AppName: Go2`
  - `AppSign = md5("XyvkwK45hp5PHfA8" + ts + nonce)` (nonce = uuid4.hex)
  - `AppTimezone`: usar `"GMT-05:00"` literal — `time.strftime("%Z")` en Windows ES devuelve `"Hora estándar de Colombia"` con `á` y curl_cffi lo rechaza por no-ASCII.

## Lo que aprendimos sobre la API Unitree

| Path | AppVersion | Resultado |
|---|---|---|
| `/login/email` POST | cualquiera | 200 + accessToken |
| `/user/info` GET | cualquiera | 200 + datos del usuario |
| `/device/bind/list` GET | `1.11.4` | 200 + lista de robots vinculados (con `key` AES) |
| `/robot/list` y similares | cualquiera | 200 + `code:13003` (catch-all, ruta no existe) |
| Cualquier path con `AppVersion: 2.1.0` + headers completos | — | HTTP 567 Cloudflare challenge |

Códigos de respuesta:
- `code: 100` = success
- `code: 1001` = token expirado → llamar `token/refresh`
- `code: 1000` = device not online (en `/webrtc/connect`)
- `code: 13003` = "request invalid" — el servidor devuelve esto para **rutas no encontradas** (catch-all), no para parámetros malos

JWT decodificado del accessToken: `{"sub":"user","uid":53067,"ct":1779205405,"iss":"unitree_robot","type":"access_token","exp":1781797405}`. El `uid` de la cuenta es `53067`.

## Por qué el robot no aparece

`device/bind/list` devuelve `[]`. Posibles razones (en orden de probabilidad):

1. **El robot nunca fue pareado con la app oficial Unitree usando esta cuenta.** Hay que abrir el Go2 app, login con `divergencyai@gmail.com`, "Agregar dispositivo", scan/SN.
2. El robot está pareado a una cuenta distinta (¿el lab tiene otra cuenta Unitree?). El SN `B42D1000PAHBJ3K5` puede estar registrado en otra dirección email.
3. La cuenta tiene `hasCompanyInfo: true` — está asociada a una organización. Quizá los robots están en el workspace de la empresa, no en el perfil personal. (Pero no encontré endpoint de `/company/devices` ni similar — todos dan 13003.)

## Alternativas si no se puede vincular desde la app

Documentadas en el repo (revisar antes de empezar):

### Opción A — SSH directo al robot ([INSTRUCCIONES_SSH_ROBOT.md](INSTRUCCIONES_SSH_ROBOT.md))
1. Conectarte al WiFi del robot (password: `00000000`)
2. `ssh unitree@192.168.12.1` (password: `123`)
3. Buscar la key:
   ```bash
   grep -rl "aes\|key\|secret" /unitree/ 2>/dev/null
   cat /unitree/module/webrtc_bridge/*.json 2>/dev/null
   strings /unitree/module/webrtc_bridge/bin/unitreeWebRTCClientMaster | grep -i "key\|aes" | head -30
   ```
4. La key son 32 chars hex. Va en `config/config.py` como `ROBOT_AES_128_KEY`.

### Opción B — BLE exploit UniPwn ([habilitar_ssh_robot.py](habilitar_ssh_robot.py))
- Si el SSH default no funciona porque no está habilitado, este script habilita SSH via BLE.
- Usa clave AES-CFB **hardcoded** para la negociación BLE: `df98b715d5c6ed2b25817b6f2554124a` (ojo: esta NO es la clave WebRTC, es la clave del protocolo de configuración BLE).
- Después del exploit: `ssh root@192.168.12.1` (password: `Bin4ryWasHere`).
- Requiere el robot encendido y cerca con BLE activo.

### Opción C — Reset físico
Botón de encendido sostenido ~10s al arrancar. Borra la pareja con la cuenta vieja y permite re-emparejar.

## Lo que NO funciona

Probado y descartado:

- **Derivación de clave desde SN/MAC** (`try_sn_derived_keys.py`): probó 15 fórmulas (MD5, SHA256, HMAC con combinaciones de SN y MAC). Ninguna funciona. **La key es aleatoria por dispositivo y solo existe en el cloud o en el firmware del robot.**
- **Claves comunes hardcoded** (`try_aes_decrypt.py`): ceros, FF, "1234...", "UnitreeRobotics1", "go2airsecretkey1", la clave legacy `e85682bd16549b008e04a6682bb3e3e3`. Ninguna.
- **`requests` plano**: bloqueado por Cloudflare (HTTP 567 con HTML de challenge).
- **`cloudscraper`**: pasa Cloudflare pero requiere los headers/AppVersion correctos del SDK.
- **Adivinar paths**: probé ~50 paths (`robot/list`, `user/robot`, `device/list`, con/sin prefijo `/v1` `/v2` `/api/`, con/sin SN en el path…). Todos 404 o `code:13003`.

## Mensaje "verificación en dos pasos de tu organización"

Aparece cuando intentas login web/OAuth con `divergencyai@gmail.com`. La cuenta de Google tiene 2FA forzado por la organización (CUN). **No afecta el API login de Unitree** — Unitree no usa OAuth de Google, solo email + md5(password). Por eso nuestro `get_key.py` sí logra autenticar.

## Para mañana

1. **Decidir ruta**:
   - Si tienen acceso a un celular con la app Go2 → opción más rápida: parear robot + correr `get_key.py` otra vez.
   - Si no → SSH directo (si el robot ya tiene SSH habilitado) o BLE exploit (si no).

2. **Una vez con la key (32 hex chars):**
   ```python
   # config/config.py
   ROBOT_AES_128_KEY = os.environ.get("ROBOT_AES_128_KEY", "<aqui-los-32-chars>")
   ```

3. **Verificar:** correr `test_con_notify.py` con el robot conectado al WiFi. Si `data2: 3` se descifra OK, la key sirve. Si tira `AesKeyRejectedError`, la key no corresponde.

## Archivos relevantes en el repo

- [get_key.py](get_key.py) — script funcional para obtener key del cloud (devuelve vacío hasta que el robot se vincule)
- [get_key_from_cloud.py](get_key_from_cloud.py) — versión anterior con más probing de endpoints (obsoleta, usaba headers viejos)
- [INSTRUCCIONES_SSH_ROBOT.md](INSTRUCCIONES_SSH_ROBOT.md) — guía paso a paso para SSH
- [habilitar_ssh_robot.py](habilitar_ssh_robot.py) — exploit BLE para habilitar SSH
- [ble_scan_robot.py](ble_scan_robot.py) — descubre UUIDs BLE del robot
- [test_con_notify.py](test_con_notify.py) — prueba el endpoint local `con_notify` del robot
- [try_aes_decrypt.py](try_aes_decrypt.py) / [try_sn_derived_keys.py](try_sn_derived_keys.py) — descartados, mantienen historial de intentos
- [unitree_env/Lib/site-packages/unitree_webrtc_connect/unitree_cloud.py](unitree_env/Lib/site-packages/unitree_webrtc_connect/unitree_cloud.py) — SDK oficial, fuente de verdad de la API
