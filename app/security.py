import base64
import hashlib

from cryptography.fernet import Fernet

from .config import get_settings

settings = get_settings()


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str | None) -> str | None:
    if plain is None:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        return None
