"""Encryption of OAuth refresh tokens at rest (Fernet / AES-128-CBC + HMAC)."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet_key(secret: str) -> bytes:
    """Use a valid Fernet key as-is; otherwise derive one from any long random string."""
    try:
        Fernet(secret.encode())
        return secret.encode()
    except ValueError:
        pass
    if len(secret) < 24:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a random string of at least 24 characters.")
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


class TokenCipher:
    def __init__(self, key: str):
        key = (key or "").strip()
        if not key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set. Use any random string of 24+ characters, or generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._f = Fernet(_fernet_key(key))

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored token cannot be decrypted (wrong TOKEN_ENCRYPTION_KEY?)") from exc
