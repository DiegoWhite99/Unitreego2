#!/usr/bin/env python3
"""Obtiene la clave AES-128 del robot Unitree desde la Unitree Cloud."""

import os
import sys

def fetch_aes_key_cloud():
    """Intenta obtener clave desde Unitree Cloud."""
    try:
        from unitree_webrtc_connect import UnitreeCloud
        
        print("Intentando conectar a Unitree Cloud...")
        cloud = UnitreeCloud()
        devices = cloud.list_devices()
        
        if devices:
            return devices
    except Exception as e:
        print(f"⚠️  No se pudo conectar a Unitree Cloud: {e}")
        return None

def fetch_aes_key_mdns():
    """Intenta obtener clave usando mDNS local."""
    try:
        from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
        
        print("Intentando obtener información del robot por red local (mDNS)...")
        # Intenta con la IP conocida
        ip = os.environ.get("ROBOT_IP", "192.168.1.36")
        
        # Nota: Algunos robots pueden exponer la clave en modo de descubrimiento
        print(f"  Conectando a {ip}...")
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA,
            ip=ip,
            enable_data_channel=False
        )
        return conn
    except Exception as e:
        print(f"⚠️  No se pudo conectar por mDNS: {e}")
        return None

def main():
    """Obtiene la clave AES-128 del robot."""
    print("=" * 70)
    print("  OBTENEDOR DE CLAVE AES-128 - Unitree Go2")
    print("=" * 70)
    print()
    
    # Opción 1: Unitree Cloud
    print("Opción 1: Conectando a Unitree Cloud...")
    print("-" * 70)
    devices = fetch_aes_key_cloud()
    
    if devices:
        print(f"✅ Se encontraron {len(devices)} dispositivo(s):\n")
        for idx, device in enumerate(devices, 1):
            name = device.get('name', 'Unknown')
            sn = device.get('sn', 'N/A')
            aes_key = device.get('aes_128_key', 'Not found')
            
            print(f"  {idx}. {name}")
            print(f"     Serial: {sn}")
            print(f"     🔑 AES-128: {aes_key}")
            print()
        
        if devices and 'aes_128_key' in devices[0]:
            print("=" * 70)
            print("  AGREGAR A config/config.py:")
            print("=" * 70)
            print(f'ROBOT_AES_128_KEY = "{devices[0]["aes_128_key"]}"\n')
        return
    
    print("\n")
    print("❌ No se pudo obtener la clave automáticamente.")
    print()
    print("=" * 70)
    print("  SOLUCIONES ALTERNATIVAS:")
    print("=" * 70)
    print("""
1. METODO MANUAL - Opción APP Unitree:
   - Abre la app Unitree en tu teléfono
   - Ve a Settings → Conectar
   - La clave aparece en formato: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (32 caracteres hex)
   - Copia la clave y agrégala a config/config.py como:
     ROBOT_AES_128_KEY = "tu_clave_aqui"

2. METODO - SSH al robot:
   ssh root@192.168.1.36
   # La contraseña suele ser 'unitree123' o vacía
   # Busca en /etc/unitree/ la información de la clave

3. METODO - Factory Reset:
   - Algunos robots tienen una clave default: 0000000000000000
   - Intenta primero con esta clave

4. VERIFICAR CONEXIÓN SIMPLE:
   python scripts/01_test_connection.py
   # Si sale: "data2=2" → No necesita clave AES
   # Si sale: "data2=3" → Necesita clave AES
""")

if __name__ == "__main__":
    main()

