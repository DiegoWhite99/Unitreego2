import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def sentarse(pub_sub):
    """
    SENTARSE (SitDown)
    El robot se sienta plegando las patas.
    """
    print("[INFO] Ejecutando sentarse...")

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["SitDown"]}
    )

    await asyncio.sleep(3)


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

    await sentarse(pub_sub)

    print("[INFO] Finalizado")
    await conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
