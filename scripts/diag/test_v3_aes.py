"""¿La clave AES del .env descifra el data1 v3 del robot?

Si el resultado contiene un PEM/clave publica -> la clave AES es VALIDA y el
handshake v3 usa ese esquema. Si sale basura/error -> clave invalida o esquema
distinto (robot no vinculado a la cuenta, clave caduca, etc.).
"""
import sys, os, base64, json, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config.config import ROBOT_AES_128_KEY
KEY = ROBOT_AES_128_KEY
IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.98"
print(f"Clave AES: {KEY!r}  (len={len(KEY)})")

r = requests.post(f"http://{IP}:9991/con_notify", timeout=6)
j = json.loads(base64.b64decode(r.text).decode("utf-8"))
data1, data2 = j.get("data1"), j.get("data2")
print(f"data2={data2}  data1 len={len(data1)}\n")

def looks_like_key(s: str) -> bool:
    return ("BEGIN" in s) or ("MII" in s) or ("PUBLIC" in s)

# Intento 1: AES-256-ECB (mismo esquema que aes_decrypt del SDK) -------
from Crypto.Cipher import AES
try:
    raw = base64.b64decode(data1)
    cipher = AES.new(KEY.encode("utf-8"), AES.MODE_ECB)
    dec = cipher.decrypt(raw)
    # quita padding tipo PKCS
    try:
        dec_s = dec[:-dec[-1]].decode("utf-8", "replace")
    except Exception:
        dec_s = dec.decode("utf-8", "replace")
    print("[ECB-256] resultado (primeros 120):", repr(dec_s[:120]))
    print("[ECB-256] ¿parece clave? ->", looks_like_key(dec_s), "\n")
except Exception as e:
    print(f"[ECB-256] error: {type(e).__name__}: {e}\n")

# Intento 2: AES-GCM con clave de 32 bytes (layout de decrypt_con_notify_data)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
for keylen, kbytes in (("32B", KEY.encode()), ("16B-hex", bytes.fromhex(KEY))):
    try:
        data = base64.b64decode(data1)
        tag, nonce, ct = data[-16:], data[-28:-16], data[:-28]
        pt = AESGCM(kbytes).decrypt(nonce, ct + tag, None).decode("utf-8", "replace")
        print(f"[GCM-{keylen}] resultado (primeros 120):", repr(pt[:120]))
        print(f"[GCM-{keylen}] ¿parece clave? ->", looks_like_key(pt))
    except Exception as e:
        print(f"[GCM-{keylen}] error: {type(e).__name__}: {e}")
