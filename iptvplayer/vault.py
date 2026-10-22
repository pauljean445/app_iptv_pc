"""Chiffrement de bout en bout de la source IPTV des profils, stockée dans le compte du foyer : seuls les appareils
qui ont saisi le mot de passe du compte peuvent la lire (pas Google / Firebase). Même format que l'appli TV
(data/Vault.kt) :
  clé  = PBKDF2-HMAC-SHA256(mot de passe, sel = "iptv-player/" + uid, 200 000 itérations, 32 octets)
  bloc = base64(nonce 12 octets || AES-256-GCM(JSON de la source)), données associées = "source/" + id du profil
La clé est calculée à la connexion (le mot de passe n'est pas gardé) puis conservée chiffrée par Windows (DPAPI).
"""
import base64
import hashlib
import json
import os

ITERATIONS = 200_000
KEYS = ("mode", "server", "username", "password", "stream_format", "url")  # champs de la source partagés


def derive_key(password: str, uid: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), f"iptv-player/{uid}".encode(), ITERATIONS, 32)


def encrypt(key: bytes, pid: str, data: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, json.dumps(data, ensure_ascii=False).encode("utf-8"), f"source/{pid}".encode())
    return base64.b64encode(nonce + sealed).decode()


def decrypt(key: bytes, pid: str, blob: str) -> dict | None:
    """None si le bloc ne se déchiffre pas avec cette clé (mot de passe changé depuis, données abîmées)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        raw = base64.b64decode(blob)
        data = json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], f"source/{pid}".encode()))
        return data if isinstance(data, dict) else None
    except (InvalidTag, ValueError, TypeError):
        return None
