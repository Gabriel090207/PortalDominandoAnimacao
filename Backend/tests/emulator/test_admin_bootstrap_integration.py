"""First-owner validation with real SDK transactions on the guarded emulator."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest

from app.persistence import admin_repository as repository
from app.persistence.admin_records import AdminRecord
from app.services.admin_bootstrap_service import provision_first_owner
from app.services.admin_password_service import verify_admin_password
from emulator_support import TEST_PROJECT_ID

pytestmark = pytest.mark.firestore_emulator
PASSWORD = "synthetic emulator owner password"


def provision(client, email="owner@example.com"):
    return provision_first_owner(
        client=client, email=email, password=PASSWORD,
        bootstrap_enabled=True, expected_project_id=TEST_PROJECT_ID,
    )


def state(client):
    return {name: {s.id: s.to_dict() for s in client.collection(name).stream(timeout=5)}
            for name in ("admins", "admin_bootstrap")}


def assert_one_owner(client):
    documents = state(client)
    assert len(documents["admins"]) == len(documents["admin_bootstrap"]) == 1
    identifier, document = next(iter(documents["admins"].items()))
    record = AdminRecord.from_document(document)
    assert record.admin_id == identifier
    assert record.role == "owner" and record.status == "enabled"
    assert record.auth_version == 1 and record.created_by == "bootstrap"
    assert record.created_at == record.updated_at == record.password_changed_at
    assert verify_admin_password(PASSWORD, record.password_hash.get_secret_value())
    assert "password_hash" not in record.to_admin().model_dump()
    marker = documents["admin_bootstrap"][repository.BOOTSTRAP_DOCUMENT]
    assert marker["schema_version"] == 1
    assert marker["operation"] == "first_owner_provisioned"
    assert marker["admin_id"] == identifier and marker["created_by"] == "bootstrap"
    assert isinstance(marker["created_at"], datetime)
    assert marker["created_at"].utcoffset() is not None
    assert not {"password", "password_hash", "email_normalized"} & marker.keys()
    owner_snapshot = client.collection("admins").document(identifier).get(timeout=5)
    marker_snapshot = client.collection("admin_bootstrap").document(repository.BOOTSTRAP_DOCUMENT).get(timeout=5)
    # Both documents were created by the same real atomic commit.
    assert owner_snapshot.create_time == marker_snapshot.create_time
    return record


def assert_private_output_absent(capsys, caplog, hashes=(), errors=()):
    output = capsys.readouterr()
    text = output.out + output.err + caplog.text + " ".join(str(e) for e in errors)
    assert PASSWORD not in text
    assert "$argon2" not in text
    for encoded in hashes:
        assert encoded not in text


def test_first_owner_contract_and_safe_output(emulator_client, capsys, caplog):
    result = provision(emulator_client, " Owner@Example.com ")
    record = assert_one_owner(emulator_client)
    assert result == record.to_admin()
    assert record.email_normalized == "owner@example.com"
    assert_private_output_absent(capsys, caplog, [record.password_hash.get_secret_value()])


@pytest.mark.parametrize("email", [" OWNER@EXAMPLE.COM ", "other@example.com"])
def test_second_bootstrap_rejected_without_overwrite(emulator_client, email, capsys, caplog):
    provision(emulator_client)
    before = state(emulator_client)
    with pytest.raises(repository.AdminBootstrapError) as error:
        provision(emulator_client, email)
    assert state(emulator_client) == before
    record = assert_one_owner(emulator_client)
    assert_private_output_absent(capsys, caplog, [record.password_hash.get_secret_value()], [error.value])


@pytest.mark.parametrize("second_email", [" OWNER@EXAMPLE.COM ", "other@example.com"])
def test_concurrent_bootstrap_unique(emulator_client, second_email, capsys, caplog):
    start = Barrier(2)
    def attempt(email):
        start.wait(timeout=10)
        try:
            return provision(emulator_client, email), None
        except repository.AdminBootstrapError as error:
            return None, error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["owner@example.com", second_email]))
    assert sum(result is not None for result, _ in results) == 1
    assert sum(error is not None for _, error in results) == 1
    record = assert_one_owner(emulator_client)
    assert_private_output_absent(capsys, caplog, [record.password_hash.get_secret_value()],
                                 [error for _, error in results if error is not None])


def test_abort_after_buffered_writes_is_atomic(emulator_client, monkeypatch, capsys, caplog):
    original = repository._create_first_owner
    def abort(transaction, client, document):
        original(transaction, client, document)
        # Real transaction contains BOTH creates but must never commit them.
        raise RuntimeError("synthetic private failure " + document["password_hash"])
    with monkeypatch.context() as patch:
        patch.setattr(repository, "_create_first_owner", abort)
        with pytest.raises(repository.AdminBootstrapError) as error:
            provision(emulator_client)
    assert state(emulator_client) == {"admins": {}, "admin_bootstrap": {}}
    assert "synthetic private failure" not in str(error.value)
    assert error.value.__cause__ is None
    provision(emulator_client)
    record = assert_one_owner(emulator_client)
    assert_private_output_absent(capsys, caplog, [record.password_hash.get_secret_value()], [error.value])


def test_commit_precondition_failure_is_atomic(emulator_client, monkeypatch, capsys, caplog):
    original = repository._create_first_owner
    def invalid_commit(transaction, client, document):
        original(transaction, client, document)
        # Duplicate create fails at the emulator's commit, not in a mock.
        ref = client.collection("admins").document(document["admin_id"])
        transaction.create(ref, document)
    with monkeypatch.context() as patch:
        patch.setattr(repository, "_create_first_owner", invalid_commit)
        with pytest.raises(repository.AdminBootstrapError) as error:
            provision(emulator_client)
    assert state(emulator_client) == {"admins": {}, "admin_bootstrap": {}}
    assert_private_output_absent(capsys, caplog, errors=[error.value])


def test_marker_survives_missing_owner(emulator_client):
    owner = provision(emulator_client)
    emulator_client.collection("admins").document(owner.admin_id).delete(timeout=5)
    before = state(emulator_client)
    assert before["admins"] == {} and len(before["admin_bootstrap"]) == 1
    with pytest.raises(repository.AdminBootstrapError, match="already consumed"):
        provision(emulator_client, "replacement@example.com")
    assert state(emulator_client) == before


def test_existing_admin_without_marker_blocks_bootstrap(emulator_client):
    emulator_client.collection("admins").document("synthetic-legacy").create(
        {"status": "disabled"}, timeout=5)
    before = state(emulator_client)
    with pytest.raises(repository.AdminBootstrapError, match="empty admin collection"):
        provision(emulator_client)
    assert state(emulator_client) == before
