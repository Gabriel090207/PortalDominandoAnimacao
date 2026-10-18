"""Explicit router factory; deliberately not registered in app.main."""
import inspect
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.admin_dependencies import AdminHTTPAuthentication, read_admin_session_token
from app.api.admin_request_security import AdminOriginSecurity, AdminRequestSecurity
from app.api.admin_cookies import issue_admin_session_cookie, remove_admin_session_cookie
from app.services.admin_login_service import AdminLoginLimited
from app.services.admin_auth_service import InvalidAdminCredentials
from app.domain.admin import Admin, AdminPermission, AdminRole, role_has_permission


class AdminSessionResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    admin_id: str
    email: str
    role: AdminRole
    permissions: list[AdminPermission]


class _NoStoreAdminRoute(APIRoute):
    async def handle(self, scope, receive, send):
        try:
            await super().handle(scope, receive, send)
        except StarletteHTTPException as error:
            # Includes method rejection before FastAPI dependency execution.
            error.headers = {**(error.headers or {}), 'Cache-Control': 'no-store'}
            raise

    def get_route_handler(self):
        handler = super().get_route_handler()
        async def no_store(request):
            try:
                response = await handler(request)
            except StarletteHTTPException as error:
                error.headers = {**(error.headers or {}), 'Cache-Control': 'no-store'}
                raise
            except Exception:
                raise HTTPException(status_code=503, detail='Administrative request unavailable.',
                                    headers={'Cache-Control': 'no-store'}) from None
            response.headers['Cache-Control'] = 'no-store'
            return response
        return no_store


def create_admin_auth_router(*, session_service, security_config, login_service=None, trusted_origin_dependency=None):
    """No Firebase/environment initialization; dependencies must be supplied."""
    authentication = AdminHTTPAuthentication(session_service)
    origin = AdminOriginSecurity(security_config)
    router = APIRouter(prefix='/admin/auth', tags=['Admin authentication'], route_class=_NoStoreAdminRoute)
    @router.get('/session', response_model=AdminSessionResponse, dependencies=[Depends(origin)])
    async def current_session(administrator: Admin = Depends(authentication)):
        return AdminSessionResponse(admin_id=administrator.admin_id, email=administrator.email_normalized,
            role=administrator.role, permissions=[permission for permission in AdminPermission
                if role_has_permission(administrator.role, permission)])
    mutation_security = AdminRequestSecurity(security_config)

    async def trusted_origin(request: Request):
        # Explicit callable(request); no proxy header or peer fallback.
        try:
            if trusted_origin_dependency is None:
                raise ValueError
            if inspect.iscoroutinefunction(trusted_origin_dependency):
                value = await trusted_origin_dependency(request)
            else:
                value = await run_in_threadpool(trusted_origin_dependency, request)
            if (not isinstance(value, str) or not value or len(value) > 256 or
                value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError
            return value
        except Exception:
            raise HTTPException(status_code=503, detail='Administrative origin unavailable.') from None

    @router.post('/login', dependencies=[Depends(mutation_security)])
    async def login(request: Request, network_origin: str = Depends(trusted_origin)):
        if login_service is None:
            raise HTTPException(status_code=503, detail='Administrative login unavailable.')
        if request.query_params:
            raise HTTPException(status_code=400, detail='Invalid administrative login request.')
        body = bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk) > 4096:
                raise HTTPException(status_code=413, detail='Administrative login request too large.')
            body.extend(chunk)
        try:
            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError
                    value[key] = item
                return value
            def invalid_constant(value):
                raise ValueError
            credentials = json.loads(body, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            if (not isinstance(credentials, dict) or set(credentials) != {'email', 'password'} or
                not isinstance(credentials['email'], str) or not isinstance(credentials['password'], str)):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail='Invalid administrative login request.') from None
        try:
            issued = await run_in_threadpool(login_service.authenticate, network_origin,
                                            credentials['email'], credentials['password'])
        except InvalidAdminCredentials:
            raise HTTPException(status_code=401, detail='Invalid administrative credentials.') from None
        except AdminLoginLimited as error:
            retry = error.retry_after_seconds
            if type(retry) is not int or retry < 0:
                raise HTTPException(status_code=503, detail='Administrative login unavailable.') from None
            raise HTTPException(status_code=429, detail='Administrative authentication temporarily limited.',
                                headers={'Retry-After': str(retry)}) from None
        except Exception:
            raise HTTPException(status_code=503, detail='Administrative login unavailable.') from None
        # Service returns session facts only. GET /session supplies email/role
        # without a redundant presentation-only lookup during login.
        response = JSONResponse({'admin_id': issued.session.admin_id})
        issue_admin_session_cookie(response, issued)
        return response

    logout_security = AdminRequestSecurity(security_config, requires_json=False)

    @router.post('/logout', dependencies=[Depends(logout_security)])
    async def logout(request: Request, token: str = Depends(read_admin_session_token)):
        if request.query_params:
            raise HTTPException(status_code=400, detail='Invalid administrative logout request.')
        # Logout has no body contract, including JSON token/identity claims.
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(status_code=400, detail='Invalid administrative logout request.')
        try:
            confirmed = await run_in_threadpool(session_service.revoke, token)
            # True: changed; False: transaction confirmed missing/already revoked.
            # Never turn an unexpected dependency result into a logout receipt.
            if type(confirmed) is not bool:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=503, detail='Administrative logout unavailable.') from None
        response = JSONResponse({'success': True})
        remove_admin_session_cookie(response)
        return response

    return router
