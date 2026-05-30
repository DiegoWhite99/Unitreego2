# Instrucciones SSH al Robot Go2 Air — LEER ANTES DE DESCONECTARTE DE INTERNET

> Imprime o abre este archivo ANTES de conectarte al WiFi del robot.
> Una vez conectado al WiFi del robot pierdes internet.

---

## PASO 0 — Verificar que tienes SSH disponible

Abre PowerShell y ejecuta:

```powershell
ssh -V
```

Si dice algo como `OpenSSH_for_Windows_...` ya está listo.
Si da error, ejecuta esto para instalarlo:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

---

## PASO 1 — Conectarte al WiFi del robot

1. Enciende el robot (pulso corto + sostenido hasta que arranquen los ventiladores)
2. En tu laptop busca redes WiFi
3. Conecta a la red del robot (se llama algo como `Unitree_Go2_XXXX` o `GO2_XXXX`)
4. **Contraseña del WiFi: `00000000`** (ocho ceros)
5. Confirma que tu laptop está conectada a esa red

---

## PASO 2 — SSH al robot

Abre PowerShell y ejecuta:

```powershell
ssh unitree@192.168.12.1
```

Cuando pregunte la contraseña escribe:

```
123
```

Si da error de "authenticity of host", escribe `yes` y Enter.

Si `unitree@192.168.12.1` no funciona, prueba estas alternativas en orden:

```powershell
ssh root@192.168.12.1
# contraseña: unitree123

ssh unitree@192.168.123.18
# contraseña: 123

ssh root@192.168.123.18
# contraseña: 123
```

---

## PASO 3 — Una vez dentro del robot, busca la clave AES

Cuando veas el prompt del robot (algo como `unitree@raspberrypi:~$`), ejecuta estos comandos uno por uno:

### 3.1 Ver qué hay en el directorio WebRTC

```bash
ls /unitree/module/webrtc_bridge/
ls /unitree/module/webrtc_bridge/bin/
ls /unitree/module/webrtc_bridge/config/ 2>/dev/null
ls /unitree/module/webrtc_bridge/conf/ 2>/dev/null
```

### 3.2 Buscar archivos de configuración con la clave

```bash
find /unitree/ -name "*.json" -o -name "*.conf" -o -name "*.cfg" -o -name "*.key" -o -name "*.ini" 2>/dev/null
```

### 3.3 Buscar la palabra "key" o "aes" en esos archivos

```bash
grep -rl "aes\|AES\|webrtc_key\|secret\|token" /unitree/ 2>/dev/null | head -20
```

### 3.4 Ver el contenido de los archivos de configuración WebRTC

```bash
cat /unitree/module/webrtc_bridge/*.json 2>/dev/null
cat /unitree/module/webrtc_bridge/*.conf 2>/dev/null
cat /unitree/module/webrtc_bridge/config/* 2>/dev/null
cat /unitree/module/webrtc_bridge/conf/* 2>/dev/null
```

### 3.5 Buscar cadenas de texto en el binario WebRTC (puede dar mucha info)

```bash
strings /unitree/module/webrtc_bridge/bin/unitreeWebRTCClientMaster | grep -i "key\|aes\|secret\|passw" | head -30
```

### 3.6 Buscar archivos con exactamente 32 caracteres hex (formato de la clave)

```bash
find /unitree/ -type f -size -1k 2>/dev/null | xargs grep -l "[0-9a-fA-F]\{32\}" 2>/dev/null | head -10
```

### 3.7 Ver todo /unitree/ superficialmente

```bash
find /unitree/ -maxdepth 4 -type f 2>/dev/null | head -60
```

---

## PASO 4 — Qué buscar en los resultados

La clave AES se ve así: **32 caracteres hexadecimales**

Ejemplos de cómo se ve:
```
e85682bd16549b008e04a6682bb3e3e3
a1b2c3d4e5f60718293a4b5c6d7e8f90
```

Puede estar en un archivo JSON como:
```json
{"aes_key": "e85682bd16549b008e04a6682bb3e3e3"}
{"key": "e85682bd16549b008e04a6682bb3e3e3"}
{"webrtc_key": "e85682bd16549b008e04a6682bb3e3e3"}
```

---

## PASO 5 — Una vez que tengas la clave

1. Anota los 32 caracteres hex de la clave
2. Desconéctate del WiFi del robot: escribe `exit` en el SSH y vuelve a tu WiFi normal
3. Abre el archivo `config/config.py` del proyecto
4. Cambia esta línea:
   ```python
   ROBOT_AES_128_KEY = os.environ.get("ROBOT_AES_128_KEY", None)
   ```
   Por:
   ```python
   ROBOT_AES_128_KEY = os.environ.get("ROBOT_AES_128_KEY", "PEGA_AQUI_TUS_32_CARACTERES")
   ```
5. Reconecta al WiFi normal (192.168.1.97 del robot en red STA)
6. Inicia la app y ya conecta

---

## NOTAS IMPORTANTES

- Si ningún comando `ls` funciona, el robot puede tener una ruta diferente. En ese caso ejecuta:
  ```bash
  find / -name "webrtc*" -type f 2>/dev/null | head -20
  find / -name "*bridge*" -type d 2>/dev/null | head -10
  ```

- Si SSH no conecta a ninguna IP, el robot puede estar en modo STA (conectado a tu router).
  En ese caso conecta tu laptop a la misma red del router Y al robot a la vez,
  y prueba `ssh unitree@192.168.1.97` (la IP del robot en tu red local).

- Si pide contraseña y `123` no funciona, prueba: `unitree`, `1234`, `root`, `admin`, `` (vacía)

---

## RESUMEN RÁPIDO (para pegar en papel)

```
WiFi robot → contraseña: 00000000
SSH: ssh unitree@192.168.12.1  → contraseña: 123
Buscar clave:
  grep -rl "aes\|key\|secret" /unitree/ 2>/dev/null
  find /unitree/ -name "*.json" -o -name "*.conf" 2>/dev/null
  cat /unitree/module/webrtc_bridge/*.json 2>/dev/null
Clave = 32 caracteres hex → va en config/config.py como ROBOT_AES_128_KEY
```
