import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


async def mover(pub_sub, x, y, z, duracion):
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


async def stop(pub_sub):
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
    )
    await asyncio.sleep(1)


async def ejecutar_ruta(pub_sub, ciclo):
    print(f"\n🔁 INICIO CICLO {ciclo}\n")

    # STEP 1
    print("[STEP 1] Avanzar 5.5m")
    await mover(pub_sub, 0.5, 0.0, 0.0, 11)
    await stop(pub_sub)

    # STEP 2
    print("[STEP 2] Giro izquierda 180°")
    await mover(pub_sub, 0.0, 0.0, 1.0, 1.8)
    await stop(pub_sub)

    # STEP 3
    print("[STEP 3] Avanzar 5m")
    await mover(pub_sub, 0.5, 0.0, 0.0, 10)
    await stop(pub_sub)

    # STEP 4
    print("[STEP 4] Giro izquierda 180°")
    await mover(pub_sub, 0.0, 0.0, 1.0, 2)
    await stop(pub_sub)

    # STEP 5
    print("[STEP 5] Avanzar 3.75m")
    await mover(pub_sub, 0.5, 0.0, 0.0, 7.5)
    await stop(pub_sub)

    # STEP 6
    print("[STEP 6] Giro izquierda 180°")
    await mover(pub_sub, 0.0, 0.0, 1.0, 1.7)
    await stop(pub_sub)

    # STEP 7
    print("[STEP 7] Avanzar 4.8m")
    await mover(pub_sub, 0.3, 0.0, 0.0, 16)
    await stop(pub_sub)

    # STEP 8
    print("[STEP 8] Giro izquierda 180°")
    await mover(pub_sub, 0.0, 0.0, 1.0, 1.7)
    await stop(pub_sub)

    print(f"\n✅ FIN CICLO {ciclo}\n")


async def main():
    print("====================================")
    print(" RUTA PATRULLA LOOP GO2 AIR ")
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
    # 🔁 LOOP DE RUTA (2 VECES)
    # =========================
    ciclo = 1
    while ciclo <= 2:
        await ejecutar_ruta(pub_sub, ciclo)
        ciclo += 1

    print("[SUCCESS] Ruta completada 🎯")

    await conn.disconnect()
    print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())