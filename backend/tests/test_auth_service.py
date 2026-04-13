import time
from unittest.mock import patch

import pytest
from jose import jwt

from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import settings


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "test_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)
        assert not verify_password("wrong_password", hashed)

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_same_password_different_salts(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        # bcrypt uses random salt, so hashes should differ
        assert h1 != h2
        # but both should verify
        assert verify_password("same_password", h1)
        assert verify_password("same_password", h2)

    def test_unicode_password(self):
        password = "pässwörd_ñ_日本"
        hashed = hash_password(password)
        assert verify_password(password, hashed)
        assert not verify_password("plain_ascii", hashed)

    def test_empty_string_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("notempty", hashed)


class TestAccessToken:
    def test_roundtrip(self):
        token = create_access_token(user_id=42, role="rider")
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["role"] == "rider"
        assert payload["type"] == "access"

    def test_driver_role(self):
        token = create_access_token(user_id=10, role="driver")
        payload = decode_token(token)
        assert payload["sub"] == "10"
        assert payload["role"] == "driver"

    def test_admin_role(self):
        token = create_access_token(user_id=1, role="admin")
        payload = decode_token(token)
        assert payload["role"] == "admin"

    def test_has_expiry(self):
        token = create_access_token(user_id=1, role="rider")
        payload = decode_token(token)
        assert "exp" in payload
        assert payload["exp"] > time.time()


class TestRefreshToken:
    def test_roundtrip(self):
        token = create_refresh_token(user_id=42)
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"

    def test_no_role_in_refresh(self):
        token = create_refresh_token(user_id=42)
        payload = decode_token(token)
        assert "role" not in payload

    def test_has_expiry(self):
        token = create_refresh_token(user_id=1)
        payload = decode_token(token)
        assert "exp" in payload
        assert payload["exp"] > time.time()


class TestDecodeToken:
    def test_invalid_token_string(self):
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token("invalid.token.here")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token("")

    def test_tampered_payload(self):
        token = create_access_token(user_id=42, role="rider")
        # tamper with the payload section
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # reverse the payload
        tampered = ".".join(parts)
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(tampered)

    def test_wrong_secret_key(self):
        # Create a token with a different secret
        payload = {"sub": "42", "role": "rider", "type": "access"}
        token = jwt.encode(payload, "wrong-secret-key", algorithm=settings.jwt_algorithm)
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(token)
