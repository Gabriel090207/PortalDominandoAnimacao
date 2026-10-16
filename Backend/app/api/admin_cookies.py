"""Opt-in cookie transport only; no sessions, endpoints, environment or logging."""
from datetime import datetime, timezone
import re

from pydantic import SecretStr
from starlette.responses import Response

from app.api.admin_dependencies import ADMIN_SESSION_COOKIE_NAME
from app.domain.admin import AdminSession
from app.domain.policies import ADMIN_SESSION_LIFETIME
from app.services.admin_session_service import IssuedAdminSession


class AdminCookieError(RuntimeError):
    def __init__(self):
        super().__init__('Administrative cookie operation unavailable.')


def issue_admin_session_cookie(response: Response, issued: IssuedAdminSession, *, now=None):
    """Call only after successful authentication with the service-issued result.

    Max-Age is rounded DOWN. A subsecond remaining lifetime is rejected rather
    than issuing a cookie that could outlive the session or immediately disappear.
    This does not attest persistence or revalidate authorization against Firestore.
    """
    try:
        if not isinstance(issued, IssuedAdminSession) or not isinstance(issued.token, SecretStr):
            raise ValueError
        session = AdminSession.model_validate(issued.session.model_dump())
        instant = datetime.now(timezone.utc) if now is None else now
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError
        instant = instant.astimezone(timezone.utc)
        if session.revoked_at is not None or not session.created_at <= instant < session.expires_at:
            raise ValueError
        remaining = session.expires_at-instant
        max_age = min(remaining.days*86400+remaining.seconds, int(ADMIN_SESSION_LIFETIME.total_seconds()))
        token = issued.token.get_secret_value()
        if max_age < 1 or not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError
        expires = session.expires_at.astimezone(timezone.utc).replace(microsecond=0)
    except Exception:
        raise AdminCookieError() from None
    response.set_cookie(ADMIN_SESSION_COOKIE_NAME, token, max_age=max_age, expires=expires,
                        path='/', secure=True, httponly=True, samesite='lax')
    response.headers['Cache-Control'] = 'no-store'


def remove_admin_session_cookie(response: Response):
    """Clear browser transport only. NOT a Firestore revocation/logout receipt.

    Future logout must confirm server revocation first. On an error or uncertain
    commit, propagate failure; do not report logout success by clearing a cookie.
    """
    response.delete_cookie(ADMIN_SESSION_COOKIE_NAME, path='/', secure=True,
                           httponly=True, samesite='lax')
    response.headers['Cache-Control'] = 'no-store'
