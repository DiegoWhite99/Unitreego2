import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def mover(pub_sub, x, y, z, duracion):
    """Movimiento continuo durante X tiempo"""
    inicio = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - inicio < duracion:
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z}
            }
        )
        await asyncio.sleep(0.2)


async def stop(pub_sub):
    """Detener robot"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
    )
    await asyncio.sleep(1)


async def balance_stand(pub_sub):
    """Posicion de equilibrio"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)


async def hello(pub_sub):
    """Saludo - levanta la pata delantera"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Hello"]}
    )
    await asyncio.sleep(4)


async def wiggle_hips(pub_sub):
    """Meneo de caderas"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["WiggleHips"]}
    )
    await asyncio.sleep(4)


async def main():
    print("====================================")
    print("   RUTINA DE SALUDO GO2 AIR         ")
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

    # =========================
    # 1. Balance Stand
    # =========================
    print("[STEP 1] Balance Stand")
    await balance_stand(pub_sub)

    # =========================
    # 2. Avanzar un poco hacia la persona
    # =========================
    print("[STEP 2] Avanzar hacia la persona")
    await mover(pub_sub, 0.3, 0.0, 0.0, 2)
    await stop(pub_sub)

    # =========================
    # 3. Saludo - Levanta la pata
    # =========================
    print("[STEP 3] Saludo - Levanta la pata")
    await hello(pub_sub)

    # =========================
    # 4. Meneo de caderas (contento)
    # =========================
    print("[STEP 4] Meneo de caderas")
    await wiggle_hips(pub_sub)

    # =========================
    # 5. Segundo saludo
    # =========================
    print("[STEP 5] Segundo saludo")
    await hello(pub_sub)

    # =========================
    # 6. Balance Stand final
    # =========================
    print("[STEP 6] Balance Stand final")
    await balance_stand(pub_sub)

    print("[SUCCESS] Rutina de saludo completada")

    await conn.disconnect()
    print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())
