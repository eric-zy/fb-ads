from core.auth import AuthManager
from datetime import datetime, timedelta, timezone
import jwt
import pytest
from fastapi import HTTPException
from config.settings import settings


def test_password_hash_is_salted_and_verifiable():
    first = AuthManager.hash_password("correct horse battery staple")
    second = AuthManager.hash_password("correct horse battery staple")

    assert first != second
    assert first.startswith("pbkdf2_sha256$")
    assert AuthManager.verify_password("correct horse battery staple", first)
    assert not AuthManager.verify_password("wrong password", first)
    assert not AuthManager.needs_password_rehash(first)


def test_legacy_sha256_password_can_be_upgraded_at_login():
    import hashlib

    legacy = hashlib.sha256("legacy-password".encode("utf-8")).hexdigest()

    assert AuthManager.verify_password("legacy-password", legacy)
    assert AuthManager.needs_password_rehash(legacy)


@pytest.mark.parametrize("token", ["invalid-token", "a.b.c", ""])
def test_invalid_jwt_returns_unauthorized(token):
    with pytest.raises(HTTPException) as error:
        AuthManager.verify_token(token)
    assert error.value.status_code == 401


def test_jwt_rejects_bad_signature_missing_claims_and_expiry():
    now = datetime.now(timezone.utc)
    payload = {"sub": "auth-test", "iat": now, "exp": now + timedelta(minutes=5)}
    invalid = [jwt.encode(payload, "wrong-signing-key", algorithm="HS256"),
               jwt.encode({"sub": "auth-test"}, settings.SECRET_KEY, algorithm="HS256"),
               jwt.encode({**payload, "exp": now - timedelta(seconds=1)}, settings.SECRET_KEY, algorithm="HS256")]
    for token in invalid:
        with pytest.raises(HTTPException) as error:
            AuthManager.verify_token(token)
        assert error.value.status_code == 401
    assert AuthManager.verify_token(AuthManager.create_access_token({"sub": "auth-test"}))["sub"] == "auth-test"
