"""
Descubre los UUIDs BLE reales del robot Unitree Go2 Air.
Ejecutar con el robot encendido y cerca.

    pip install bleak
    python ble_scan_robot.py
"""

import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME_KEYWORDS = ["go2", "unitree", "ut"]

async def main():
    print("Buscando robot...")
    devices = await BleakScanner.discover(timeout=10)

    address = None
    for d in devices:
        name = (d.name or "").lower()
        if any(k in name for k in TARGET_NAME_KEYWORDS):
            print(f"[+] Encontrado: {d.name} ({d.address})")
            address = d.address
            break

    if not address:
        print("[-] Robot no encontrado. Asegurate de que esta encendido y cerca.")
        return

    print(f"\nConectando a {address}...")
    async with BleakClient(address, timeout=20) as client:
        print("[+] Conectado!\n")
        print("=" * 60)
        print("SERVICIOS Y CARACTERISTICAS BLE DEL ROBOT")
        print("=" * 60)

        for service in client.services:
            print(f"\nServicio: {service.uuid}")
            print(f"  Descripcion: {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  Caracteristica: {char.uuid}")
                print(f"    Propiedades: {props}")
                print(f"    Handle: {char.handle}")

                # Si es legible, intentar leer el valor
                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        print(f"    Valor actual: {val.hex()} | {val!r}")
                    except Exception as e:
                        print(f"    (No se pudo leer: {e})")

        print("\n" + "=" * 60)
        print("PEGA EL OUTPUT COMPLETO ARRIBA PARA CONTINUAR")
        print("=" * 60)

asyncio.run(main())
