import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def pata(pub_sub):
    """
    DAR LA PATA (Hello)
    Levanta una pata delantera como saludo.
    """
    print("[INFO] Ejecutando dar la pata...")

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Hello"]}
    )

    await asyncio.sleep(4)


async def main():
    print("[INFO] Conectando al robot...")

    conn = UnitreeWebRTCConnection(
        method=WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP
    )

    await conn.connect()
    pub_sub = conn.datachannel.pub_sub

    await asyncio.sleep(2)

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    await pata(pub_sub)

    print("[INFO] Finalizado")
    await conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
