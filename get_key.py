import hashlib
import time
import uuid
from curl_cffi import requests as cffi_requests
import json

EMAIL    = "divergencyai@gmail.com"
PASSWORD = "=WAs}r5iz5g5h/0"
SN       = "B42D1000PAHBJ3K5"

APP_SIGN_SECRET = "XyvkwK45hp5PHfA8"
BASE_URL = "https://global-robot-api.unitree.com/"

def make_headers(token=""):
    ts    = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign  = hashlib.md5(f"{APP_SIGN_SECRET}{ts}{nonce}".encode()).hexdigest()
    return {
        "Content-Type":    "application/x-www-form-urlencoded",
        "DeviceId":        "Samsung/Samsung/SM-S931B/s24/14/34",
        "DevicePlatform":  "Android",
        "DeviceModel":     "SM-S931B",
        "SystemVersion":   "34",
        "AppVersion":      "1.11.4",
        "AppLocale":       "en_US",
        "AppTimezone":     "GMT-05:00",
        "Channel":         "UMENG_CHANNEL",
        "User-Agent":      "Mozilla/5.0 (Linux; Android 14; SM-S931B Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.103 Mobile Safari/537.36",
        "AppTimestamp":    ts,
        "AppNonce":        nonce,
        "AppSign":         sign,
        "AppName":         "Go2",
        "Token":           token,
    }

session = cffi_requests.Session(impersonate="chrome120")

pwd_md5 = hashlib.md5(PASSWORD.encode()).hexdigest()
resp = session.post(BASE_URL + "login/email",
                    data={"email": EMAIL, "password": pwd_md5},
                    headers=make_headers())
resp.encoding = "utf-8"
data = resp.json()
print("Login code:", data.get("code"))
token = data.get("data", {}).get("accessToken", "")
if not token:
    print("Login failed:", json.dumps(data, indent=2, ensure_ascii=False))
    exit(1)
print("Token OK:", token[:20] + "...")

resp2 = session.get(BASE_URL + "device/bind/list",
                    headers=make_headers(token))
resp2.encoding = "utf-8"
devices_data = resp2.json()
print("\nRespuesta device/bind/list:")
print(json.dumps(devices_data, indent=2, ensure_ascii=False))

devices = devices_data.get("data") or []
if devices:
    for d in devices:
        sn  = d.get("sn", "")
        key = d.get("key") or d.get("gcm_key", "")
        print(f"\nSN: {sn}")
        print(f"AES key: {key}")
        if sn == SN:
            print("<<< ESTE ES NUESTRO ROBOT >>>")
else:
    print("\nNingún dispositivo vinculado a esta cuenta.")
