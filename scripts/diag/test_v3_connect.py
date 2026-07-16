"""Prueba el connect LocalSTA REAL con el parche v3 aplicado."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.98"

from core.unitree_v3_patch import apply_v3_patch
apply_v3_patch()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod


async def main():
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=IP)
    await conn.connect()
    print("\n>>> ✅ CONECTADO — datachannel abierto. El handshake v3 funciono.")
    await asyncio.sleep(2)
    await conn.disconnect()
    print(">>> desconectado limpio.")


try:
    asyncio.run(asyncio.wait_for(main(), timeout=30))
except asyncio.TimeoutError:
    print(">>> ⏱ TIMEOUT 30s: el connect no completo (robot inestable o ICE no convergio).")
except SystemExit as e:
    print(f">>> ⛔ SystemExit del SDK (rechazo/offline/otro cliente): code={e.code}")
except Exception as e:
    import traceback
    print(f">>> ❌ Fallo: {type(e).__name__}: {e}")
    traceback.print_exc()
