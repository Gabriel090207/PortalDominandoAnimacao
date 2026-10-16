"""Synchronous password cryptography only; no environment, persistence or logs.

Future async callers must offload this work. Verification has a process-local
nonblocking capacity limit; password hashing/provisioning remains unchanged.
Parameters are an initial interactive baseline, not a Render benchmark.
"""
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from threading import BoundedSemaphore

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import (
    HashingError, InvalidHashError, VerificationError, VerifyMismatchError,
)

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 256
MAX_PASSWORD_BYTES = 1024
MAX_CONCURRENT_ADMIN_PASSWORD_VERIFICATIONS = 1
_verification_slots = BoundedSemaphore(MAX_CONCURRENT_ADMIN_PASSWORD_VERIFICATIONS)

_HASHER = PasswordHasher(
    type=Type.ID, memory_cost=19456, time_cost=2, parallelism=1,
    hash_len=32, salt_len=16, encoding="utf-8",
)


class AdminPasswordPolicyError(ValueError):
    """Invalid password input; messages never contain input."""


class InvalidAdminPasswordHashError(ValueError):
    """Stored hash is unsupported, malformed or corrupt."""


class AdminPasswordHashingError(RuntimeError):
    """Cryptographic operation failed."""


class AdminPasswordVerificationUnavailable(RuntimeError):
    """No verification capacity or unexpected verifier failure; never a mismatch."""


def _validate_password(password):
    if type(password) is not str or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AdminPasswordPolicyError("Invalid administrative password policy.")
    try:
        size = len(password.encode("utf-8"))
    except UnicodeError:
        raise AdminPasswordPolicyError("Invalid administrative password encoding.") from None
    if size > MAX_PASSWORD_BYTES:
        raise AdminPasswordPolicyError("Invalid administrative password size.")


def _validate_hash(encoded_hash):
    # Bound input and encoded work factors before verification to avoid an
    # unbounded allocation if storage is corrupt. Retuning may expand these caps.
    if type(encoded_hash) is not str or not encoded_hash.isascii() or len(encoded_hash) > 1024:
        raise InvalidAdminPasswordHashError("Invalid stored administrative password hash.")
    try:
        parameters = extract_parameters(encoded_hash)
        parts = encoded_hash.split("$")
        if len(parts) != 6:
            raise ValueError
        for part, expected_size in ((parts[4], parameters.salt_len), (parts[5], parameters.hash_len)):
            decoded = b64decode(part + "=" * (-len(part) % 4), validate=True)
            if len(decoded) != expected_size or b64encode(decoded).decode("ascii").rstrip("=") != part:
                raise ValueError
        if (parameters.type != Type.ID or parameters.version != 19
            or not 1 <= parameters.time_cost <= 10
            or not 1 <= parameters.parallelism <= 8
            or not 8 * parameters.parallelism <= parameters.memory_cost <= 262144
            or not 8 <= parameters.salt_len <= 64
            or not 16 <= parameters.hash_len <= 64):
            raise ValueError
    except (InvalidHashError, ValueError, TypeError, Base64Error):
        raise InvalidAdminPasswordHashError("Invalid stored administrative password hash.") from None


def hash_admin_password(password: str) -> str:
    _validate_password(password)
    try:
        return _HASHER.hash(password)
    except HashingError:
        raise AdminPasswordHashingError("Administrative password hashing failed.") from None


def verify_admin_password(password: str, encoded_hash: str) -> bool:
    _validate_password(password)
    _validate_hash(encoded_hash)
    if not _verification_slots.acquire(blocking=False):
        raise AdminPasswordVerificationUnavailable("Administrative password verification unavailable.")
    try:
        try:
            return _HASHER.verify(encoded_hash, password)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError):
            raise InvalidAdminPasswordHashError("Invalid stored administrative password hash.") from None
        except Exception:
            raise AdminPasswordVerificationUnavailable("Administrative password verification unavailable.") from None
    finally:
        _verification_slots.release()


def needs_admin_password_rehash(encoded_hash: str) -> bool:
    """Inspect parameters only; caller must first successfully verify the hash."""
    _validate_hash(encoded_hash)
    try:
        return _HASHER.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        raise InvalidAdminPasswordHashError("Invalid stored administrative password hash.") from None
