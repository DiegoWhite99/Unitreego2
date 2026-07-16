"""Decodifica la respuesta de con_notify para ver el 'data2' (modo del handshake).
  data2 == 1/ausente -> v1 (clave publica en claro)
  data2 == 2         -> v2 (data1 cifrado con clave fija conocida)
  data2 == 3         -> v3 (requiere la clave AES de la cuenta / cloud)
"""
import sys, base64, json, requests
IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.98"
r = requests.post(f"http://{IP}:9991/con_notify", timeout=5)
print("HTTP", r.status_code, "len", len(r.content))
decoded = base64.b64decode(r.text).decode("utf-8")
j = json.loads(decoded)
print("keys:", list(j.keys()))
print("data2 =", j.get("data2"), "  <-- modo del handshake")
d1 = j.get("data1", "")
print("data1 len:", len(d1))
print("data1 head:", repr(d1[:40]))
print("data1 tail:", repr(d1[-40:]))
print("¿parece PEM en claro? ->", "BEGIN" in d1)
