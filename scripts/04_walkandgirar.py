import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def mover(pub_sub, x, y, z, duracion):
    """Movimiento continuo durante X tiempo"""
    start = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start < duracion:
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z}
            }
        )
        await asyncio.sleep(0.2)


async def main():
    print("====================================")
    print(" AVANZAR 5.4m + GIRO IZQUIERDA ")
    print("====================================")

    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP
    )

    print("[INFO] Conectando...")
    await conn.connect()
    print("[SUCCESS] Conectado")

    pub_sub = conn.datachannel.pub_sub

    await asyncio.sleep(2)

    # Stand
    print("[ACTION] Balance Stand")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)

    # =========================
    # 🚶 AVANZAR 5.4 METROS
    # =========================
    print("[ACTION] Avanzando 5.4 metros...")

    velocidad = 0.3  # m/s aprox
    tiempo = 18      # segundos (~5.4m)

    await mover(pub_sub, velocidad, 0.0, 0.0, tiempo)

    # Stop
    print("[ACTION] Stop")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
    )

    await asyncio.sleep(1)

    # =========================
    # 🔄 GIRO IZQUIERDA
    # =========================
    print("[ACTION] Girando izquierda...")

    velocidad_giro = 0.5  # velocidad angular
    tiempo_giro = 2       # ajustable (≈90°)

    await mover(pub_sub, 0.0, 0.0, velocidad_giro, tiempo_giro)

    # Stop final
    print("[ACTION] Stop final")
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
    )

    await asyncio.sleep(1)

    await conn.disconnect()
    print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())