"""Pure administrative contracts, using synthetic facts only."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.domain.admin import (
    Admin, AdminSession, AdminStatus, AdminRole, AdminPermission,
    AdminAuthenticationMethod, role_has_permission, is_admin_enabled,
    admin_session_expires_at, is_admin_session_valid,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def admin(**changes):
    return Admin(**(dict(
        admin_id="synthetic-admin", email_normalized="admin@example.com",
        status="enabled", role="owner", created_at=START,
        updated_at=START, password_changed_at=START, created_by="bootstrap",
    ) | changes))


def session(**changes):
    return AdminSession(**(dict(
        admin_id="synthetic-admin", auth_version_at_issue=1,
        authentication_method="password", created_at=START,
        expires_at=admin_session_expires_at(START),
    ) | changes))


def test_exact_permission_matrix():
    operator = {"read_customers", "read_dashboard", "read_audit", "activate_customer"}
    assert {p.value for p in AdminPermission if role_has_permission(AdminRole.OPERATOR, p)} == operator
    assert all(role_has_permission(AdminRole.OWNER, p) for p in AdminPermission)
    assert set(AdminRole) == {"owner", "operator"}
    assert set(AdminStatus) == {"enabled", "disabled"}
    assert set(AdminAuthenticationMethod) == {"password"}


@pytest.mark.parametrize("value", [None, "", "unknown", 1, True, [], {}])
def test_unknown_permission_or_role_denied(value):
    assert not role_has_permission(value, "read_customers")
    assert not role_has_permission("owner", value)


def test_status_and_invalid_contracts_fail_closed():
    assert is_admin_enabled(admin())
    assert not is_admin_enabled(admin(status="disabled"))
    for value in (None, "enabled", {}, admin().model_copy(update={"status": "unknown"})):
        assert not is_admin_enabled(value)
    for field in ("status", "role"):
        with pytest.raises(ValidationError):
            admin(**{field: "unknown"})


@pytest.mark.parametrize("value", [0, -1, True, "1", 1.0, None])
def test_versions_are_strict_positive_integers(value):
    with pytest.raises(ValidationError):
        admin(auth_version=value)
    with pytest.raises(ValidationError):
        session(auth_version_at_issue=value)
    with pytest.raises(ValidationError):
        admin(email_normalization_version=value)


def test_session_boundaries_and_combinations():
    a, s = admin(), session()
    assert is_admin_session_valid(a, s, now=START)
    assert is_admin_session_valid(a, s, now=s.expires_at-timedelta(microseconds=1))
    for now in (START-timedelta(microseconds=1), s.expires_at, s.expires_at+timedelta(seconds=1)):
        assert not is_admin_session_valid(a, s, now=now)
    for state in (admin(status="disabled"), admin(auth_version=2), admin(admin_id="other-admin")):
        assert not is_admin_session_valid(state, s, now=START)
    assert not is_admin_session_valid(a, session(revoked_at=START), now=START)
    assert not is_admin_session_valid(a, session(auth_version_at_issue=2), now=START)
    assert not is_admin_session_valid(a, s, now=START.replace(tzinfo=None))
    assert not is_admin_session_valid(a, s, now=None)
    assert not is_admin_session_valid(None, s, now=START)
    assert not is_admin_session_valid(a, None, now=START)
    assert not is_admin_session_valid(a, s.model_copy(update={"auth_version_at_issue": True}), now=START)
    assert not is_admin_session_valid(a.model_copy(update={"auth_version": True}), s, now=START)


def test_absolute_eight_hours_including_dst():
    assert admin_session_expires_at(START)-START == timedelta(hours=8)
    local = datetime(2026, 3, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    end = admin_session_expires_at(local)
    assert end-local.astimezone(timezone.utc) == timedelta(hours=8)
    assert session(created_at=local, expires_at=end).expires_at == end
    with pytest.raises(ValueError):
        admin_session_expires_at(START.replace(tzinfo=None))


@pytest.mark.parametrize("field", ["created_at", "updated_at", "password_changed_at"])
def test_admin_naive_timestamps_rejected(field):
    with pytest.raises(ValidationError):
        admin(**{field: START.replace(tzinfo=None)})


@pytest.mark.parametrize("field", ["created_at", "expires_at", "revoked_at"])
def test_session_naive_timestamps_rejected(field):
    with pytest.raises(ValidationError):
        session(**{field: START.replace(tzinfo=None)})


def test_inconsistent_timestamps_rejected():
    for end in (START, START-timedelta(seconds=1), START+timedelta(hours=7), START+timedelta(hours=9)):
        with pytest.raises(ValidationError):
            session(expires_at=end)
    with pytest.raises(ValidationError):
        session(revoked_at=START-timedelta(seconds=1))
    with pytest.raises(ValidationError):
        session(revocation_reason="synthetic-reason")
    with pytest.raises(ValidationError):
        admin(updated_at=START-timedelta(seconds=1))
    with pytest.raises(ValidationError):
        admin(password_changed_at=START+timedelta(seconds=1))


def test_models_are_frozen_secret_free_and_errors_hide_input():
    a, s = admin(), session()
    assert "admin@example.com" not in repr(a)
    assert a.auth_version == 1
    for model in (a, s):
        assert not {"password", "password_hash", "token", "token_digest", "cookie", "csrf_secret"} & type(model).model_fields.keys()
        with pytest.raises(ValidationError):
            model.admin_id = "other-admin"
        with pytest.raises(ValidationError) as error:
            type(model)(**(model.model_dump() | {"password": "SYNTHETIC_SECRET"}))
        assert "SYNTHETIC_SECRET" not in str(error.value)
        assert "SYNTHETIC_SECRET" not in repr(error.value)


def test_canonical_email_and_references():
    for value in (" Admin@Example.com ", "invalid"):
        with pytest.raises(ValidationError):
            admin(email_normalized=value)
    with pytest.raises(ValidationError):
        admin(email_normalization_version=2)
    for value in ("", " ", "invalid/reference", 1):
        with pytest.raises(ValidationError):
            admin(admin_id=value)
        with pytest.raises(ValidationError):
            session(admin_id=value)


def test_pure_dependency_boundary_and_no_global_clock():
    import app.domain.admin as module
    tree = ast.parse(Path(module.__file__).read_text())
    allowed = {"datetime", "enum", "types", "typing", "pydantic", "app.domain.email", "app.domain.policies"}
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert set(imports) <= allowed
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"now", "utcnow"} for node in ast.walk(tree))
