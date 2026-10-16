"""Opt-in FastAPI dependencies only: no routes, clients or cookie issuance.

Compose AdminHTTPAuthentication with an existing AdminSessionService. Use the
instance in Depends(), or its require_permission() dependency factory. Nothing
is registered in main. HTTP mutation/CSRF and login remain separate concerns.
"""
import re

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.domain.admin import Admin, AdminPermission, is_admin_enabled, role_has_permission

ADMIN_SESSION_COOKIE_NAME = '__Host-admin_session'


def _unauthorized():
    return HTTPException(status_code=401, detail='Invalid administrative session.')


def _session_cookie(request):
    # request.cookies collapses duplicate names. Inspect ALL original fields,
    # including multiple Cookie headers and duplicates with identical values.
    try:
        values = []
        for name, value in request.scope['headers']:
            if name.lower() != b'cookie':
                continue
            for part in value.decode('ascii').split(';'):
                cookie_name, separator, candidate = part.strip(' \t').partition('=')
                if cookie_name.strip(' \t') == ADMIN_SESSION_COOKIE_NAME:
                    if not separator:
                        raise ValueError
                    values.append(candidate)
        if len(values) != 1 or not re.fullmatch(r'[0-9a-f]{64}', values[0]):
            raise ValueError
        return values[0]
    except Exception:
        raise _unauthorized() from None


class AdminHTTPAuthentication:
    def __init__(self, session_service):
        self.session_service = session_service

    async def __call__(self, request: Request) -> Admin:
        token = _session_cookie(request)
        try:
            administrator = await run_in_threadpool(self.session_service.validate, token)
            if administrator is not None and (
                not isinstance(administrator, Admin) or not is_admin_enabled(administrator)
            ):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=503, detail='Administrative session validation unavailable.') from None
        if administrator is None:
            raise _unauthorized()
        return administrator

    def require_permission(self, permission: AdminPermission):
        # Reject programming/configuration errors at composition, never trust
        # permission/role claims supplied by a request.
        required = AdminPermission(permission)

        async def authorized(administrator: Admin = Depends(self)) -> Admin:
            if not role_has_permission(administrator.role, required):
                raise HTTPException(status_code=403, detail='Administrative permission denied.')
            return administrator

        return authorized
