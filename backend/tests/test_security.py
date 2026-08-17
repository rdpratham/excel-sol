"""Unit tests for security utilities."""
import pytest
from jose import JWTError
import uuid

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_verify():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token = create_access_token(uid, "user@test.com", "admin")
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["email"] == "user@test.com"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_invalid_token_raises():
    with pytest.raises(JWTError):
        decode_access_token("not.a.jwt")


def test_refresh_token_hash():
    raw, h = generate_refresh_token()
    assert hash_refresh_token(raw) == h
    raw2, h2 = generate_refresh_token()
    assert h != h2  # each token is unique
