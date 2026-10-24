from cryptography.fernet import Fernet

from app.crypto import TokenCipher


def test_accepts_fernet_key():
    c = TokenCipher(Fernet.generate_key().decode())
    assert c.decrypt(c.encrypt("hello")) == "hello"


def test_accepts_any_long_random_string_deterministically():
    secret = "some-long-random-string-1234567890"
    token = TokenCipher(secret).encrypt("refresh")
    assert TokenCipher(secret).decrypt(token) == "refresh"
    assert "refresh" not in token


def test_rejects_short_or_empty_keys():
    for bad in ("", "short", "   "):
        try:
            TokenCipher(bad)
        except RuntimeError:
            continue
        raise AssertionError(f"accepted {bad!r}")
