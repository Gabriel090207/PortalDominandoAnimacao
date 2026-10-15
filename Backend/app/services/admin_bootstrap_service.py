"""Explicitly gated first-owner provisioning; no Firebase initialization here."""
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.email import normalize_email
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_repository import AdminBootstrapError, BOOTSTRAP_ACTOR, create_first_owner
from app.services.admin_password_service import hash_admin_password


def provision_first_owner(*, client, email, password, bootstrap_enabled, expected_project_id):
    """Use an injected client, explicit opt-in and exact project confirmation."""
    if bootstrap_enabled is not True:
        raise AdminBootstrapError("Administrator bootstrap is not enabled.")
    if (not isinstance(expected_project_id, str) or not expected_project_id.strip()
        or expected_project_id != client.project):
        raise AdminBootstrapError("Bootstrap project confirmation failed.")
    try:
        email_normalized = normalize_email(email)
        password_hash = hash_admin_password(password)
        now = datetime.now(timezone.utc)
        record = AdminRecord(
            admin_id=uuid4().hex, email_normalized=email_normalized,
            status="enabled", role="owner", created_by=BOOTSTRAP_ACTOR,
            created_at=now, updated_at=now, password_changed_at=now,
            password_hash=password_hash,
        )
    except Exception:
        raise AdminBootstrapError("Invalid bootstrap input or password processing failed.") from None
    return create_first_owner(client, record)
