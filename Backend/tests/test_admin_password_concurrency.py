"""Deterministic capacity tests with events; no timing benchmarks or Firebase."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock
from unittest.mock import Mock

import pytest
from argon2.exceptions import VerificationError, VerifyMismatchError

from test_admin_domain import admin
from app.persistence.admin_records import AdminRecord
from app.services import admin_password_service as passwords
from app.services.admin_auth_service import AdminAuthService, AdminAuthenticationUnavailable, InvalidAdminCredentials

PASSWORD = "synthetic concurrency passphrase"


@pytest.fixture
def capacity(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Production Firebase forbidden")
    monkeypatch.setattr("firebase_admin.initialize_app", forbidden)
    monkeypatch.setattr("app.services.firebase_service.get_firestore_client", forbidden)
    gate = BoundedSemaphore(passwords.MAX_CONCURRENT_ADMIN_PASSWORD_VERIFICATIONS)
    monkeypatch.setattr(passwords, "_verification_slots", gate)
    return gate


@pytest.fixture(scope="module")
def encoded():
    return passwords.hash_admin_password(PASSWORD)


def assert_available(gate):
    assert gate.acquire(blocking=False)
    gate.release()


def replace_verifier(monkeypatch, verifier):
    proxy = Mock(wraps=passwords._HASHER)
    proxy.verify = verifier
    monkeypatch.setattr(passwords, "_HASHER", proxy)


def test_normal_success_and_mismatch_release_capacity(capacity, encoded):
    assert passwords.verify_admin_password(PASSWORD, encoded)
    assert_available(capacity)
    assert not passwords.verify_admin_password("different synthetic passphrase", encoded)
    assert_available(capacity)


@pytest.mark.parametrize("failure,expected", [
    (VerifyMismatchError("SYNTHETIC_PRIVATE"), None),
    (VerificationError("SYNTHETIC_PRIVATE"), passwords.InvalidAdminPasswordHashError),
    (RuntimeError("SYNTHETIC_PRIVATE"), passwords.AdminPasswordVerificationUnavailable),
    (KeyboardInterrupt(), KeyboardInterrupt),
])
def test_verifier_exceptions_release_capacity(capacity, encoded, monkeypatch, failure, expected, capsys, caplog):
    verifier = Mock(side_effect=failure)
    replace_verifier(monkeypatch, verifier)
    if expected is None:
        assert passwords.verify_admin_password(PASSWORD, encoded) is False
    else:
        with pytest.raises(expected) as caught:
            passwords.verify_admin_password(PASSWORD, encoded)
        assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert_available(capacity)
    output = capsys.readouterr()
    assert "SYNTHETIC_PRIVATE" not in output.out + output.err + caplog.text


def test_excess_requests_fail_without_waiting_or_entering_argon(capacity, encoded, monkeypatch, capsys, caplog):
    assert passwords.MAX_CONCURRENT_ADMIN_PASSWORD_VERIFICATIONS == 1
    entered, release = Event(), Event()
    lock = Lock()
    active = peak = 0
    real_verify = passwords._HASHER.verify
    def held_verify(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        entered.set()
        try:
            assert release.wait(timeout=10), "Test release event not received"
            return real_verify(*args)
        finally:
            with lock: active -= 1
    verifier = Mock(side_effect=held_verify)
    replace_verifier(monkeypatch, verifier)
    with ThreadPoolExecutor(max_workers=9) as pool:
        first = pool.submit(passwords.verify_admin_password, PASSWORD, encoded)
        try:
            assert entered.wait(timeout=5)
            excess = [pool.submit(passwords.verify_admin_password, PASSWORD, encoded) for _ in range(8)]
            # Completion while the first verifier is STILL held proves no
            # capacity queue. Timeouts are deadlock guards, not timing assertions.
            for result in excess:
                with pytest.raises(passwords.AdminPasswordVerificationUnavailable) as caught:
                    result.result(timeout=5)
                assert PASSWORD not in str(caught.value) and encoded not in str(caught.value)
            assert not first.done() and peak == active == 1
            assert verifier.call_count == 1
        finally:
            release.set()
        assert first.result(timeout=5) is True
    assert_available(capacity)
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err + caplog.text
    assert encoded not in output.out + output.err + caplog.text


def test_acquisition_is_explicitly_nonblocking(encoded, monkeypatch):
    gate = Mock()
    gate.acquire.return_value = False
    verifier = Mock()
    monkeypatch.setattr(passwords, "_verification_slots", gate)
    replace_verifier(monkeypatch, verifier)
    with pytest.raises(passwords.AdminPasswordVerificationUnavailable):
        passwords.verify_admin_password(PASSWORD, encoded)
    gate.acquire.assert_called_once_with(blocking=False)
    gate.release.assert_not_called()
    verifier.assert_not_called()


@pytest.mark.parametrize("kind", ["owner", "operator", "missing", "invalid_email", "short_password", "lookup_error"])
def test_real_and_dummy_auth_share_capacity_and_fail_as_unavailable(capacity, encoded, kind):
    repository, sessions = Mock(), Mock()
    record = AdminRecord(**admin(role="operator" if kind == "operator" else "owner").model_dump(), password_hash=encoded)
    repository.find_by_email.return_value = None if kind == "missing" else record
    if kind == "lookup_error": repository.find_by_email.side_effect = RuntimeError("SYNTHETIC_PRIVATE")
    auth = AdminAuthService(repository, sessions)
    assert capacity.acquire(blocking=False)
    try:
        with pytest.raises(AdminAuthenticationUnavailable) as caught:
            auth.authenticate("invalid" if kind == "invalid_email" else "admin@example.com",
                              "short" if kind == "short_password" else PASSWORD)
    finally:
        capacity.release()
    assert str(caught.value) == "Administrative authentication unavailable."
    assert caught.value.__cause__ is None
    sessions.create.assert_not_called()


@pytest.mark.parametrize("kind", ["owner", "operator", "missing", "wrong", "invalid_email", "disabled", "short"])
def test_auth_outcomes_and_dummy_checks_preserved(capacity, encoded, monkeypatch, kind):
    repository, sessions = Mock(), Mock()
    record = AdminRecord(**admin(role="operator" if kind == "operator" else "owner",
        status="disabled" if kind == "disabled" else "enabled").model_dump(), password_hash=encoded)
    repository.find_by_email.return_value = None if kind == "missing" else record
    auth = AdminAuthService(repository, sessions)
    verifier = Mock(wraps=passwords._HASHER.verify)
    replace_verifier(monkeypatch, verifier)
    email = "invalid" if kind == "invalid_email" else "admin@example.com"
    password = "short" if kind == "short" else "different synthetic passphrase" if kind == "wrong" else PASSWORD
    if kind in {"owner", "operator"}:
        def create_after_capacity_release(value):
            assert_available(capacity)
            return sessions.create.return_value
        sessions.create.side_effect = create_after_capacity_release
        assert auth.authenticate(email, password) is sessions.create.return_value
        sessions.create.assert_called_once_with(record.to_admin())
    else:
        with pytest.raises(InvalidAdminCredentials, match="Invalid administrative credentials"):
            auth.authenticate(email, password)
        sessions.create.assert_not_called()
    assert verifier.call_count == 1
    assert_available(capacity)


def test_distinct_auth_instances_share_real_and_dummy_limit(capacity, encoded, monkeypatch):
    real_repository, missing_repository = Mock(), Mock()
    real_repository.find_by_email.return_value = AdminRecord(**admin().model_dump(), password_hash=encoded)
    missing_repository.find_by_email.return_value = None
    first_sessions, second_sessions = Mock(), Mock()
    first = AdminAuthService(real_repository, first_sessions)
    second = AdminAuthService(missing_repository, second_sessions)
    entered, release = Event(), Event()
    real_verify = passwords._HASHER.verify
    def held_verify(*args):
        entered.set()
        assert release.wait(timeout=10)
        return real_verify(*args)
    replace_verifier(monkeypatch, Mock(side_effect=held_verify))
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(first.authenticate, "admin@example.com", PASSWORD)
        try:
            assert entered.wait(timeout=5)
            excess = pool.submit(second.authenticate, "missing@example.com", PASSWORD)
            with pytest.raises(AdminAuthenticationUnavailable):
                excess.result(timeout=5)
            second_sessions.create.assert_not_called()
        finally:
            release.set()
        assert running.result(timeout=5) is first_sessions.create.return_value
    assert_available(capacity)
