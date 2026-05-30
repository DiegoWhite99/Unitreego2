#!/usr/bin/env python3
"""Obtener clave AES-128 desde el Go2 Air sin acceso a Unitree Cloud."""

import os
import sys
import socket
import subprocess

def try_ssh_key_from_robot():
    """Intenta obtener la clave via SSH directo al robot."""
    print("=" * 70)
    print("  OPCIÓN 1: Obtener clave via SSH al robot")
    print("=" * 70)
    print()
    print("Comando para ejecutar en tu terminal:")
    print()
    print("  ssh root@192.168.1.36")
    print()
    print("Si pide contraseña, intenta:")
    print("  - 'unitree123'")
    print("  - Dejar en blanco (presionar Enter)")
    print("  - '123456'")
    print()
    print("Una vez dentro del robot, ejecuta uno de estos comandos:")
    print()
    print("  1. cat /etc/config/unitree.cfg       # Buscar 'aes_key' o 'key'")
    print("  2. cat /data/unitree.key             # Si existe el archivo de clave")
    print("  3. grep -r 'aes\\|key' /etc/         # Buscar recursivamente")
    print("  4. cat /proc/cmdline                 # Ver parámetros de boot")
    print()
    print("=" * 70)
    print()

def try_default_keys():
    """Intenta con claves por defecto conocidas."""
    print("=" * 70)
    print("  OPCIÓN 2: Probar con claves por defecto")
    print("=" * 70)
    print()
    print("El modelo Go2 Air podría tener claves por defecto.")
    print("Intenta estos valores en config.py:")
    print()
    
    default_keys = [
        "00000000000000000000000000000000",  # Todos ceros
        "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",  # Todos F
        "12345678901234567890123456789012",  # Secuencial
    ]
    
    for idx, key in enumerate(default_keys, 1):
        print(f"  {idx}. ROBOT_AES_128_KEY = \"{key}\"")
    
    print()
    print("Luego prueba: python scripts/01_test_connection.py")
    print()
    print("=" * 70)
    print()

def try_network_discovery():
    """Intenta descubrir el robot en la red."""
    print("=" * 70)
    print("  OPCIÓN 3: Verificar conectividad del robot")
    print("=" * 70)
    print()
    
    ip = "192.168.1.36"
    print(f"Verificando si el robot está en la red ({ip})...")
    print()
    
    try:
        result = subprocess.run(
            ["ping", "-n", "1", ip],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Robot ENCONTRADO en {ip}")
            print("   Está conectado y accesible por red")
        else:
            print(f"❌ Robot NO ENCONTRADO en {ip}")
            print("   Verifica que:")
            print("   1. El robot esté encendido")
            print("   2. Esté en la misma red WiFi/Ethernet")
            print("   3. La IP sea correcta")
    except Exception as e:
        print(f"❌ Error al verificar: {e}")
    
    print()
    print("=" * 70)
    print()

def alternative_approach():
    """Alternativa: usar conexión sin cifrado si es posible."""
    print("=" * 70)
    print("  OPCIÓN 4: Alternativa - Verificar versión del robot")
    print("=" * 70)
    print()
    print("El error mencionó 'data2=3' que requiere AES-128.")
    print()
    print("Pero algunos Go2 Air pueden tener:")
    print("  - Firmware antiguo (data2=2) → NO necesita clave")
    print("  - Configuración de red local (LAN mode) → Sin cifrado")
    print()
    print("Intenta actualizar el firmware del robot:")
    print("  1. Usa la APP Unitree")
    print("  2. Ve a Settings → System → Firmware Update")
    print("  3. Si hay actualización, instálala")
    print()
    print("Después intenta: python scripts/01_test_connection.py")
    print()
    print("=" * 70)
    print()

def try_mac_based_key():
    """Algunas versiones usan MAC address para generar clave."""
    print("=" * 70)
    print("  OPCIÓN 5: Generar clave basada en dirección MAC")
    print("=" * 70)
    print()
    print("Algunos robots generan la clave basada en su MAC address.")
    print()
    print("1. Descubre la MAC del robot:")
    print("   arp -a | findstr 192.168.1.36")
    print()
    print("2. O desde SSH en el robot:")
    print("   cat /sys/class/net/eth0/address")
    print("   cat /sys/class/net/wlan0/address")
    print()
    print("3. Si obtienes algo como: aa:bb:cc:dd:ee:ff")
    print("   Prueba estas variaciones como clave:")
    print("   - AABBCCDDEEFF00000000000000000000 (MAC repetido)")
    print("   - AABBCCDDEE00112233445566778899FF")
    print()
    print("=" * 70)
    print()

def hardcoded_test():
    """Intenta una conexión sin clave para ver el mensaje de error."""
    print("=" * 70)
    print("  OPCIÓN 6: Ejecutar test y capturar el mensaje")
    print("=" * 70)
    print()
    print("El mensaje de error podría contener más información.")
    print()
    print("Ejecuta (sin clave AES):")
    print("  python scripts/01_test_connection.py")
    print()
    print("Lee el mensaje de error completo. A veces muestra:")
    print("  - Sugerencias de clave")
    print("  - Configuración actual del robot")
    print("  - URLs de documentación")
    print()
    print("=" * 70)
    print()

def main():
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  OPCIONES PARA OBTENER CLAVE AES-128 EN GO2 AIR".center(68) + "║")
    print("║" + "  (Sin acceso a Unitree Cloud)".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    try_ssh_key_from_robot()
    try_default_keys()
    try_network_discovery()
    try_mac_based_key()
    try_network_discovery()
    alternative_approach()
    hardcoded_test()
    
    print()
    print("💡 RECOMENDACIÓN:")
    print("   Comienza por la OPCIÓN 1 (SSH al robot)")
    print("   Si el robot está en la red, podrás acceder por SSH")
    print("   y buscar la clave en sus archivos de configuración.")
    print()

if __name__ == "__main__":
    main()
