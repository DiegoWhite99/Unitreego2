"""Prueba claves AES-128 comunes para descifrar la respuesta del robot (data2=3)."""
import base64
import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA1 = "GfQwN4VpJyp9ZaGuMs5eeYxG+pc+lZ5K1JFikkvuEIiqufnOJ8OxQCGvUq7Sy8S9GF+l/awDur4NNX7yBjv2hXcgvQp29919qkRv4a0WRjjkgiYVAbC7jNl75XTk8XV7Wh2PWHKwKOo+9Nnw8kKHkjkggcCDOkZ3O0pjj+P8UogISnUDgIspLicgOxnirNb9+SJD7DhZ1+c9NLCiQY7LlN3GoCceZAPmn8CWdjZKSd6P9lmGdCuwA43CBZ1Q/oCzJnfTzmhcgtWyNWISd0Otq9rSjBQIYEJBqz4+JVqTF9bl1She9M1JDKt6EQDk7/n8Vxmy7LMgx+bnJTUuG6kcbwv2RtW+u1QuG8bn7SW1Nx6IuBitIcG+u2gqs4ET/1Y2nAMgR9Pq67Shv7mSihiDLwMtuTZbIdfQ6vL3y75WBAu9B/FufUxPq3DHlQukg4uupOPZLDU36uwvOWHNN48hBxh18bf0b6edJVgRy2uDjjcLpMzQNjKOn1vvS0jU1k8GqKITSZ2BzlQV0cKziwwpURHLs1/xbDpRnhbENg/V2iOPJKp01OydgGVRaPD5O1RdQaNDtz4Em8o="

def try_decrypt(key_bytes: bytes, label: str) -> bool:
    try:
        data = base64.b64decode(DATA1)
        tag = data[-16:]
        nonce = data[-28:-16]
        ciphertext = data[:-28]
        aesgcm = AESGCM(key_bytes)
        plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None).decode('utf-8')
        print(f"EXITO con clave '{label}'!")
        print(f"Contenido descifrado (primeros 100): {plaintext[:100]}")
        return True
    except Exception:
        print(f"  Fallo: {label}")
        return False

# Claves candidatas comunes para Go2
keys = [
    (bytes(16),                                          "todo-ceros"),
    (bytes([0xFF]*16),                                   "todo-FF"),
    (b"1234567890123456",                                "1234..."),
    (b"unitree_go2_key_",                                "unitree_go2_key_"),
    (b"UnitreeRobotics1",                                "UnitreeRobotics1"),
    (b"go2airsecretkey1",                                "go2airsecretkey1"),
    (bytes([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]),   "1..16"),
    # Clave hardcodeada interna de la lib (data2==2)
    (bytes([232,86,130,189,22,84,155,0,142,4,166,104,43,179,235,227]), "lib-hardcoded"),
]

print("Probando claves AES-GCM para descifrar data1 del robot...\n")
found = False
for key, label in keys:
    if try_decrypt(key, label):
        found = True
        break

if not found:
    print("\nNinguna clave comun funciono.")
    print("Opciones:")
    print("  1. Hacer reset fisico del robot (boton 10s al encender)")
    print("  2. Obtener la clave desde la app Unitree en el celular")
    print("  3. Contactar soporte Unitree con el numero de serie")
