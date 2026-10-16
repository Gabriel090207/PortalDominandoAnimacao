"""Session service + repository with isolated atomic in-memory transactions."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock

import pytest

from commerce_fake import Client, Transaction
from test_admin_domain import admin, START
from app.persistence.admin_records import AdminRecord, AdminSessionRecord
from app.persistence.admin_sessions_repository import AdminSessionsRepository
from app.services.admin_password_service import hash_admin_password
from app.services.admin_session_service import AdminSessionService, AdminSessionServiceError


def admin_document():
    return AdminRecord(**admin().model_dump(),
        password_hash=hash_admin_password("synthetic session admin password")).to_document()


@pytest.fixture
def sessions(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Production Firebase forbidden")
    monkeypatch.setattr("firebase_admin.initialize_app", forbidden)
    monkeypatch.setattr("app.services.firebase_service.get_firestore_client", forbidden)
    client = Client()
    client.data["admins/synthetic-admin"] = admin_document()
    client.transaction = lambda: Transaction(client)
    lock = Lock()
    def transactional(callback):
        def run(transaction, *args):
            with lock:
                result = callback(transaction, *args)
                transaction.commit()
                return result
        return run
    monkeypatch.setattr("app.persistence.admin_sessions_repository.firestore.transactional", transactional)
    return client, AdminSessionService(AdminSessionsRepository(client))


def token_of(issued):
    return issued.token.get_secret_value()


def test_creation_digest_contract_and_boundaries(sessions, capsys, caplog):
    client, service = sessions
    issued = service.create(admin(), now=START)
    token = token_of(issued)
    assert len(token) == 64
    path = next(path for path in client.data if path.startswith("admin_sessions/"))
    assert token not in path and token not in str(client.data)
    record = AdminSessionRecord.from_document(client.data[path])
    assert record.to_session() == issued.session
    assert record.expires_at - record.created_at == timedelta(hours=8)
    assert service.get_session(token) == issued.session
    assert service.validate(token, now=START) == admin()
    assert service.validate(token, now=record.expires_at-timedelta(microseconds=1)) == admin()
    for now in (START-timedelta(microseconds=1), record.expires_at, record.expires_at+timedelta(seconds=1)):
        assert service.validate(token, now=now) is None
    assert service.validate(token, now=START, expected_admin_id="other") is None
    assert token not in repr(issued) and token not in repr(issued.token)
    output = capsys.readouterr()
    assert token not in output.out + output.err + caplog.text


@pytest.mark.parametrize("token", [None, "", "x", "a/b", "A"*64, "a"*63, "a"*65, [], {}, 1])
def test_invalid_tokens_never_access_storage(sessions, monkeypatch, token):
    _, service = sessions
    def forbidden(*args, **kwargs):
        raise AssertionError("Malformed token must not access storage")
    monkeypatch.setattr(service.repository, "lookup", forbidden)
    monkeypatch.setattr(service.repository, "revoke", forbidden)
    assert service.get_session(token) is None
    assert service.validate(token, now=START) is None
    assert service.revoke(token, now=START) is False


def test_unknown_token(sessions):
    _, service = sessions
    assert service.validate("0"*64, now=START) is None
    assert service.revoke("0"*64, now=START) is False


@pytest.mark.parametrize("change", [{"status":"disabled"}, {"auth_version":2}, {"admin_id":"other"}])
def test_current_admin_changes_reject_session(sessions, change):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    client.data["admins/synthetic-admin"].update(change)
    if "admin_id" in change:
        with pytest.raises(AdminSessionServiceError):
            service.validate(token, now=START)
    else:
        assert service.validate(token, now=START) is None


def test_missing_admin_and_stale_issuance(sessions):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    client.data["admins/synthetic-admin"]["auth_version"] = 2
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminSessionServiceError):
        service.create(admin(), now=START)
    assert client.data == before
    del client.data["admins/synthetic-admin"]
    assert service.validate(token, now=START) is None
    with pytest.raises(AdminSessionServiceError):
        service.create(admin(), now=START)


def test_revocation_idempotent_and_preserves_provenance(sessions):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    assert service.revoke(token, now=START+timedelta(minutes=1), reason="manual_revocation")
    before = copy.deepcopy(client.data)
    assert not service.revoke(token, now=START+timedelta(minutes=2))
    assert client.data == before
    assert service.validate(token, now=START+timedelta(minutes=3)) is None
    assert service.get_session(token).revocation_reason == "manual_revocation"


def test_collision_never_overwrites_and_has_bounded_retries(sessions, monkeypatch):
    client, service = sessions
    monkeypatch.setattr("app.services.admin_session_service.secrets.token_hex", lambda size: "1"*64)
    service.create(admin(), now=START)
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminSessionServiceError, match="unique session"):
        service.create(admin(), now=START)
    assert client.data == before


def test_collision_retries_with_new_token(sessions, monkeypatch):
    client, service = sessions
    values = iter(["1"*64, "1"*64, "2"*64])
    monkeypatch.setattr("app.services.admin_session_service.secrets.token_hex", lambda size: next(values))
    first = service.create(admin(), now=START)
    second = service.create(admin(), now=START)
    assert token_of(first) != token_of(second)
    assert len(client.data) == 3


def test_concurrent_revoke_only_one_change(sessions):
    _, service = sessions
    token = token_of(service.create(admin(), now=START))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: service.revoke(token, now=START), range(2)))
    assert sorted(outcomes) == [False, True]


@pytest.mark.parametrize("operation", ["create", "lookup", "revoke"])
def test_storage_failures_are_sanitized(sessions, monkeypatch, operation, caplog, capsys):
    _, service = sessions
    token = token_of(service.create(admin(), now=START))
    def failure(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE " + token)
    monkeypatch.setattr(service.repository, operation, failure)
    with pytest.raises(AdminSessionServiceError) as error:
        if operation == "create": service.create(admin(), now=START)
        elif operation == "lookup": service.validate(token, now=START)
        else: service.revoke(token, now=START)
    assert token not in str(error.value) and "SYNTHETIC_PRIVATE" not in str(error.value)
    assert error.value.__cause__ is None
    output = capsys.readouterr()
    assert token not in output.out + output.err + caplog.text


def test_bad_records_fail_closed(sessions):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    path = next(path for path in client.data if path.startswith("admin_sessions/"))
    client.data[path]["expires_at"] = START+timedelta(hours=9)
    for operation in (lambda: service.validate(token, now=START), lambda: service.revoke(token, now=START)):
        with pytest.raises(AdminSessionServiceError): operation()


def test_ineligible_and_naive_clock_do_not_write(sessions):
    client, service = sessions
    before = copy.deepcopy(client.data)
    for value in (None, admin(status="disabled")):
        with pytest.raises(AdminSessionServiceError): service.create(value, now=START)
    with pytest.raises(AdminSessionServiceError): service.create(admin(), now=START.replace(tzinfo=None))
    token = token_of(service.create(admin(), now=START))
    after = copy.deepcopy(client.data)
    with pytest.raises(AdminSessionServiceError): service.revoke(token, now=START-timedelta(seconds=1))
    with pytest.raises(AdminSessionServiceError): service.revoke(token, reason="unknown", now=START)
    assert client.data == after
    assert len(before) == 1


def test_random_sessions_are_independent(sessions):
    client, service = sessions
    issued = [service.create(admin(), now=START) for _ in range(10)]
    tokens = [token_of(item) for item in issued]
    assert len(set(tokens)) == 10
    assert len([path for path in client.data if path.startswith("admin_sessions/")]) == 10
    assert service.revoke(tokens[0], now=START)
    assert service.validate(tokens[0], now=START) is None
    assert all(service.validate(token, now=START) == admin() for token in tokens[1:])


def test_commit_failure_leaves_no_session_and_sanitizes(sessions, monkeypatch):
    client, service = sessions
    before = copy.deepcopy(client.data)
    def fail(transaction):
        raise RuntimeError("SYNTHETIC_PRIVATE_COMMIT")
    monkeypatch.setattr(Transaction, "commit", fail)
    with pytest.raises(AdminSessionServiceError) as error:
        service.create(admin(), now=START)
    assert client.data == before
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
