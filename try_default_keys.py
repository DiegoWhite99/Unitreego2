#!/usr/bin/env python3
"""Script para intentar conexión con claves por defecto y workarounds."""

import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config.config import ROBOT_IP

async def try_connection_with_key(ip: str, key: str | None = None, attempt_num: int = 1) -> bool:
    """Intenta conectar con una clave específica."""
    try:
        from unitree_webrtc_connect import (
            UnitreeWebRTCConnection,
            WebRTCConnectionMethod,
        )
        
        print(f"\n🔄 Intento {attempt_num}: Conectando a {ip}", end="")
        if key:
            print(f" con clave {key[:8]}...")
        else:
            print(" SIN clave...")
        
        conn_kwargs = {"ip": ip}
        if key:
            conn_kwargs["aes_128_key"] = key
        
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA,
            **conn_kwargs
        )
        
        print("  ⏳ Espera de conexión...", end="", flush=True)
        await asyncio.wait_for(conn.connect(), timeout=10.0)
        
        print("\n  ✅ ¡ÉXITO! Conexión establecida!")
        print(f"\n  Clave que funcionó: {key if key else 'NINGUNA (sin cifrado)'}")
        
        # Si la clave funcionó, guardarla
        if key:
            print(f"\n  📝 Agrega esto a config/config.py:")
            print(f'     ROBOT_AES_128_KEY = "{key}"')
        
        return True
        
    except asyncio.TimeoutError:
        print("\n  ⏱️  Timeout de conexión (robot no responde)")
        return False
    except Exception as e:
        error_msg = str(e).lower()
        print(f"\n  ❌ Error: {e}")
        
        # Analizar el error para dar feedback
        if "aes" in error_msg or "key" in error_msg or "encrypt" in error_msg:
            print("     → Parece que esta clave no es válida")
        elif "data2=3" in error_msg:
            print("     → El robot requiere clave AES-128")
        elif "connection refused" in error_msg or "unreachable" in error_msg:
            print("     → El robot no está en la red o no responde")
        
        return False

async def main():
    print("\n" + "=" * 70)
    print("  INTENTAR CONEXIÓN CON CLAVES POR DEFECTO")
    print("=" * 70)
    
    keys_to_try = [
        None,  # Sin clave
        "00000000000000000000000000000000",  # Todos ceros
        "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",  # Todos F
        "12345678901234567890123456789012",  # Secuencial
        "ABCDEF0123456789ABCDEF0123456789",  # Patrón
    ]
    
    print(f"\nIP del robot: {ROBOT_IP}")
    print(f"Intentos: {len(keys_to_try)}")
    
    for idx, key in enumerate(keys_to_try, 1):
        success = await try_connection_with_key(ROBOT_IP, key, idx)
        if success:
            print("\n" + "=" * 70)
            print("  ✅ CONEXIÓN EXITOSA")
            print("=" * 70)
            return True
        
        # Pequeña pausa entre intentos
        await asyncio.sleep(1)
    
    print("\n" + "=" * 70)
    print("  ❌ NINGUNA CLAVE FUNCIONÓ")
    print("=" * 70)
    print("""
PRÓXIMOS PASOS:

1. VERIFICAR ROBOT EN LÍNEA:
   ping 192.168.1.36
   
2. CONECTAR POR SSH Y BUSCAR CLAVE:
   ssh root@192.168.1.36
   # Contraseña: unitree123 o vacía
   # Luego: grep -r 'aes\|key' /etc/

3. BUSCAR EN DOCUMENTACIÓN DEL ROBOT:
   - Revisar manual del Go2 Air
   - Buscar en Unitree forum/GitHub
   - Documentación del firmware actual

4. ACTUALIZAR FIRMWARE:
   - Usar APP Unitree
   - Settings → System → Firmware Update
   
5. FACTORY RESET:
   - Mantener botón reset 10 segundos
   - Podría resetear credenciales
""")
    return False

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
