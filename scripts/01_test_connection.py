import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from config.config import ROBOT_IP, ROBOT_AES_128_KEY

async def main():
    print("====================================")
    print(" TEST CONEXION GO2 AIR - WEBRTC ")
    print("====================================")

    print(f"[INFO] IP objetivo: {ROBOT_IP}")
    print("[INFO] Metodo: LocalSTA")
    
    if ROBOT_AES_128_KEY:
        print(f"[INFO] Usando clave AES-128: {ROBOT_AES_128_KEY[:8]}...")
    else:
        print("[WARNING] No se especificó clave AES-128")

    try:
        conn_kwargs = {"ip": ROBOT_IP}
        if ROBOT_AES_128_KEY:
            conn_kwargs["aes_128_key"] = ROBOT_AES_128_KEY
        
        conn = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA,
            **conn_kwargs
        )

        print("[INFO] Iniciando conexion...")

        await conn.connect()

        print("[SUCCESS] Conexion establecida con el Go2 Air 🎉")

    except Exception as e:
        print("[ERROR] Fallo la conexion:")
        print(e)

if __name__ == "__main__":
    asyncio.run(main())

