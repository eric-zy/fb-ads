from core.auth import AuthManager


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
