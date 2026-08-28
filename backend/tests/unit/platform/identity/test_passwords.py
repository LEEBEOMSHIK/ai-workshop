from ai_workshop.platform.identity.service import Argon2PasswordHasher


def test_argon2_hash_is_not_plaintext_and_verifies() -> None:
    hasher = Argon2PasswordHasher()

    password_hash = hasher.hash("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert hasher.verify("correct horse battery staple", password_hash) is True
    assert hasher.verify("wrong password", password_hash) is False
