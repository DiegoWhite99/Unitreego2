import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from config.config import ROBOT_IP

async def main():
    print("====================================")
    print(" TEST CONEXION GO2 AIR - WEBRTC ")
    print("====================================")

    print(f"[INFO] IP objetivo: {ROBOT_IP}")
    print("[INFO] Metodo: LocalSTA")

    try:
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA,
            ip=ROBOT_IP
        )

        print("[INFO] Iniciando conexion...")

        await conn.connect()

        print("[SUCCESS] Conexion establecida con el Go2 Air 🎉")

    except Exception as e:
        print("[ERROR] Fallo la conexion:")
        print(e)

if __name__ == "__main__":
    asyncio.run(main())