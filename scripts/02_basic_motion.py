import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import json
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from config.config import ROBOT_IP


async def main():
    print("====================================")
    print(" TEST MOVIMIENTO BASICO GO2 AIR ")
    print("====================================")

    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP
    )

    print("[INFO] Conectando...")
    await conn.connect()
    print("[SUCCESS] Conectado")

    # ✅ Canal correcto
    channel = conn.datachannel

    print("[INFO] Esperando estabilidad...")
    await asyncio.sleep(2)

    # ✅ Función para enviar comandos (IMPORTANTE)
    def send_cmd(cmd):
        channel.send(json.dumps(cmd))

    # 🧠 Stand
    print("[ACTION] Stand")
    send_cmd({"cmd": "stand"})
    await asyncio.sleep(3)

    # 🧠 Avanzar
    print("[ACTION] Avanzar")
    send_cmd({
        "cmd": "move",
        "vx": 0.2,
        "vy": 0.0,
        "vyaw": 0.0
    })
    await asyncio.sleep(2)

    # 🧠 Stop
    print("[ACTION] Stop")
    send_cmd({
        "cmd": "move",
        "vx": 0.0,
        "vy": 0.0,
        "vyaw": 0.0
    })
    await asyncio.sleep(1)

    # 🧠 Sit
    print("[ACTION] Sit")
    send_cmd({"cmd": "sit"})

    print("[DONE] Prueba finalizada")


if __name__ == "__main__":
    asyncio.run(main())