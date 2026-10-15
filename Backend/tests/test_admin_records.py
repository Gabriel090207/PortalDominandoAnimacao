"""Synthetic storage contracts; no database access."""
import pytest
from pydantic import ValidationError

from app.domain.admin import AdminRevocationReason, is_admin_session_valid
from app.persistence.admin_records import AdminRecord, AdminSessionRecord, InvalidAdminRecordError
from app.services.admin_password_service import hash_admin_password
from test_admin_domain import admin, session, START


@pytest.fixture
def record():
    return AdminRecord(**admin().model_dump(), password_hash=hash_admin_password("synthetic record passphrase"))


def test_admin_storage_roundtrip_and_safe_serialization(record):
    encoded = record.password_hash.get_secret_value()
    assert encoded not in repr(record)
    assert "password_hash" not in record.model_dump()
    assert encoded not in record.model_dump_json()
    document = record.to_document()
    assert document["password_hash"] == encoded
    assert document["schema_version"] == 1
    loaded = AdminRecord.from_document(document)
    assert loaded.to_admin() == admin()
    assert "password_hash" not in loaded.to_admin().model_dump()


@pytest.mark.parametrize("value", ["bad", None, 1, b"bad"])
def test_hash_rejected_safely(value):
    with pytest.raises(InvalidAdminRecordError) as error:
        AdminRecord.from_document(dict(admin().model_dump(), schema_version=1, password_hash=value))
    assert str(error.value) == "Invalid stored administrative record."


@pytest.mark.parametrize("version", [None, True, "1", 1.0, 0, 2])
def test_invalid_schema_rejected(record, version):
    for cls, document in ((AdminRecord, record.to_document()),
                          (AdminSessionRecord, AdminSessionRecord(**session().model_dump()).to_document())):
        document["schema_version"] = version
        with pytest.raises(InvalidAdminRecordError):
            cls.from_document(document)


def test_session_roundtrip_and_no_token_fields():
    s = AdminSessionRecord(**session().model_dump())
    document = s.to_document()
    loaded = AdminSessionRecord.from_document(document)
    assert loaded.to_session() == session()
    assert is_admin_session_valid(admin(), loaded.to_session(), now=START)
    for key in ("token", "token_digest", "password_hash"):
        with pytest.raises(InvalidAdminRecordError):
            AdminSessionRecord.from_document(document | {key: "SYNTHETIC_PRIVATE"})


@pytest.mark.parametrize("value", ["", " ", "bootstrap\nactor", "a/b", "a@example.com", "x"*129])
def test_created_by_restricted(value):
    with pytest.raises(ValidationError):
        admin(created_by=value)


def test_created_by_and_revocation_reasons():
    assert admin(created_by="synthetic-admin_2").created_by == "synthetic-admin_2"
    for reason in AdminRevocationReason:
        s = session(revoked_at=START, revocation_reason=reason)
        assert not is_admin_session_valid(admin(), s, now=START)
    for reason in ("unknown", "logout\nactor", "", 1):
        with pytest.raises(ValidationError):
            session(revoked_at=START, revocation_reason=reason)
    with pytest.raises(ValidationError):
        session(revocation_reason=AdminRevocationReason.LOGOUT)


def test_corrupted_input_is_not_in_sanitized_error(record):
    document = record.to_document() | {"unexpected": "SYNTHETIC_PRIVATE"}
    with pytest.raises(InvalidAdminRecordError) as error:
        AdminRecord.from_document(document)
    assert "SYNTHETIC_PRIVATE" not in repr(error.value)
    assert record.password_hash.get_secret_value() not in str(error.value)


@pytest.mark.parametrize("version", [2, 0, True, "1", 1.0, None])
def test_session_export_rejects_invalid_copied_schema(version):
    record = AdminSessionRecord(**session().model_dump())
    corrupted = record.model_copy(update={"schema_version": version})
    with pytest.raises(InvalidAdminRecordError):
        corrupted.to_document()


@pytest.mark.parametrize("identifier", ["synthetic-admin_2", "a", "a"*128])
def test_admin_references_share_the_same_format(identifier):
    creator = admin(admin_id=identifier)
    assert admin(created_by=creator.admin_id).created_by == identifier
    assert session(admin_id=identifier).admin_id == identifier


@pytest.mark.parametrize("identifier", ["admin.with.dots", "a/b", "a b", "a\nactor", "a"*129, "", 1])
def test_admin_references_reject_the_same_invalid_values(identifier):
    for factory, field in ((admin, "admin_id"), (admin, "created_by"), (session, "admin_id")):
        with pytest.raises(ValidationError):
            factory(**{field: identifier})
