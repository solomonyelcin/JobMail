"""Encryption of OAuth refresh tokens at rest (Fernet / AES-128-CBC + HMAC)."""
from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, key: str):
        if not key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._f = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored token cannot be decrypted (wrong TOKEN_ENCRYPTION_KEY?)") from exc
