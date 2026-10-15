"""In-memory optimistic transactions only; no Firebase initialization or network."""
import copy
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from google.cloud import firestore

from app.persistence.admin_records import AdminRecord
from app.persistence.admin_repository import AdminBootstrapError, create_first_owner
from app.services.admin_bootstrap_service import provision_first_owner
from app.services.admin_password_service import verify_admin_password
from app.tools import provision_admin as cli

PASSWORD = "synthetic owner password only"
CONTROL = "admin_bootstrap/first_owner_v1"


class Conflict(Exception):
    pass


class Ref:
    def __init__(self, client, path):
        self.client, self.path = client, path

    def get(self, transaction):
        assert not transaction.writes
        return SimpleNamespace(exists=self.path in transaction.snapshot)


class Collection:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def document(self, identifier):
        return Ref(self.client, f"{self.name}/{identifier}")

    def limit(self, number):
        assert number == 1
        return self

    def stream(self, transaction):
        assert not transaction.writes
        return iter([object()] if any(p.startswith(self.name + "/")
                                     for p in transaction.snapshot) else [])


class Transaction:
    def __init__(self, client):
        self.client, self.writes = client, []
        with client.lock:
            self.snapshot = copy.deepcopy(client.data)
            self.version = client.version

    def create(self, ref, data):
        self.writes.append((ref.path, data))

    def commit(self):
        with self.client.lock:
            if self.version != self.client.version:
                raise Conflict
            pending = copy.deepcopy(self.client.data)
            for path, data in self.writes:
                if path in pending:
                    raise Conflict
                if self.client.fail_write == path.split("/")[0]:
                    raise RuntimeError("SYNTHETIC_PRIVATE_STORAGE_ERROR")
                pending[path] = {
                    key: datetime(2026, 1, 1, tzinfo=timezone.utc)
                    if value is firestore.SERVER_TIMESTAMP else copy.deepcopy(value)
                    for key, value in data.items()
                }
            self.client.data = pending
            self.client.version += 1


class Client:
    project = "demo-admin-bootstrap-test"

    def __init__(self):
        self.data, self.version, self.lock = {}, 0, Lock()
        self.fail_write = None
        self.barrier = None
        self.conflicts = 0

    def collection(self, name):
        assert name in {"admins", "admin_bootstrap"}
        return Collection(self, name)

    def transaction(self):
        return Transaction(self)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # Unit CLI cases must not load the operator's private .env or inherit tests.
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    for name in cli._TEST_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Production Firebase access forbidden")
    monkeypatch.setattr("firebase_admin.initialize_app", forbidden)
    monkeypatch.setattr("app.services.firebase_service.get_firestore_client", forbidden)
    monkeypatch.setattr(cli, "get_firestore_client", forbidden)

    def transactional(callback):
        def run(transaction, client, document):
            # Both concurrent requests observe the same initial empty snapshot.
            if client.barrier is not None:
                client.barrier.wait(timeout=10)
            for _ in range(3):
                callback(transaction, client, document)
                try:
                    transaction.commit()
                    return
                except Conflict:
                    client.conflicts += 1
                    transaction = client.transaction()
            raise RuntimeError("Synthetic contention exhausted")
        return run
    monkeypatch.setattr("app.persistence.admin_repository.firestore.transactional", transactional)


def provision(client, email="Owner@Example.com", **changes):
    args = dict(client=client, email=email, password=PASSWORD,
                bootstrap_enabled=True, expected_project_id=client.project)
    return provision_first_owner(**(args | changes))


def test_first_owner_hash_contract_and_audit(capsys):
    client = Client()
    admin = provision(client)
    document = client.data[f"admins/{admin.admin_id}"]
    loaded = AdminRecord.from_document(document)
    assert loaded.to_admin() == admin
    assert admin.role == "owner" and admin.status == "enabled"
    assert admin.created_by == "bootstrap" and admin.auth_version == 1
    assert admin.email_normalized == "owner@example.com"
    assert admin.created_at == admin.updated_at == admin.password_changed_at
    assert "password_hash" not in admin.model_dump()
    assert verify_admin_password(PASSWORD, document["password_hash"])
    assert PASSWORD not in str(client.data)
    marker = client.data[CONTROL]
    assert marker["admin_id"] == admin.admin_id
    assert marker["created_by"] == "bootstrap"
    assert not {"email", "email_normalized", "password", "password_hash"} & marker.keys()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("email", ["owner@example.com", " OWNER@EXAMPLE.COM ", "other@example.com"])
def test_repeat_never_overwrites(email):
    client = Client()
    provision(client)
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminBootstrapError):
        provision(client, email)
    assert client.data == before


def test_existing_legacy_admin_blocks_bootstrap():
    client = Client()
    client.data["admins/existing"] = {"status": "disabled"}
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminBootstrapError, match="empty admin collection"):
        provision(client)
    assert client.data == before


def test_deleted_owner_does_not_reopen_bootstrap():
    client = Client()
    admin = provision(client)
    del client.data[f"admins/{admin.admin_id}"]
    with pytest.raises(AdminBootstrapError, match="already consumed"):
        provision(client)
    assert set(client.data) == {CONTROL}


@pytest.mark.parametrize("second", [" OWNER@EXAMPLE.COM ", "other@example.com"])
def test_concurrent_requests_have_exactly_one_winner(second):
    client = Client()
    client.barrier = Barrier(2)
    def attempt(email):
        try:
            return provision(client, email)
        except AdminBootstrapError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["owner@example.com", second]))
    assert sum(result is not None for result in results) == 1
    assert sum(path.startswith("admins/") for path in client.data) == 1
    assert CONTROL in client.data and len(client.data) == 2
    assert client.conflicts == 1


@pytest.mark.parametrize("collection", ["admins", "admin_bootstrap"])
def test_failed_commit_has_no_partial_writes_and_can_retry(collection):
    client = Client()
    client.fail_write = collection
    with pytest.raises(AdminBootstrapError) as error:
        provision(client)
    assert client.data == {}
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
    assert PASSWORD not in str(error.value) and error.value.__cause__ is None
    client.fail_write = None
    assert provision(client).role == "owner"


def test_lost_commit_response_does_not_allow_second_owner(monkeypatch):
    client = Client()
    real_commit = Transaction.commit
    def uncertain(transaction):
        real_commit(transaction)
        raise RuntimeError("SYNTHETIC_PRIVATE_STORAGE_ERROR")
    monkeypatch.setattr(Transaction, "commit", uncertain)
    with pytest.raises(AdminBootstrapError):
        provision(client)
    monkeypatch.setattr(Transaction, "commit", real_commit)
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminBootstrapError, match="already consumed"):
        provision(client)
    assert client.data == before


@pytest.mark.parametrize("changes", [dict(bootstrap_enabled=False), dict(bootstrap_enabled="true"),
    dict(expected_project_id="wrong-project"), dict(expected_project_id=""),
    dict(password="short"), dict(email="invalid")])
def test_invalid_input_never_writes(changes):
    client = Client()
    with pytest.raises(AdminBootstrapError):
        provision(client, **changes)
    assert client.data == {}


@pytest.mark.parametrize("changes", [dict(role="operator"), dict(status="disabled"),
    dict(created_by="someone_else"), dict(admin_id="bootstrap"), dict(auth_version=2)])
def test_repository_rejects_ineligible_record(changes):
    client = Client()
    admin = provision(client)
    source = client.data[f"admins/{admin.admin_id}"] | changes
    empty = Client()
    with pytest.raises(AdminBootstrapError, match="contract"):
        create_first_owner(empty, AdminRecord.from_document(source))
    assert empty.data == {}


def terminal(monkeypatch, answers):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_ENABLED", "true")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(iterator))


def test_cli_disabled_and_noninteractive_never_initialize(monkeypatch):
    monkeypatch.delenv("ADMIN_BOOTSTRAP_ENABLED", raising=False)
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1
    monkeypatch.setenv("ADMIN_BOOTSTRAP_ENABLED", "true")
    assert cli.main(["--project-id", Client.project]) == 1
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1


def test_cli_confirmation_cancel_never_initializes(monkeypatch):
    terminal(monkeypatch, ["wrong confirmation"])
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1


def test_cli_success_and_sanitized_failure(monkeypatch, capsys):
    client = Client()
    terminal(monkeypatch, [f"BOOTSTRAP {Client.project}", "owner@example.com"])
    monkeypatch.setattr(cli, "get_firestore_client", lambda: client)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: PASSWORD)
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 0
    terminal(monkeypatch, [f"BOOTSTRAP {Client.project}", "owner@example.com"])
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
    assert next(d["password_hash"] for p, d in client.data.items() if p.startswith("admins/")) not in output.out + output.err


def test_cli_wrong_project_and_password_confirmation_never_write(monkeypatch):
    client = Client()
    terminal(monkeypatch, ["BOOTSTRAP wrong-project"])
    monkeypatch.setattr(cli, "get_firestore_client", lambda: client)
    assert cli.main(["--bootstrap", "--project-id", "wrong-project"]) == 1
    terminal(monkeypatch, [f"BOOTSTRAP {Client.project}", "owner@example.com"])
    passwords = iter([PASSWORD, "different synthetic password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(passwords))
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1
    assert client.data == {}


def test_cli_refuses_password_echo_fallback(monkeypatch, capsys):
    client = Client()
    terminal(monkeypatch, [f"BOOTSTRAP {Client.project}", "owner@example.com"])
    monkeypatch.setattr(cli, "get_firestore_client", lambda: client)
    def fallback(prompt):
        warnings.warn("SYNTHETIC_PRIVATE_WARNING", cli.getpass.GetPassWarning)
        raise AssertionError("Password must not be read with echo")
    monkeypatch.setattr(cli.getpass, "getpass", fallback)
    assert cli.main(["--bootstrap", "--project-id", Client.project]) == 1
    assert client.data == {}
    assert "SYNTHETIC_PRIVATE_WARNING" not in capsys.readouterr().err
