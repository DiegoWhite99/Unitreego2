import requests, base64, json

url = 'http://192.168.123.161:9991/con_notify'
print(f'POST a {url}...')
try:
    r = requests.post(url, data=None, timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Raw (primeros 200): {r.text[:200]}')
    try:
        decoded = base64.b64decode(r.text).decode('utf-8')
        parsed = json.loads(decoded)
        print(f'data2: {parsed.get("data2")}')
        print(f'data1 (primeros 80): {str(parsed.get("data1", ""))[:80]}')
    except Exception as e:
        print(f'No es base64/JSON valido: {e}')
except Exception as e:
    print(f'Error de conexion: {e}')
