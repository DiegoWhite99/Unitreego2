"""Parche v3 para el handshake LocalSTA del Go2 (firmware con con_notify data2==3).

El SDK instalado (unitree_webrtc_connect 2.x) solo entiende con_notify v1/v2.
El robot de este lab responde data2==3: el `data1` viene cifrado con AES-128-GCM
usando la clave AES de la cuenta (ROBOT_AES_128_KEY: 32 hex -> 16 bytes; layout
`ciphertext | nonce(12) | tag(16)`). Aqui reemplazamos send_sdp_to_local_peer por
una version que descifra ese data1 y completa el handshake.

Verificado 2026-06-05: con la clave del .env, el data1 v3 descifra a un PEM RSA
valido. Si algun dia el robot vuelve a v1/v2, esta misma funcion lo cubre.
"""
from __future__ import annotations

import base64
import json
import logging

from config.config import ROBOT_AES_128_KEY


def _decrypt_v3_data1(b64: str, aes_key_hex: str) -> str:
    """Descifra el data1 v3: AES-128-GCM, clave = hex->16 bytes, ct|nonce|tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = bytes.fromhex(aes_key_hex)            # 32 hex chars -> 16 bytes (AES-128)
    data = base64.b64decode(b64)
    tag, nonce, ct = data[-16:], data[-28:-16], data[:-28]
    return AESGCM(key).decrypt(nonce, ct + tag, None).decode("utf-8")


def _send_sdp_local_v3(ip: str, sdp: str) -> str | None:
    """send_sdp_to_local_peer_new_method, pero con rama data2==3 (v3)."""
    from unitree_webrtc_connect.unitree_auth import (
        _calc_local_path_ending, make_local_request, decrypt_con_notify_data,
    )
    from unitree_webrtc_connect.encryption import (
        aes_encrypt, rsa_encrypt, generate_aes_key, rsa_load_public_key, aes_decrypt,
    )

    # 1) con_notify -> clave publica (cifrada segun la version del firmware).
    url = f"http://{ip}:9991/con_notify"
    response = make_local_request(url, body=None, headers=None)
    if not response:
        raise ValueError("con_notify sin respuesta")

    dj = json.loads(base64.b64decode(response.text).decode("utf-8"))
    data1, data2 = dj.get("data1"), dj.get("data2")

    if data2 == 2:
        data1 = decrypt_con_notify_data(data1)          # v2: clave fija (SDK)
    elif data2 == 3:
        if not ROBOT_AES_128_KEY:
            raise ValueError("Handshake v3 requiere ROBOT_AES_128_KEY y esta vacia")
        data1 = _decrypt_v3_data1(data1, ROBOT_AES_128_KEY)  # v3: clave de cuenta
    # data2 == 1 / ausente -> data1 ya viene en claro

    public_key_pem = data1[10:len(data1) - 10]
    path_ending = _calc_local_path_ending(data1)

    # 2) Generamos clave de sesion, ciframos el SDP y lo mandamos a con_ing_*.
    session_key = generate_aes_key()
    public_key = rsa_load_public_key(public_key_pem)
    body = {
        "data1": aes_encrypt(sdp, session_key),
        "data2": rsa_encrypt(session_key, public_key),
    }
    url = f"http://{ip}:9991/con_ing_{path_ending}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = make_local_request(url, body=json.dumps(body), headers=headers)
    if response:
        return aes_decrypt(response.text, session_key)
    return None


def _patched_send_sdp_to_local_peer(ip: str, sdp: str):
    """Reemplazo de send_sdp_to_local_peer: va directo al metodo nuevo (9991),
    que es el unico que existe en este firmware y el que soporta v3."""
    try:
        return _send_sdp_local_v3(ip, sdp)
    except Exception as e:
        logging.error(f"[v3 patch] handshake local fallo: {e}")
        return None


_applied = False


def apply_v3_patch() -> None:
    """Monkey-patch idempotente de send_sdp_to_local_peer en el SDK."""
    global _applied
    if _applied:
        return
    import unitree_webrtc_connect.unitree_auth as ua
    import unitree_webrtc_connect.webrtc_driver as drv
    ua.send_sdp_to_local_peer = _patched_send_sdp_to_local_peer
    drv.send_sdp_to_local_peer = _patched_send_sdp_to_local_peer  # el driver tiene su propia ref
    _applied = True
    logging.info("[v3 patch] send_sdp_to_local_peer parcheado para con_notify v3")
