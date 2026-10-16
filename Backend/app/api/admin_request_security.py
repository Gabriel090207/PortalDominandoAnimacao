"""Opt-in mutation protection, not authentication and not a global middleware."""
import re

from fastapi import HTTPException, Request

from app.config.admin_http_security import AdminRequestSecurityConfig, AdminRequestSecurityConfigurationError, validate_origin

ADMIN_REQUEST_HEADER = 'X-Admin-Request'
ADMIN_REQUEST_VALUE = '1'  # Public protocol marker, never an authentication secret.
_MUTATION_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')


def _single_header(request, name):
    values = [value for key, value in request.scope['headers'] if key.lower() == name]
    if len(values) != 1:
        raise ValueError
    return values[0].decode('ascii')


class AdminRequestSecurity:
    def __init__(self, config: AdminRequestSecurityConfig, *, requires_json=True):
        # Revalidate even injected configuration; no defaults for trusted origins.
        try:
            if not isinstance(config, AdminRequestSecurityConfig) or type(requires_json) is not bool:
                raise ValueError
            self.config = AdminRequestSecurityConfig(config.allowed_origins)
        except Exception:
            raise AdminRequestSecurityConfigurationError() from None
        self.requires_json = requires_json

    async def __call__(self, request: Request):
        if request.method not in _MUTATION_METHODS:
            raise HTTPException(status_code=405, detail='Administrative mutation method required.',
                                headers={'Allow': ', '.join(_MUTATION_METHODS)})
        try:
            origin = validate_origin(_single_header(request, b'origin'))
            if origin not in self.config.allowed_origins:
                raise ValueError
            if _single_header(request, b'x-admin-request') != ADMIN_REQUEST_VALUE:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=403, detail='Administrative request rejected.') from None
        if self.requires_json:
            try:
                content_type = _single_header(request, b'content-type')
                if not re.fullmatch(r'application/json(?:;[ \t]*charset=utf-8)?', content_type, re.IGNORECASE):
                    raise ValueError
            except Exception:
                raise HTTPException(status_code=415, detail='Administrative JSON Content-Type required.') from None
