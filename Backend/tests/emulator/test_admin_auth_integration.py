"""Authentication + existing sessions with the guarded local Firestore only."""
import pytest

from test_admin_domain import admin
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_repository import AdminRepository
from app.persistence.admin_sessions_repository import AdminSessionsRepository
from app.services.admin_auth_service import AdminAuthService, InvalidAdminCredentials, AdminAuthenticationUnavailable
from app.services.admin_password_service import hash_admin_password
from app.services.admin_session_service import AdminSessionService

pytestmark = pytest.mark.firestore_emulator
PASSWORD = "synthetic emulator authentication password"


def service(client):
    sessions = AdminSessionService(AdminSessionsRepository(client))
    return AdminAuthService(AdminRepository(client), sessions), sessions


def seed(client, role="owner", **changes):
    record = AdminRecord(**admin(role=role).model_dump(), password_hash=hash_admin_password(PASSWORD))
    document = record.to_document() | changes
    client.collection("admins").document(record.admin_id).create(document, timeout=5)


@pytest.mark.parametrize("role", ["owner", "operator"])
def test_password_to_persisted_session(emulator_client, role, caplog, capsys):
    seed(emulator_client, role)
    auth, sessions = service(emulator_client)
    issued = auth.authenticate(" ADMIN@EXAMPLE.COM ", PASSWORD)
    token = issued.token.get_secret_value()
    assert sessions.validate(token).role == role
    records = list(emulator_client.collection("admin_sessions").stream(timeout=5))
    assert len(records) == 1 and token not in str(records[0].to_dict())
    output = capsys.readouterr()
    assert token not in output.out + output.err + caplog.text
    assert PASSWORD not in output.out + output.err + caplog.text


@pytest.mark.parametrize("kind", ["missing", "wrong", "disabled", "corrupt", "duplicate"])
def test_failures_do_not_create_session(emulator_client, kind):
    if kind != "missing":
        changes = {"status":"disabled"} if kind == "disabled" else {"password_hash":"broken"} if kind == "corrupt" else {}
        seed(emulator_client, **changes)
    if kind == "duplicate":
        document = emulator_client.collection("admins").document("synthetic-admin").get(timeout=5).to_dict()
        document["admin_id"] = "second-admin"
        emulator_client.collection("admins").document("second-admin").create(document, timeout=5)
    auth, _ = service(emulator_client)
    expected = AdminAuthenticationUnavailable if kind in {"corrupt", "duplicate"} else InvalidAdminCredentials
    with pytest.raises(expected):
        auth.authenticate("admin@example.com", "different synthetic password" if kind == "wrong" else PASSWORD)
    assert list(emulator_client.collection("admin_sessions").stream(timeout=5)) == []
