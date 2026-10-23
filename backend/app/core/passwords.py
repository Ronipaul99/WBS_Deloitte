from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
_DUMMY_HASH = password_hasher.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate_hash = password_hash or _DUMMY_HASH
    try:
        return password_hasher.verify(password, candidate_hash) and password_hash is not None
    except (TypeError, ValueError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    if len(password.encode("utf-8")) > 128:
        raise ValueError("Password must not exceed 128 bytes.")
