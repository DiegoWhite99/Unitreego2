"""
00_referencia_comandos.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCRIPT DE REFERENCIA — Go2 Air WebRTC
Cada bloque es independiente y listo para copiar.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import math
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP


# ════════════════════════════════════════════════
#  PRIMITIVA BASE — mover()
#  Úsala en TODOS los movimientos continuos.
#  El robot solo se mueve mientras recibe el
#  comando, por eso se re-envía cada 0.2s.
# ════════════════════════════════════════════════
async def mover(pub_sub, x, y, z, duracion):
    inicio = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - inicio < duracion:
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z}
            }
        )
        await asyncio.sleep(0.2)


async def main():

    # ════════════════════════════════════════════
    #  CONEXIÓN — siempre al inicio
    # ════════════════════════════════════════════
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP)
    await conn.connect()
    pub_sub = conn.datachannel.pub_sub
    await asyncio.sleep(2)  # estabilización


    # ════════════════════════════════════════════
    #  PARARSE (Balance Stand)
    #  El robot debe estar parado antes de mover.
    #  Ejecutar siempre al inicio.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BalanceStand"]}
    )
    await asyncio.sleep(3)


    # ════════════════════════════════════════════
    #  AVANZAR
    #  x > 0 = adelante | x < 0 = atrás
    #  Fórmula: t = distancia / velocidad
    #
    #  Ejemplos:
    #    1 metro  a 0.5 m/s → t = 1.0 / 0.5 = 2s
    #    5 metros a 0.5 m/s → t = 5.0 / 0.5 = 10s
    # ════════════════════════════════════════════
    await mover(pub_sub, x=0.5, y=0.0, z=0.0, duracion=10)  # avanza 5m


    # ════════════════════════════════════════════
    #  RETROCEDER
    #  x negativo = hacia atrás
    # ════════════════════════════════════════════
    await mover(pub_sub, x=-0.5, y=0.0, z=0.0, duracion=4)  # retrocede 2m


    # ════════════════════════════════════════════
    #  MOVERSE DE LADO (strafing)
    #  y > 0 = izquierda | y < 0 = derecha
    # ════════════════════════════════════════════
    await mover(pub_sub, x=0.0, y=0.3, z=0.0, duracion=3)   # desplaza izquierda
    await mover(pub_sub, x=0.0, y=-0.3, z=0.0, duracion=3)  # desplaza derecha


    # ════════════════════════════════════════════
    #  GIRAR IZQUIERDA
    #  z > 0 = giro izquierda (antihorario)
    #  Fórmula: t = (grados × π/180) / velocidad_angular × K
    #
    #  Con z=1.0 rad/s y K=1.0:
    #    90°  → t = 1.571 / 1.0 = 1.57s
    #    180° → t = 3.142 / 1.0 = 3.14s
    #    360° → t = 6.283 / 1.0 = 6.28s
    # ════════════════════════════════════════════
    grados = 180
    t_giro = (grados * math.pi / 180) / 1.0   # ← ajustar K si desvía
    await mover(pub_sub, x=0.0, y=0.0, z=1.0, duracion=t_giro)


    # ════════════════════════════════════════════
    #  GIRAR DERECHA
    #  z < 0 = giro derecha (horario)
    # ════════════════════════════════════════════
    grados = 90
    t_giro = (grados * math.pi / 180) / 1.0
    await mover(pub_sub, x=0.0, y=0.0, z=-1.0, duracion=t_giro)


    # ════════════════════════════════════════════
    #  DETENER (Stop)
    #  Siempre llamar entre movimientos.
    #  Envía velocidad cero.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Move"], "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}}
    )
    await asyncio.sleep(1)


    # ════════════════════════════════════════════
    #  SENTARSE
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["SitDown"]}
    )
    await asyncio.sleep(3)


    # ════════════════════════════════════════════
    #  LEVANTARSE (desde el suelo / después de caída)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["RecoveryStand"]}
    )
    await asyncio.sleep(3)


    # ════════════════════════════════════════════
    #  PARADA DE EMERGENCIA (Damp)
    #  Amortigua todos los motores.
    #  El robot cae controladamente.
    #  Usar solo en emergencia.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Damp"]}
    )


    # ════════════════════════════════════════════
    #  AJUSTAR ALTURA DEL CUERPO
    #  Rango aprox: 0.20 (bajo) a 0.40 (alto)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["BodyHeight"], "parameter": {"data": 0.35}}
    )
    await asyncio.sleep(2)


    # ════════════════════════════════════════════
    #  INCLINAR EL CUERPO (Euler / Pose)
    #  Parámetros en radianes: roll, pitch, yaw
    #    roll  = inclinación lateral
    #    pitch = inclinación adelante/atrás
    #    yaw   = rotación horizontal
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Euler"],
            "parameter": {"x": 0.0, "y": 0.3, "z": 0.0}  # pitch 0.3 rad ≈ 17°
        }
    )
    await asyncio.sleep(2)


    # ════════════════════════════════════════════
    #  CAMBIAR TIPO DE MARCHA (Gait)
    #  0 = idle   1 = trot (normal)
    #  2 = run    3 = subir escaleras
    #  4 = bajar escaleras
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["SwitchGait"], "parameter": {"data": 1}}  # trot
    )
    await asyncio.sleep(1)


    # ════════════════════════════════════════════
    #  SALUDO (Hello)
    #  Levanta una pata delantera.
    #  Esperar ~4s para que termine la animación.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Hello"]}
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  ESTIRAMIENTO (Stretch)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Stretch"]}
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  CORAZÓN CON LA PATA (FingerHeart)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["FingerHeart"]}
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  MENEO DE CADERAS (WiggleHips)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["WiggleHips"]}
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  RASPAR EL SUELO (Scrape)
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Scrape"]}
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  BAILE 1 y BAILE 2
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Dance1"]}
    )
    await asyncio.sleep(6)

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["Dance2"]}
    )
    await asyncio.sleep(6)


    # ════════════════════════════════════════════
    #  VOLTERETA / SALTO (acrobacias)
    #  ⚠️ Requiere espacio libre alrededor.
    #  No usar en espacios reducidos.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["FrontFlip"]}   # voltereta frontal
    )
    await asyncio.sleep(5)

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["FrontJump"]}   # salto frontal
    )
    await asyncio.sleep(4)

    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["FrontPounce"]} # salto agresivo
    )
    await asyncio.sleep(4)


    # ════════════════════════════════════════════
    #  MODO MARCHA ECONÓMICA
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["EconomicGait"]}
    )
    await asyncio.sleep(2)


    # ════════════════════════════════════════════
    #  CONSULTAR ESTADO DEL ROBOT (GetState)
    #  Devuelve: modo, velocidad, posición, batería, etc.
    #  La respuesta llega por el canal de datos.
    # ════════════════════════════════════════════
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {"api_id": SPORT_CMD["GetState"]}
    )
    await asyncio.sleep(1)


    # ════════════════════════════════════════════
    #  DESCONEXIÓN — siempre al final
    # ════════════════════════════════════════════
    await conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main())