import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import json
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
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

    pub_sub = conn.datachannel.pub_sub

    print("[INFO] Esperando estabilidad...")
    await asyncio.sleep(2)

    # Stand
    print("[ACTION] Stand")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    # Avanzar
    print("[ACTION] Avanzar")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.9, "y": 0.0, "z": 0.0}
        }
    )
    await asyncio.sleep(2)

    # Stop
    print("[ACTION] Stop")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["StopMove"]}
    )
    await asyncio.sleep(1)

    # Sit
    print("[ACTION] Sit")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["StandDown"]}
    )

    print("[DONE] Prueba finalizada")

    await conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
