"""Intenta descifrar data1 del robot usando claves AES derivadas del SN y MAC."""
import base64
import hashlib
import hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SN  = "B42D1000PAHBJ3K5"
MAC = "fc23cd997449"  # sin separadores

DATA1 = "GfQwN4VpJyp9ZaGuMs5eeYxG+pc+lZ5K1JFikkvuEIiqufnOJ8OxQCGvUq7Sy8S9GF+l/awDur4NNX7yBjv2hXcgvQp29919qkRv4a0WRjjkgiYVAbC7jNl75XTk8XV7Wh2PWHKwKOo+9Nnw8kKHkjkggcCDOkZ3O0pjj+P8UogISnUDgIspLicgOxnirNb9+SJD7DhZ1+c9NLCiQY7LlN3GoCceZAPmn8CWdjZKSd6P9lmGdCuwA43CBZ1Q/oCzJnfTzmhcgtWyNWISd0Otq9rSjBQIYEJBqz4+JVqTF9bl1She9M1JDKt6EQDk7/n8Vxmy7LMgx+bnJTUuG6kcbwv2RtW+u1QuG8bn7SW1Nx6IuBitIcG+u2gqs4ET/1Y2nAMgR9Pq67Shv7mSihiDLwMtuTZbIdfQ6vL3y75WBAu9B/FufUxPq3DHlQukg4uupOPZLDU36uwvOWHNN48hBxh18bf0b6edJVgRy2uDjjcLpMzQNjKOn1vvS0jU1k8GqKITSZ2BzlQV0cKziwwpURHLs1/xbDpRnhbENg/V2iOPJKp01OydgGVRaPD5O1RdQaNDtz4Em8o="

def try_decrypt(key_bytes: bytes, label: str) -> bool:
    if len(key_bytes) != 16:
        return False
    try:
        data = base64.b64decode(DATA1)
        tag        = data[-16:]
        nonce      = data[-28:-16]
        ciphertext = data[:-28]
        aesgcm = AESGCM(key_bytes)
        plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None).decode('utf-8')
        print(f"\n*** EXITO con clave '{label}' ***")
        print(f"Contenido: {plaintext[:120]}")
        return True
    except Exception:
        print(f"  Fallo: {label}")
        return False

def md5(s: str) -> bytes:
    return hashlib.md5(s.encode()).digest()

def sha16(s: str) -> bytes:
    return hashlib.sha256(s.encode()).digest()[:16]

def hm(key: str, msg: str) -> bytes:
    return hmac.new(key.encode(), msg.encode(), hashlib.md5).digest()

candidates = [
    (md5(SN),                    "MD5(SN)"),
    (md5(MAC),                   "MD5(MAC)"),
    (md5(SN + MAC),              "MD5(SN+MAC)"),
    (md5(MAC + SN),              "MD5(MAC+SN)"),
    (sha16(SN),                  "SHA256[:16](SN)"),
    (sha16(MAC),                 "SHA256[:16](MAC)"),
    (sha16(SN + MAC),            "SHA256[:16](SN+MAC)"),
    (md5(SN.lower()),            "MD5(sn-lower)"),
    (md5(SN[:8]),                "MD5(SN-primera-mitad)"),
    (md5(SN[8:]),                "MD5(SN-segunda-mitad)"),
    (md5("unitree" + SN),        "MD5(unitree+SN)"),
    (md5("go2" + SN),            "MD5(go2+SN)"),
    (md5(SN + "unitree"),        "MD5(SN+unitree)"),
    (hm(SN, MAC),                "HMAC-MD5(key=SN, msg=MAC)"),
    (hm(MAC, SN),                "HMAC-MD5(key=MAC, msg=SN)"),
]

print(f"Probando {len(candidates)} claves derivadas de SN y MAC...\n")
found = False
for key, label in candidates:
    if try_decrypt(key, label):
        found = True
        break

if not found:
    print("\nNinguna derivacion funciono.")
    print("La clave AES es aleatoria y unica — no deriva del SN/MAC.")
    print("\nOpciones:")
    print("  1. Recuperar desde cuenta Unitree Cloud (si el robot estaba registrado)")
    print("  2. Reset fisico: mantener boton encendido ~10s al arrancar")
    print("  3. Email a support@unitree.com con SN: B42D1000PAHBJ3K5")
