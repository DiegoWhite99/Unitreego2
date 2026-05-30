"""
Configura el WiFi del Unitree Go2 Air via BLE.

Usa el protocolo de configuracion del bootloader BLE (mismo que la app oficial
y que UniPwn, sin el payload de inyeccion SSH). Una vez aplicado el robot se
reinicia y se une al WiFi indicado.

Requisitos:
    pip install bleak pycryptodome

Uso:
    python configurar_wifi_robot.py
"""

import asyncio
import sys

from bleak import BleakScanner, BleakClient
from Crypto.Cipher import AES


# ─── Config ────────────────────────────────────────────────────────────
WIFI_SSID    = "Starlink"
WIFI_PASS    = "Diver2026**"
COUNTRY_CODE = "CO"      # Colombia (ISO 3166-1 alpha-2)
ROBOT_NAME   = "Go2_46481"
ROBOT_MAC    = "FC:23:CD:99:74:4A"

# ─── BLE / protocolo (mismo que UniPwn / app oficial) ──────────────────
AES_KEY     = bytes.fromhex("df98b715d5c6ed2b25817b6f2554124a")
AES_IV      = bytes.fromhex("2841ae97419c2973296a0d4bdfe19a4f")
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ffe2-0000-1000-8000-00805f9b34fb"
CHUNK_SIZE  = 14


def aes_encrypt(data: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CFB, iv=AES_IV, segment_size=128)
    return cipher.encrypt(data)


def aes_decrypt(data: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CFB, iv=AES_IV, segment_size=128)
    return cipher.decrypt(data)


def create_packet(instruction: int, data_bytes: list = None) -> bytes:
    """Frame: [0x52, length, instruction, ...data, checksum] cifrado AES-CFB."""
    instruction_data = [instruction]
    if data_bytes:
        instruction_data.extend(data_bytes)
    length    = len(instruction_data) + 3
    full_data = [0x52, length] + instruction_data
    checksum  = (-sum(full_data)) & 0xFF
    return aes_encrypt(bytes(full_data + [checksum]))


async def send_chunked(client: BleakClient, instruction: int, data: bytes):
    total = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for i in range(total):
        chunk = list(data[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE])
        pkt   = create_packet(instruction, data_bytes=[i + 1, total] + chunk)
        await client.write_gatt_char(WRITE_UUID, pkt, response=True)
        print(f"    chunk {i+1}/{total}: {bytes(chunk)!r}")
        await asyncio.sleep(0.3)


async def find_robot() -> str | None:
    print(f"[*] Buscando '{ROBOT_NAME}' por BLE...")
    devices = await BleakScanner.discover(timeout=8)
    for d in devices:
        if (d.name or "").lower() == ROBOT_NAME.lower() or d.address.upper() == ROBOT_MAC.upper():
            print(f"[+] Encontrado: {d.name} ({d.address})")
            return d.address
    # fallback: cualquiera con go2/unitree
    for d in devices:
        n = (d.name or "").lower()
        if "go2" in n or "unitree" in n:
            print(f"[+] Encontrado (fallback): {d.name} ({d.address})")
            return d.address
    print("[-] Robot no encontrado.")
    return None


async def configurar(address: str):
    print(f"[*] Conectando a {address}...")
    async with BleakClient(address, timeout=20) as client:
        print("[+] Conectado.\n")

        respuestas = []

        def on_notify(_sender, data: bytearray):
            try:
                dec = aes_decrypt(bytes(data))
                respuestas.append(dec)
                print(f"    [ROBOT] dec={dec!r}")
            except Exception as e:
                print(f"    [ROBOT] raw={bytes(data).hex()} (decrypt err: {e})")

        await client.start_notify(NOTIFY_UUID, on_notify)

        print("[1/6] Handshake...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(1, list(b"unitree")), response=True)
        await asyncio.sleep(2)

        print("[2/6] Solicitar SN...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(2), response=True)
        await asyncio.sleep(1.5)

        print("[3/6] Modo STA (cliente WiFi)...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(3, [0x02]), response=True)
        await asyncio.sleep(1)

        print(f"[4/6] SSID: {WIFI_SSID!r}")
        await send_chunked(client, 4, WIFI_SSID.encode("utf-8"))
        await asyncio.sleep(0.5)

        print(f"[5/6] Password: {'*' * len(WIFI_PASS)}")
        await send_chunked(client, 5, WIFI_PASS.encode("utf-8"))
        await asyncio.sleep(0.5)

        print(f"[6/6] Country code: {COUNTRY_CODE} (dispara aplicacion + reinicio)")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(6, list(COUNTRY_CODE.encode("ascii"))), response=True)
        await asyncio.sleep(5)

        await client.stop_notify(NOTIFY_UUID)

    print()
    print("=" * 55)
    print("[+] Configuracion enviada.")
    print("=" * 55)
    print(f"  SSID: {WIFI_SSID}")
    print(f"  Country: {COUNTRY_CODE}")
    print(f"  Respuestas del robot: {len(respuestas)}")
    for i, r in enumerate(respuestas):
        print(f"    [{i}] {r[:80]!r}")
    print()
    print("Espera ~30-60s mientras el robot reinicia y se une al WiFi.")
    print("Despues:")
    print("  arp -a | findstr fe-23-cd     (buscar la IP del robot)")
    print("  ping <ip>")


async def main():
    print("=" * 55)
    print("  CONFIGURAR WIFI EN UNITREE Go2 Air via BLE")
    print(f"  SSID destino: {WIFI_SSID}")
    print("=" * 55)
    print()
    addr = ROBOT_MAC
    if "--scan" in sys.argv:
        addr = await find_robot()
        if not addr:
            sys.exit(1)
    else:
        print(f"[*] Usando MAC hardcodeada: {addr}")
        print("    (usa --scan si la MAC cambio)")
    await configurar(addr)


if __name__ == "__main__":
    asyncio.run(main())
