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


async def saltar(pub_sub):
    """Ejecutar salto frontal"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["FrontJump"]}
    )
    await asyncio.sleep(3)


async def balance_stand(pub_sub):
    """Posicion de equilibrio"""
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)


async def main():
    print("====================================")
    print("   RUTINA DE SALTO GO2 AIR          ")
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
    # 2. Avanzar 2m para tomar impulso
    # =========================
    print("[STEP 2] Avanzar 2m")
    await mover(pub_sub, 0.4, 0.0, 0.0, 5)
    await stop(pub_sub)

    # =========================
    # 3. Salto frontal
    # =========================
    print("[STEP 3] Salto frontal")
    await saltar(pub_sub)

    # =========================
    # 4. Recuperar equilibrio
    # =========================
    print("[STEP 4] Recuperar equilibrio")
    await balance_stand(pub_sub)

    # =========================
    # 5. Avanzar 2m
    # =========================
    print("[STEP 5] Avanzar 2m")
    await mover(pub_sub, 0.4, 0.0, 0.0, 5)
    await stop(pub_sub)

    # =========================
    # 6. Segundo salto frontal
    # =========================
    print("[STEP 6] Segundo salto frontal")
    await saltar(pub_sub)

    # =========================
    # 7. Recuperar equilibrio
    # =========================
    print("[STEP 7] Recuperar equilibrio")
    await balance_stand(pub_sub)

    # =========================
    # 8. Giro 180 y regresar
    # =========================
    print("[STEP 8] Giro 180")
    await mover(pub_sub, 0.0, 0.0, 1.0, 1.8)
    await stop(pub_sub)

    # =========================
    # 9. Avanzar de regreso 4m
    # =========================
    print("[STEP 9] Regresar 4m")
    await mover(pub_sub, 0.4, 0.0, 0.0, 10)
    await stop(pub_sub)

    # =========================
    # 10. Salto final
    # =========================
    print("[STEP 10] Salto final")
    await saltar(pub_sub)

    # =========================
    # 11. Balance Stand final
    # =========================
    print("[STEP 11] Balance Stand final")
    await balance_stand(pub_sub)

    print("[SUCCESS] Rutina de salto completada")

    await conn.disconnect()
    print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())
