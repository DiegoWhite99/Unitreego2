# 🔐 CONFIGURAR CLAVE AES-128 PARA CONECTAR AL ROBOT

El robot Unitree Go2 requiere autenticación mediante una clave AES-128 para conexiones WebRTC (versiones G1 ≥ 1.5.1).

## ✅ Pasos para conectar:

### Paso 1: Obtener la clave AES-128

**Opción A: Desde la APP Unitree (RECOMENDADO)**
1. Abre la app Unitree en tu teléfono
2. Ve a **Settings → Connect**
3. Busca el **AES-128 Key** (32 caracteres hexadecimales)
4. Copia la clave

**Opción B: SSH al robot**
```bash
ssh root@192.168.1.36
# Contraseña: 'unitree123' o vacía
# Busca en: /etc/unitree/ o cat /etc/config
```

**Opción C: Ejecutar el script de obtención automática**
```bash
python fetch_aes_key.py
```

### Paso 2: Configurar la clave

**Opción 1: Variable de entorno (RECOMENDADO)**
```bash
set ROBOT_AES_128_KEY=tu_clave_aqui_32_caracteres
# Luego ejecuta tu app
python app.py
```

**Opción 2: En `config/config.py`**
Edita el archivo y cambia:
```python
ROBOT_AES_128_KEY = "tu_clave_aqui_32_caracteres"
```

### Paso 3: Probar la conexión

```bash
python scripts/01_test_connection.py
```

Si ves `[SUCCESS] Conexion establecida con el Go2 Air 🎉`, ¡la conexión está lista!

## 🔍 Verificación:

**Si ves este error:**
```
This robot speaks data2=3 (G1 ≥ 1.5.1) — the per-device AES-128 key is required
```
→ El robot sí requiere la clave AES-128. Obtén la clave y configúrala.

**Si ves este error:**
```
Invalid AES-128 key format (must be 32 hex characters)
```
→ La clave tiene un formato incorrecto. Debe ser exactamente 32 caracteres hexadecimales.

## 📝 Notas:

- La clave AES-128 es única por robot
- Nunca comparta su clave AES-128 en repositorios públicos
- La clave se puede encontrar en la APP Unitree oficial
- Si no tienes acceso a la APP, intenta con SSH al robot

## 🆘 Soporte:

Si sigue sin funcionar:
1. Verifica que tu robot esté en la red correcta (192.168.1.x)
2. Intenta hacer ping al robot: `ping 192.168.1.36`
3. Revisa que la clave sea correcta (32 caracteres hex)
4. Reinicia el robot y el servidor
