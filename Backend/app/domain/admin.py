"""Pure administrative facts and authorization policies; no secrets or I/O."""
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.email import normalize_email
from app.domain.policies import ADMIN_SESSION_LIFETIME, EMAIL_NORMALIZATION_VERSION


class AdminStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class AdminRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"


class AdminPermission(StrEnum):
    READ_CUSTOMERS = "read_customers"
    READ_DASHBOARD = "read_dashboard"
    READ_AUDIT = "read_audit"
    ACTIVATE_CUSTOMER = "activate_customer"
    SUSPEND_CUSTOMER = "suspend_customer"
    RESUME_CUSTOMER = "resume_customer"
    BLOCK_CUSTOMER = "block_customer"
    UNBLOCK_CUSTOMER = "unblock_customer"


class AdminRevocationReason(StrEnum):
    LOGOUT = "logout"
    ADMIN_DISABLED = "admin_disabled"
    CREDENTIALS_CHANGED = "credentials_changed"
    PERMISSIONS_CHANGED = "permissions_changed"
    MANUAL_REVOCATION = "manual_revocation"


class AdminAuthenticationMethod(StrEnum):
    PASSWORD = "password"


INITIAL_ADMIN_AUTH_VERSION = 1
_ROLE_PERMISSIONS = MappingProxyType({
    AdminRole.OWNER: frozenset(AdminPermission),
    AdminRole.OPERATOR: frozenset({
        AdminPermission.READ_CUSTOMERS, AdminPermission.READ_DASHBOARD,
        AdminPermission.READ_AUDIT, AdminPermission.ACTIVATE_CUSTOMER,
        AdminPermission.SUSPEND_CUSTOMER, AdminPermission.RESUME_CUSTOMER,
        AdminPermission.BLOCK_CUSTOMER, AdminPermission.UNBLOCK_CUSTOMER,
    }),
})
_PositiveVersion = Annotated[int, Field(strict=True, gt=0)]
_Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timezone-aware instant required.")
    return value.astimezone(timezone.utc)


class Admin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    admin_id: _Identifier
    email_normalized: str = Field(strict=True, repr=False)
    email_normalization_version: _PositiveVersion = EMAIL_NORMALIZATION_VERSION
    status: AdminStatus
    role: AdminRole
    auth_version: _PositiveVersion = INITIAL_ADMIN_AUTH_VERSION
    created_at: AwareDatetime
    updated_at: AwareDatetime
    password_changed_at: AwareDatetime
    created_by: _Identifier

    @model_validator(mode="after")
    def validate_facts(self):
        if any(not value.strip() or "/" in value for value in (self.admin_id, self.created_by)):
            raise ValueError("Invalid administrative reference.")
        if normalize_email(self.email_normalized, version=self.email_normalization_version) != self.email_normalized:
            raise ValueError("Normalized administrative email required.")
        if not (_utc(self.created_at) <= _utc(self.password_changed_at) <= _utc(self.updated_at)):
            raise ValueError("Invalid administrative timestamps.")
        return self


class AdminSession(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    admin_id: _Identifier
    auth_version_at_issue: _PositiveVersion
    authentication_method: AdminAuthenticationMethod
    created_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    revocation_reason: AdminRevocationReason | None = None

    @model_validator(mode="after")
    def validate_facts(self):
        if not self.admin_id.strip() or "/" in self.admin_id:
            raise ValueError("Invalid administrative reference.")
        if _utc(self.expires_at) - _utc(self.created_at) != ADMIN_SESSION_LIFETIME:
            raise ValueError("Administrative session must last exactly eight hours.")
        if self.revoked_at is not None and _utc(self.revoked_at) < _utc(self.created_at):
            raise ValueError("Invalid session revocation timestamp.")
        if self.revocation_reason is not None and (
            self.revoked_at is None or not self.revocation_reason.strip()
        ):
            raise ValueError("Invalid session revocation reason.")
        return self


def role_has_permission(role: AdminRole | str, permission: AdminPermission | str) -> bool:
    if not isinstance(role, str) or not isinstance(permission, str):
        return False
    try:
        return AdminPermission(permission) in _ROLE_PERMISSIONS[AdminRole(role)]
    except ValueError:
        return False


def is_admin_enabled(admin: Admin) -> bool:
    if not isinstance(admin, Admin):
        return False
    try:
        validated = Admin.model_validate(admin.model_dump(warnings=False))
    except ValueError:
        return False
    return validated.status == AdminStatus.ENABLED


def admin_session_expires_at(created_at: datetime) -> datetime:
    """Absolute lifetime in UTC, including across daylight-saving transitions."""
    return _utc(created_at) + ADMIN_SESSION_LIFETIME


def is_admin_session_valid(admin: Admin, session: AdminSession, *, now: datetime) -> bool:
    if not isinstance(admin, Admin) or not isinstance(session, AdminSession):
        return False
    try:
        admin = Admin.model_validate(admin.model_dump(warnings=False))
        session = AdminSession.model_validate(session.model_dump(warnings=False))
        instant = _utc(now)
    except (ValueError, TypeError):
        return False
    return (
        admin.status == AdminStatus.ENABLED
        and session.admin_id == admin.admin_id
        and session.auth_version_at_issue == admin.auth_version
        and session.revoked_at is None
        and _utc(session.created_at) <= instant < _utc(session.expires_at)
    )
