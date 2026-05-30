"""Prueba varios endpoints de login en Unitree Cloud."""
import getpass
import hashlib
import time
import requests
import urllib.parse
import json

TARGET_SN = "B42D1000PAHBJ3K5"
BASE_URL   = "https://global-robot-api.unitree.com/"

def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()

def _base_headers(token: str = "", content_type: str = None) -> dict:
    ts    = str(int(round(time.time() * 1000)))
    nonce = _md5(ts)
    sign  = _md5(f"XyvkwK45hp5PHfA8{ts}{nonce}")
    h = {
        "DeviceId":       "Samsung/GalaxyS20/SM-G981B/s20/10/29",
        "AppTimezone":    "GMT-05:00",
        "DevicePlatform": "Android",
        "AppVersion":     "2.1.0",
        "AppLocale":      "en_US",
        "AppTimestamp":   ts,
        "AppNonce":       nonce,
        "AppSign":        sign,
        "Channel":        "UMENG_CHANNEL",
        "Token":          token,
        "AppName":        "Go2",
        "User-Agent":     "okhttp/4.9.3",
    }
    if content_type:
        h["Content-Type"] = content_type
    return h

def try_login(email: str, password_md5: str) -> str | None:
    attempts = [
        ("POST", "login/email",         urllib.parse.urlencode({"email": email, "password": password_md5}), "application/x-www-form-urlencoded"),
        ("POST", "login/email",         json.dumps({"email": email, "password": password_md5}),              "application/json"),
        ("GET",  "login/email",         None, None),
        ("POST", "v2/login/email",      urllib.parse.urlencode({"email": email, "password": password_md5}), "application/x-www-form-urlencoded"),
        ("POST", "user/login",          urllib.parse.urlencode({"email": email, "password": password_md5}), "application/x-www-form-urlencoded"),
        ("POST", "account/loginByEmail",urllib.parse.urlencode({"email": email, "password": password_md5}), "application/x-www-form-urlencoded"),
    ]
    for method, path, body, ct in attempts:
        url = BASE_URL + path
        hdrs = _base_headers(content_type=ct)
        try:
            if method == "GET":
                r = requests.get(url, params={"email": email, "password": password_md5}, headers=hdrs, timeout=8)
            else:
                r = requests.post(url, data=body, headers=hdrs, timeout=8)
            print(f"  {method} {path} → {r.status_code}: {r.text[:120]}")
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                if data.get("code") == 100:
                    token = data.get("data", {}).get("accessToken")
                    if token:
                        print(f"\n  LOGIN OK — token: {token[:20]}...")
                        return token
        except Exception as e:
            print(f"  {method} {path} → ERROR: {e}")
    return None

if __name__ == "__main__":
    print("=" * 60)
    print("  RECUPERAR CLAVE AES-128 DESDE UNITREE CLOUD")
    print("=" * 60)
    email    = input("Email: ").strip()
    password = getpass.getpass("Contrasena: ")
    pwd_md5  = _md5(password)

    print("\nProbando endpoints de login...\n")
    token = try_login(email, pwd_md5)

    if token:
        print("\n--- BUSCANDO DISPOSITIVOS ---")
        for path in ["robot/list", "device/list", "robot/page", "user/robot"]:
            r = requests.get(BASE_URL + path, headers=_base_headers(token=token), timeout=8)
            print(f"  GET {path} → {r.status_code}: {r.text[:200]}")
    else:
        print("\nNo se pudo hacer login.")
        print("La API de Unitree Cloud puede haber cambiado.")
        print("\nAlternativa directa: reset fisico del robot.")
        print("Mantener boton encendido presionado al arrancar ~8-10 segundos.")
