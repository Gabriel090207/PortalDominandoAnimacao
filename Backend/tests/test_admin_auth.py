"""Synthetic credentials and injected mocks only; no Firebase access."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from test_admin_domain import admin
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_repository import AdminRepository, AdminLookupError
from app.services import admin_auth_service as auth
from app.services.admin_password_service import hash_admin_password, verify_admin_password

PASSWORD = "synthetic authentication passphrase"


@pytest.fixture(scope="module")
def encoded():
    return hash_admin_password(PASSWORD)


@pytest.fixture
def setup_auth(encoded, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Production Firebase forbidden")
    monkeypatch.setattr("firebase_admin.initialize_app", forbidden)
    monkeypatch.setattr("app.services.firebase_service.get_firestore_client", forbidden)
    record = AdminRecord(**admin().model_dump(), password_hash=encoded)
    repository, sessions = Mock(), Mock()
    repository.find_by_email.return_value = record
    service = auth.AdminAuthService(repository, sessions)
    return service, repository, sessions, record


@pytest.mark.parametrize("role", ["owner", "operator"])
def test_success_normalizes_and_uses_existing_session_service(setup_auth, encoded, role):
    service, repository, sessions, _ = setup_auth
    record = AdminRecord(**admin(role=role).model_dump(), password_hash=encoded)
    repository.find_by_email.return_value = record
    result = service.authenticate(" ADMIN@EXAMPLE.COM ", PASSWORD)
    assert result is sessions.create.return_value
    repository.find_by_email.assert_called_once_with("admin@example.com")
    sessions.create.assert_called_once_with(record.to_admin())
    assert "password_hash" not in sessions.create.call_args.args[0].model_dump()


@pytest.mark.parametrize("kind", ["missing", "wrong_password", "invalid_email", "disabled", "short", "oversized", "bad_type"])
def test_generic_failure_and_no_session(setup_auth, kind, monkeypatch, encoded, caplog, capsys):
    service, repository, sessions, _ = setup_auth
    email, password = "admin@example.com", PASSWORD
    if kind == "missing": repository.find_by_email.return_value = None
    elif kind == "wrong_password": password = "different synthetic passphrase"
    elif kind == "invalid_email": email = "invalid"
    elif kind == "disabled":
        repository.find_by_email.return_value = AdminRecord(**admin(status="disabled").model_dump(), password_hash=encoded)
    elif kind == "short": password = "short"
    elif kind == "oversized": password = "x"*257
    elif kind == "bad_type": password = None
    verify = Mock(wraps=verify_admin_password)
    monkeypatch.setattr(auth, "verify_admin_password", verify)
    with pytest.raises(auth.InvalidAdminCredentials) as error:
        service.authenticate(email, password)
    assert str(error.value) == "Invalid administrative credentials."
    sessions.create.assert_not_called()
    assert verify.call_count == (2 if kind in {"short", "oversized", "bad_type"} else 1)
    if kind == "invalid_email": repository.find_by_email.assert_not_called()
    else: repository.find_by_email.assert_called_once()
    output = capsys.readouterr()
    assert PASSWORD not in str(error.value) + output.out + output.err + caplog.text
    assert encoded not in str(error.value) + output.out + output.err + caplog.text


@pytest.mark.parametrize("kind", ["lookup", "session", "corrupt_hash", "argon2"])
def test_internal_failures_are_distinct_and_sanitized(setup_auth, monkeypatch, kind, capsys, caplog, encoded):
    service, repository, sessions, record = setup_auth
    private = PASSWORD + encoded + " synthetic-token"
    if kind == "lookup": repository.find_by_email.side_effect = RuntimeError(private)
    elif kind == "session": sessions.create.side_effect = RuntimeError(private)
    elif kind == "corrupt_hash":
        repository.find_by_email.return_value = SimpleNamespace(password_hash=SecretStr("corrupt"))
    else:
        monkeypatch.setattr(auth, "verify_admin_password", Mock(side_effect=RuntimeError(private)))
    with pytest.raises(auth.AdminAuthenticationUnavailable) as error:
        service.authenticate("admin@example.com", PASSWORD)
    assert str(error.value) == "Administrative authentication unavailable."
    assert error.value.__cause__ is None
    if kind != "session": sessions.create.assert_not_called()
    else: sessions.create.assert_called_once_with(record.to_admin())
    output = capsys.readouterr()
    assert private not in output.out + output.err + caplog.text + str(error.value)
    assert PASSWORD not in str(error.value) and encoded not in str(error.value)


def test_service_construction_failure_sanitized(monkeypatch):
    monkeypatch.setattr(auth, "_dummy_hash", Mock(side_effect=RuntimeError("synthetic-private")))
    with pytest.raises(auth.AdminAuthenticationUnavailable, match="unavailable") as error:
        auth.AdminAuthService(Mock(), Mock())
    assert "synthetic-private" not in str(error.value)


def query_mock(documents):
    client = Mock()
    query = client.collection.return_value.where.return_value
    query.limit.return_value.stream.return_value = iter(documents)
    return client, query


def test_repository_bounded_equality_query(encoded):
    record = AdminRecord(**admin().model_dump(), password_hash=encoded)
    client, query = query_mock([SimpleNamespace(id=record.admin_id, to_dict=record.to_document)])
    loaded = AdminRepository(client).find_by_email("admin@example.com")
    assert loaded.to_admin() == record.to_admin()
    client.collection.assert_called_once_with("admins")
    filter_value = client.collection.return_value.where.call_args.kwargs["filter"]
    assert (filter_value.field_path, filter_value.op_string, filter_value.value) == (
        "email_normalized", "==", "admin@example.com")
    query.limit.assert_called_once_with(2)
    query.limit.return_value.stream.assert_called_once_with(timeout=10)


def test_repository_missing():
    client, _ = query_mock([])
    assert AdminRepository(client).find_by_email("admin@example.com") is None


@pytest.mark.parametrize("kind", ["duplicate", "corrupt_hash", "bad_binding", "wrong_email", "network", "noncanonical"])
def test_repository_failures_are_safe(encoded, kind):
    record = AdminRecord(**admin().model_dump(), password_hash=encoded)
    document = record.to_document()
    identifier = record.admin_id
    if kind == "corrupt_hash": document["password_hash"] = "SYNTHETIC_PRIVATE"
    if kind == "bad_binding": identifier = "other"
    if kind == "wrong_email": document["email_normalized"] = "other@example.com"
    snapshot = SimpleNamespace(id=identifier, to_dict=lambda: document)
    client, query = query_mock([snapshot, snapshot] if kind == "duplicate" else [snapshot])
    if kind == "network": query.limit.return_value.stream.side_effect = RuntimeError(PASSWORD + encoded)
    with pytest.raises(AdminLookupError) as error:
        AdminRepository(client).find_by_email(" Admin@Example.com " if kind == "noncanonical" else "admin@example.com")
    assert str(error.value) == "Administrator lookup failed."
    assert error.value.__cause__ is None
    if kind == "noncanonical": client.collection.assert_not_called()
