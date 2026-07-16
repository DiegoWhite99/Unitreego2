"""Diagnostico de conexion al Go2. Lanzar con el python de unitree_env.

Pasos:
  1. Probe HTTP a los endpoints WebRTC locales del robot (8081/offer y 9991/con_notify).
  2. Confirma la firma del constructor del SDK (¿acepta aes_128_key?).
  3. Reproduce EXACTAMENTE la construccion que hace core/connection.py.
  4. Si el handshake local responde, intenta un connect LocalSTA real (con timeout).
"""
import sys, os, json, asyncio, inspect, traceback

# El SDK imprime emojis; en consola Windows (cp1252) eso lanza UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# El script vive en scripts/diag/ — añade la raiz del proyecto al path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.98"

print(f"=== DIAGNOSTICO CONEXION Go2 — IP {IP} ===\n")

# ── 1. Probe HTTP a los endpoints locales ───────────────────────────
import requests
for label, url, method in [
    ("9991/con_notify (metodo nuevo)", f"http://{IP}:9991/con_notify", "POST"),
    ("8081/offer       (metodo viejo)", f"http://{IP}:8081/offer", "GET"),
]:
    try:
        r = requests.request(method, url, timeout=4)
        print(f"[OK ] {label}: HTTP {r.status_code} ({len(r.content)} bytes)")
    except Exception as e:
        print(f"[ERR] {label}: {type(e).__name__}: {e}")

# ── 2. Firma del constructor del SDK ────────────────────────────────
print()
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
sig = inspect.signature(UnitreeWebRTCConnection.__init__)
print(f"[SDK] Constructor: {sig}")
print(f"[SDK] Acepta aes_128_key? {'aes_128_key' in sig.parameters}")

# ── 3. Reproduce la construccion de core/connection.py ──────────────
print()
from config.config import ROBOT_AES_128_KEY
print(f"[CFG] ROBOT_AES_128_KEY presente? {bool(ROBOT_AES_128_KEY)} (len={len(ROBOT_AES_128_KEY)})")
conn_kwargs = {"ip": IP}
if ROBOT_AES_128_KEY:
    conn_kwargs["aes_128_key"] = ROBOT_AES_128_KEY
print(f"[CFG] kwargs que pasa core/connection.py: {list(conn_kwargs.keys())}")
try:
    UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, **conn_kwargs)
    print("[CFG] Construccion OK (no hubo TypeError)")
except TypeError as e:
    print(f"[CFG] >>> TypeError reproducido: {e}")
except Exception as e:
    print(f"[CFG] Otra excepcion: {type(e).__name__}: {e}")

# ── 4. Connect LocalSTA real (sin aes_128_key), con timeout ─────────
print("\n=== Intento de conexion LocalSTA real (timeout 25s) ===")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def _try_connect():
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=IP)
    await conn.connect()
    print(">>> CONECTADO. datachannel abierto.")
    await conn.disconnect()

try:
    asyncio.run(asyncio.wait_for(_try_connect(), timeout=25))
except asyncio.TimeoutError:
    print(">>> TIMEOUT: el connect no completo en 25s (ICE no convergio o sin respuesta).")
except SystemExit as e:
    print(f">>> SystemExit del SDK (rechazo/offline): code={e.code}")
except Exception as e:
    print(f">>> Fallo connect: {type(e).__name__}: {e}")
    traceback.print_exc()
