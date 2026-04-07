"""
07_catalogo_y_patrulla.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Script de referencia corregido — Go2 Air via WebRTC
Basado en 06_rutinaLoop.py con todos los bugs corregidos
y el catálogo completo de comandos documentado.

Autor   : Diego Fernando Castelblanco Jiménez
Robot   : Unitree Go2 Air
SDK     : unitree_webrtc_connect v2.0.5 (legion1581)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

════════════════════════════════════════════════════════
 CATÁLOGO COMPLETO DE COMANDOS — SPORT MODE API
════════════════════════════════════════════════════════

 Topic destino: RTC_TOPIC["SPORT_MOD"]
                = "rt/api/sport/request"

 Formato de envío:
   await pub_sub.publish_request_new(
       RTC_TOPIC["SPORT_MOD"],
       {
           "api_id": SPORT_CMD["NombreComando"],
           "parameter": { ... }   # opcional según comando
       }
   )

 ┌─────────┬──────────────────┬────────────┬─────────────────────────────────────────────────┐
 │ api_id  │ SPORT_CMD key    │ Categoría  │ Descripción + parámetros                        │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1001   │ Damp             │ Seguridad  │ Amortigua motores. Parada de emergencia.         │
 │         │                  │            │ El robot cae controladamente. Sin parámetros.    │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1002   │ BalanceStand     │ Postura    │ Postura de pie en equilibrio. Ejecutar siempre   │
 │         │                  │            │ antes de mover. Sin parámetros.                  │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1003   │ StopMove         │ Movimiento │ Detiene el movimiento actual. Sin parámetros.    │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1004   │ Move             │ Movimiento │ ★ COMANDO PRINCIPAL DE DESPLAZAMIENTO            │
 │         │                  │            │ Debe re-enviarse cada ~0.2s (comando continuo).  │
 │         │                  │            │ Parámetros:                                      │
 │         │                  │            │   x: velocidad lineal adelante/atrás (m/s)       │
 │         │                  │            │      positivo=adelante, negativo=atrás           │
 │         │                  │            │      rango recomendado: -0.8 a 0.8               │
 │         │                  │            │   y: velocidad lateral izq/der (m/s)             │
 │         │                  │            │      positivo=izquierda, negativo=derecha         │
 │         │                  │            │   z: velocidad angular (rad/s) = vyaw            │
 │         │                  │            │      positivo=giro izquierda, negativo=derecha    │
 │         │                  │            │      rango recomendado: -1.5 a 1.5               │
 │         │                  │            │ Fórmulas:                                        │
 │         │                  │            │   distancia = x * tiempo_segundos                │
 │         │                  │            │   ángulo_rad = z * tiempo_segundos               │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1005   │ SwitchGait       │ Gait       │ Cambia tipo de marcha.                           │
 │         │                  │            │ Parámetro t: 0=idle, 1=trot, 2=run,              │
 │         │                  │            │             3=climb stairs, 4=down stairs         │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1007   │ BodyHeight       │ Postura    │ Altura del cuerpo. param: height (metros)        │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1008   │ FootRaiseHeight  │ Movimiento │ Altura de elevación de patas al caminar.         │
 │         │                  │            │ Parámetro: height (metros)                       │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1009   │ SpeedLevel       │ Movimiento │ Nivel velocidad global. param level: 0/1/2       │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1010   │ Hello            │ Acción     │ Robot saluda levantando pata delantera.           │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1011   │ Stretch          │ Acción     │ Estiramiento completo.                           │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1012   │ TrajectoryFollow │ Avanzado   │ Sigue trayectoria. Param: path[] (lista puntos)  │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1016   │ RecoveryStand    │ Postura    │ Levantarse desde el suelo después de una caída.  │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1017   │ Euler            │ Postura    │ Orientación cuerpo con ángulos Euler.             │
 │         │                  │            │ Params: roll, pitch, yaw (radianes)              │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1019   │ SitDown          │ Postura    │ Se sienta (pliegue patas). Sin parámetros.       │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1020   │ RiseSit          │ Postura    │ Levantarse desde sentado. Sin parámetros.        │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1022   │ Pose             │ Postura    │ Pose con ángulos de cuerpo.                      │
 │         │                  │            │ Params: roll, pitch, yaw (grados)                │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1023   │ Scrape           │ Acción     │ Raspar suelo con la pata.                        │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1024   │ FrontFlip        │ Acción     │ Voltereta frontal. Requiere espacio libre.       │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1025   │ FrontJump        │ Acción     │ Salto hacia adelante.                            │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1026   │ FrontPounce      │ Acción     │ Salto agresivo frontal.                          │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1027   │ WiggleHips       │ Acción     │ Meneo de caderas.                                │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1028   │ GetState         │ Telemetría │ Solicita estado completo del robot.              │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1029   │ EconomicGait     │ Movimiento │ Modo de marcha económica (menor consumo).        │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1032   │ Dance1           │ Acción     │ Secuencia de baile 1.                            │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1033   │ Dance2           │ Acción     │ Secuencia de baile 2.                            │
 ├─────────┼──────────────────┼────────────┼─────────────────────────────────────────────────┤
 │  1039   │ FingerHeart      │ Acción     │ Forma un corazón con la pata delantera.          │
 └─────────┴──────────────────┴────────────┴─────────────────────────────────────────────────┘

════════════════════════════════════════════════════════
 FÓRMULAS DE MOVIMIENTO
════════════════════════════════════════════════════════

  DISTANCIA:  d = v × t   →   t = d / v
    v = valor de x en Move (m/s)
    t = tiempo de sleep (s)
    Ejemplo: 5.5 m a 0.5 m/s → t = 5.5 / 0.5 = 11 s

  GIRO:  θ = ω × t   →   t = (θ_rad / ω) × K
    θ_rad = θ_deg × π / 180
    ω = valor de z en Move (rad/s)
    K = factor de corrección empírico (ajustar en lab)
    Ejemplo: 180° a ω=1.0 rad/s → t = (π / 1.0) × K ≈ 3.14 × K s

  TABLA DE GIROS (ω = 1.0 rad/s, K = 1.0):
     45° →  0.785 rad →  0.79 s
     90° →  1.571 rad →  1.57 s
    180° →  3.142 rad →  3.14 s   ← en lab calibrado a 1.7–2.0 s
    360° →  6.283 rad →  6.28 s

════════════════════════════════════════════════════════
 BUGS CORREGIDOS VS. 06_rutinaLoop.py
════════════════════════════════════════════════════════

  [BUG-1] asyncio.get_event_loop().time() → asyncio.get_running_loop().time()
          Deprecado en Python 3.10+

  [BUG-2] SPORT_CMD["StandDown"] no existe → usar SPORT_CMD["SitDown"]

  [BUG-3] Comentario Step 5 decía "5.4m" pero calcula 3.75m → corregido

  [BUG-4] Desconexión limpia con try/finally para garantizar conn.disconnect()

  [BUG-5] Patrón configurable: CICLOS, VELOCIDAD_AVANCE y VELOCIDAD_GIRO
          como constantes al inicio del archivo

"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
import math
import time
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.constants import SPORT_CMD, RTC_TOPIC
from config.config import ROBOT_IP

# ════════════════════════════════════════════════════════
#  CONFIGURACIÓN — AJUSTAR SEGÚN EL LABORATORIO
# ════════════════════════════════════════════════════════

CICLOS              = 2      # Número de ciclos de patrullaje
VELOCIDAD_AVANCE    = 0.5    # m/s — velocidad lineal estándar
VELOCIDAD_RETORNO   = 0.3    # m/s — velocidad del segmento de retorno (Step 7)
VELOCIDAD_GIRO      = 1.0    # rad/s — velocidad angular para giros

# Factor de corrección empírico para giros (K).
# Calibrar en laboratorio:
#   Si el robot gira de más  → bajar K (ej. 0.90)
#   Si el robot gira de menos → subir K (ej. 1.10)
FACTOR_GIRO_K       = 1.0

CMD_INTERVAL        = 0.2    # segundos entre comandos Move repetidos


# ════════════════════════════════════════════════════════
#  FUNCIONES DE FÍSICA
# ════════════════════════════════════════════════════════

def tiempo_avance(distancia_m: float, velocidad: float) -> float:
    """
    Calcula el tiempo necesario para recorrer una distancia.
    Fórmula: t = d / v
    """
    return distancia_m / velocidad


def tiempo_giro(grados: float, velocidad_angular: float = VELOCIDAD_GIRO) -> float:
    """
    Calcula el tiempo necesario para girar un ángulo dado.
    Fórmula: t = (θ_rad / ω) × K
    """
    radianes = abs(grados) * math.pi / 180
    return (radianes / abs(velocidad_angular)) * FACTOR_GIRO_K


# ════════════════════════════════════════════════════════
#  PRIMITIVAS DE MOVIMIENTO
# ════════════════════════════════════════════════════════

async def mover(pub_sub, x: float, y: float, z: float, duracion: float):
    """
    Envía el comando Move continuamente durante `duracion` segundos.

    El comando Move es CONTINUO: el robot solo avanza mientras recibe
    el comando. Si se deja de enviar, el robot se detiene.
    Por eso se re-envía cada CMD_INTERVAL segundos.

    Parámetros del comando Move:
        x: velocidad lineal adelante/atrás (m/s)
           positivo = adelante | negativo = atrás
        y: velocidad lateral (m/s)
           positivo = izquierda | negativo = derecha
        z: velocidad angular / yaw (rad/s)
           positivo = giro izquierda | negativo = giro derecha
    """
    # CORRECCIÓN BUG-1: usar get_running_loop() en vez de get_event_loop()
    inicio = asyncio.get_running_loop().time()

    while asyncio.get_running_loop().time() - inicio < duracion:
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {
                "api_id": SPORT_CMD["Move"],
                "parameter": {"x": x, "y": y, "z": z}
            }
        )
        await asyncio.sleep(CMD_INTERVAL)


async def stop(pub_sub):
    """
    Detiene el robot enviando velocidad cero y espera 1 segundo.
    Siempre llamar entre movimientos para estabilizar.
    """
    await pub_sub.publish_request_new(
        RTC_TOPIC["SPORT_MOD"],
        {
            "api_id": SPORT_CMD["Move"],
            "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
    )
    await asyncio.sleep(1)


async def avanzar(pub_sub, distancia_m: float, velocidad: float = VELOCIDAD_AVANCE):
    """
    Avanza `distancia_m` metros a `velocidad` m/s.
    Usa la fórmula: t = d / v
    """
    t = tiempo_avance(distancia_m, velocidad)
    print(f"    → Física: {distancia_m}m ÷ {velocidad}m/s = {t:.1f}s")
    await mover(pub_sub, velocidad, 0.0, 0.0, t)
    await stop(pub_sub)


async def girar(pub_sub, grados: float, direccion: str = "izquierda"):
    """
    Gira `grados` grados en la dirección indicada.
    Usa la fórmula: t = (θ_rad / ω) × K

    direccion: "izquierda" (vyaw positivo) | "derecha" (vyaw negativo)
    """
    t = tiempo_giro(grados, VELOCIDAD_GIRO)
    vyaw = VELOCIDAD_GIRO if direccion == "izquierda" else -VELOCIDAD_GIRO
    rad = abs(grados) * math.pi / 180
    print(f"    → Física: {grados}° = {rad:.3f} rad ÷ {VELOCIDAD_GIRO} × K={FACTOR_GIRO_K} = {t:.2f}s")
    await mover(pub_sub, 0.0, 0.0, vyaw, t)
    await stop(pub_sub)


# ════════════════════════════════════════════════════════
#  RUTA DE PATRULLAJE
# ════════════════════════════════════════════════════════
#
#  Diagrama de la ruta (vista desde arriba):
#
#   INICIO/FIN
#      ▲
#      │  Step 7 (4.8m ↑)
#      │
#  ◄───┘  Step 8 (giro izq 180°)
#  Step 6 (giro izq 180°) ───►
#      │  Step 5 (3.75m →)
#      │
#  ◄───┘  Step 4 (giro izq 180°)
#  Step 2 (giro izq 180°) ───►
#      │  Step 3 (5.0m →)
#      │
#      └───────────────────────► Step 1 (5.5m →)
#

async def ejecutar_ruta(pub_sub, ciclo: int):
    """
    Ejecuta un ciclo completo de la ruta de patrullaje.
    8 pasos: avanzar → girar → avanzar → girar → ... → cerrar ciclo.
    """
    t_inicio = time.monotonic()
    print(f"\n{'='*50}")
    print(f"  🔁 INICIO CICLO {ciclo}")
    print(f"{'='*50}\n")

    # ─────────────────────────────────────────────────
    # STEP 1 — Avanzar 5.5 metros (lado largo)
    # Comando: Move con x=VELOCIDAD_AVANCE durante t=d/v
    # ─────────────────────────────────────────────────
    print("[STEP 1/8] Avanzar 5.5 m")
    print(f"           Comando: Move(x={VELOCIDAD_AVANCE}, y=0.0, z=0.0)")
    await avanzar(pub_sub, 5.5, VELOCIDAD_AVANCE)

    # ─────────────────────────────────────────────────
    # STEP 2 — Giro izquierda 180°
    # Comando: Move con z=+VELOCIDAD_GIRO durante t=(π/ω)×K
    # vyaw positivo = giro antihorario (izquierda desde arriba)
    # ─────────────────────────────────────────────────
    print("[STEP 2/8] Giro izquierda 180°")
    print(f"           Comando: Move(x=0.0, y=0.0, z=+{VELOCIDAD_GIRO})")
    await girar(pub_sub, 180, "izquierda")

    # ─────────────────────────────────────────────────
    # STEP 3 — Avanzar 5.0 metros (lado largo, vuelta)
    # ─────────────────────────────────────────────────
    print("[STEP 3/8] Avanzar 5.0 m")
    print(f"           Comando: Move(x={VELOCIDAD_AVANCE}, y=0.0, z=0.0)")
    await avanzar(pub_sub, 5.0, VELOCIDAD_AVANCE)

    # ─────────────────────────────────────────────────
    # STEP 4 — Giro izquierda 180°
    # ─────────────────────────────────────────────────
    print("[STEP 4/8] Giro izquierda 180°")
    print(f"           Comando: Move(x=0.0, y=0.0, z=+{VELOCIDAD_GIRO})")
    await girar(pub_sub, 180, "izquierda")

    # ─────────────────────────────────────────────────
    # STEP 5 — Avanzar 3.75 metros (segmento corto)
    # CORRECCIÓN BUG-3: el comentario original decía "5.4m", corregido
    # Cálculo: 0.5 m/s × 7.5 s = 3.75 m
    # ─────────────────────────────────────────────────
    print("[STEP 5/8] Avanzar 3.75 m")
    print(f"           Comando: Move(x={VELOCIDAD_AVANCE}, y=0.0, z=0.0)")
    await avanzar(pub_sub, 3.75, VELOCIDAD_AVANCE)

    # ─────────────────────────────────────────────────
    # STEP 6 — Giro izquierda 180°
    # ─────────────────────────────────────────────────
    print("[STEP 6/8] Giro izquierda 180°")
    print(f"           Comando: Move(x=0.0, y=0.0, z=+{VELOCIDAD_GIRO})")
    await girar(pub_sub, 180, "izquierda")

    # ─────────────────────────────────────────────────
    # STEP 7 — Avanzar 4.8 metros a velocidad reducida (retorno)
    # Velocidad reducida VELOCIDAD_RETORNO para mayor precisión
    # ─────────────────────────────────────────────────
    print(f"[STEP 7/8] Avanzar 4.8 m (retorno, v={VELOCIDAD_RETORNO} m/s)")
    print(f"           Comando: Move(x={VELOCIDAD_RETORNO}, y=0.0, z=0.0)")
    await avanzar(pub_sub, 4.8, VELOCIDAD_RETORNO)

    # ─────────────────────────────────────────────────
    # STEP 8 — Giro izquierda 180° (cierre de ciclo)
    # Deja el robot orientado al punto de inicio
    # ─────────────────────────────────────────────────
    print("[STEP 8/8] Giro izquierda 180° (cierre de ciclo)")
    print(f"           Comando: Move(x=0.0, y=0.0, z=+{VELOCIDAD_GIRO})")
    await girar(pub_sub, 180, "izquierda")

    duracion = time.monotonic() - t_inicio
    print(f"\n✅ FIN CICLO {ciclo} — Duración: {duracion:.1f}s\n")


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

async def main():
    print("=" * 50)
    print(" RUTA PATRULLA LOOP — GO2 AIR")
    print(f" Ciclos: {CICLOS}")
    print(f" v_avance: {VELOCIDAD_AVANCE} m/s | v_retorno: {VELOCIDAD_RETORNO} m/s")
    print(f" ω_giro: {VELOCIDAD_GIRO} rad/s | K: {FACTOR_GIRO_K}")
    print("=" * 50)

    conn = UnitreeWebRTCConnection(
        WebRTCConnectionMethod.LocalSTA,
        ip=ROBOT_IP
    )

    # CORRECCIÓN BUG-4: usar try/finally para garantizar desconexión
    try:
        print("[INFO] Conectando...")
        await conn.connect()
        print("[SUCCESS] Conectado")

        pub_sub = conn.datachannel.pub_sub

        # Estabilización inicial
        await asyncio.sleep(2)

        # Postura inicial — SIEMPRE antes de mover
        print("[ACTION] Balance Stand")
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["BalanceStand"]}
        )
        await asyncio.sleep(3)

        # ── Ejecutar ciclos de patrullaje ──
        for ciclo in range(1, CICLOS + 1):
            await ejecutar_ruta(pub_sub, ciclo)

        print("[SUCCESS] Ruta completada 🎯")

        # ── Sentarse al terminar (opcional) ──
        # CORRECCIÓN BUG-2: SitDown, no StandDown
        # print("[ACTION] Sit Down")
        # await pub_sub.publish_request_new(
        #     RTC_TOPIC["SPORT_MOD"],
        #     {"api_id": SPORT_CMD["SitDown"]}
        # )
        # await asyncio.sleep(2)

    except KeyboardInterrupt:
        print("\n[STOP] Interrupción manual — deteniendo robot...")
        # Enviar stop de seguridad
        await pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Move"], "parameter": {"x": 0.0, "y": 0.0, "z": 0.0}}
        )
        await asyncio.sleep(1)

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        # CORRECCIÓN BUG-4: desconexión garantizada
        print("[INFO] Desconectando...")
        await conn.disconnect()
        print("[INFO] Desconectado")


if __name__ == "__main__":
    asyncio.run(main())