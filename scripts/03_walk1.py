import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def caminar_continuo(pub_sub):
    print("[LOOP] Caminata continua iniciada (CTRL + C para detener)")

    try:
        while True:
            await pub_sub.publish_request_new(
                RTC_TOPIC["SPORT_MOD"],
                {
                    "api_id": SPORT_CMD["Move"],
                    "parameter": {"x": 5.4, "y": 0.0, "z": 0.0}
                }
            )
            await asyncio.sleep(0.7)  # frecuencia de envío

    except asyncio.CancelledError:
        print("[INFO] Caminata cancelada")


async def main():
    print("====================================")
    print(" CAMINATA CONTINUA GO2 AIR ")
    print("====================================")

    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP
    )

    print("[INFO] Conectando...")
    await conn.connect()
    print("[SUCCESS] Conectado")

    pub_sub = conn.datachannel.pub_sub

    print("[INFO] Esperando estabilidad...")
    await asyncio.sleep(2)

    # Stand
    print("[ACTION] Balance Stand")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    # Caminata continua
    task = asyncio.create_task(caminar_continuo(pub_sub))

    try:
        # Mantener vivo el programa
        await asyncio.sleep(9999)

    except KeyboardInterrupt:
        print("\n[STOP] Deteniendo robot...")

        task.cancel()

        # Stop seguro
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
            }
        )

        await asyncio.sleep(1)

    finally:
        await conn.disconnect()
        print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())