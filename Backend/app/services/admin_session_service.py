"""Internal sessions only. Call create only AFTER successful authentication.

No password verification, HTTP, cookies, global client, or token logging here.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import secrets

from pydantic import SecretStr

from app.domain.admin import (
    Admin, AdminSession, AdminRevocationReason, admin_session_expires_at,
    is_admin_enabled, is_admin_session_valid,
)
from app.persistence.admin_sessions_repository import SessionCollisionError


class AdminSessionServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedAdminSession:
    token: SecretStr = field(repr=False)
    session: AdminSession


def _instant(now):
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise AdminSessionServiceError("Timezone-aware session instant required.")
    return value.astimezone(timezone.utc)


def _digest(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        return None
    return hashlib.sha256(b"portal-admin-session-v1\0" + token.encode("ascii")).hexdigest()


class AdminSessionService:
    def __init__(self, repository):
        self.repository = repository

    def create(self, authenticated_admin: Admin, *, now=None):
        """The caller supplies the admin/version verified during authentication.

        Storage rechecks the current admin atomically, preventing issuance from
        a stale authenticated version. Multiple admin sessions are permitted;
        the domain defines no single-session policy for administrators.
        """
        try:
            if not is_admin_enabled(authenticated_admin):
                raise AdminSessionServiceError("Administrator cannot start a session.")
            instant = _instant(now)
            session = AdminSession(
                admin_id=authenticated_admin.admin_id,
                auth_version_at_issue=authenticated_admin.auth_version,
                authentication_method="password", created_at=instant,
                expires_at=admin_session_expires_at(instant),
            )
            for _ in range(3):
                token = secrets.token_hex(32)
                digest = _digest(token)
                if digest is None:
                    raise AdminSessionServiceError("Session token generation failed.")
                try:
                    self.repository.create(digest, session)
                except SessionCollisionError:
                    continue
                return IssuedAdminSession(SecretStr(token), session)
            raise AdminSessionServiceError("Unable to allocate a unique session.")
        except AdminSessionServiceError:
            raise
        except Exception:
            raise AdminSessionServiceError("Session creation failed.") from None

    def _lookup(self, token):
        digest = _digest(token)
        if digest is None:
            return None
        try:
            return self.repository.lookup(digest)
        except Exception:
            raise AdminSessionServiceError("Session lookup failed.") from None

    def get_session(self, token):
        """Inspection only: returned sessions may be expired/revoked. Not authorization."""
        found = self._lookup(token)
        return found[0] if found else None

    def validate(self, token, *, now=None, expected_admin_id=None):
        """Return current safe Admin facts only when the persisted session is valid."""
        instant = _instant(now)
        found = self._lookup(token)
        if found is None:
            return None
        session, admin = found
        if admin is None or (expected_admin_id is not None and session.admin_id != expected_admin_id):
            return None
        return admin if is_admin_session_valid(admin, session, now=instant) else None

    def revoke(self, token, *, reason=AdminRevocationReason.LOGOUT, now=None):
        digest = _digest(token)
        if digest is None:
            return False
        try:
            return self.repository.revoke(digest, now=_instant(now), reason=AdminRevocationReason(reason))
        except Exception:
            raise AdminSessionServiceError("Session revocation failed.") from None
