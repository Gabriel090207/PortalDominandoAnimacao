"""Synthetic passwords only; no persisted hashes, network or Firebase."""
import ast
from pathlib import Path

import pytest
from argon2 import PasswordHasher, Type

from app.services import admin_password_service as service

PASSWORD = "synthetic passphrase for tests"


def test_hash_random_salt_algorithm_and_roundtrip():
    first = service.hash_admin_password(PASSWORD)
    second = service.hash_admin_password(PASSWORD)
    assert first.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert first != second
    assert PASSWORD not in first and PASSWORD not in second
    assert service.verify_admin_password(PASSWORD, first)
    assert service.verify_admin_password(PASSWORD, second)
    assert not service.verify_admin_password("different synthetic passphrase", first)


@pytest.mark.parametrize("password", ["x"*15, "x"*256, "🌟"*256,
    "synthetic phrase with spaces", " synthetic passphrase ", "café synthetic passphrase"])
def test_valid_boundaries_unicode_and_spaces(password):
    encoded = service.hash_admin_password(password)
    assert service.verify_admin_password(password, encoded)
    if password.startswith(" "):
        assert not service.verify_admin_password(password.strip(), encoded)


def test_unicode_is_not_normalized():
    encoded = service.hash_admin_password("café synthetic passphrase")
    assert not service.verify_admin_password("cafe\u0301 synthetic passphrase", encoded)


@pytest.mark.parametrize("password", ["", "x"*14, "x"*257, b"synthetic passphrase",
    None, True, 1, [], {}, "\ud800"*15])
def test_invalid_password_policy_safe(password):
    for function in (service.hash_admin_password,
                     lambda value: service.verify_admin_password(value, "invalid")):
        with pytest.raises(service.AdminPasswordPolicyError) as error:
            function(password)
        assert "x"*14 not in str(error.value)
        assert "synthetic passphrase" not in str(error.value)
        assert error.value.__cause__ is None


@pytest.mark.parametrize("encoded", ["", "SYNTHETIC_BROKEN_HASH", None, b"bad", 1,
    "$argon2id$v=19$m=999999999,t=2,p=1$bad$bad"])
def test_corrupt_hash_is_not_password_mismatch(encoded):
    for function in (lambda value: service.verify_admin_password(PASSWORD, value),
                     service.needs_admin_password_rehash):
        with pytest.raises(service.InvalidAdminPasswordHashError) as error:
            function(encoded)
        assert PASSWORD not in str(error.value)
        assert "SYNTHETIC_BROKEN_HASH" not in repr(error.value)
        assert error.value.__cause__ is None


def test_rehash_old_parameters_verify_without_update():
    current = service.hash_admin_password(PASSWORD)
    old = PasswordHasher(type=Type.ID, memory_cost=8192, time_cost=1,
                         parallelism=1, hash_len=32, salt_len=16).hash(PASSWORD)
    assert not service.needs_admin_password_rehash(current)
    assert service.needs_admin_password_rehash(old)
    assert service.verify_admin_password(PASSWORD, old)


def test_other_argon_types_rejected():
    encoded = PasswordHasher(type=Type.I, memory_cost=8192, time_cost=1,
                             parallelism=1).hash(PASSWORD)
    with pytest.raises(service.InvalidAdminPasswordHashError):
        service.verify_admin_password(PASSWORD, encoded)


def test_no_io_environment_firebase_or_retained_password():
    source = Path(service.__file__).read_text()
    tree = ast.parse(source)
    assert all(node.module in {"base64", "binascii", "argon2", "argon2.exceptions"} for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom))
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"open", "print"} for node in ast.walk(tree))
    service.hash_admin_password(PASSWORD)
    assert PASSWORD not in [value for value in vars(service).values() if isinstance(value, str)]


def test_malformed_base64_with_valid_parameters_rejected():
    encoded = service.hash_admin_password(PASSWORD)
    parts = encoded.split("$")
    parts[4] = "!" * len(parts[4])
    malformed = "$".join(parts)
    for function in (service.needs_admin_password_rehash,
                     lambda value: service.verify_admin_password(PASSWORD, value)):
        with pytest.raises(service.InvalidAdminPasswordHashError):
            function(malformed)
