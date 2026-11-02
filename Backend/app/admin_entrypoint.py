"""Prepared ASGI dispatcher, NOT a deployed app or an automatic Render provider.

No module-level app, environment reads, Firebase initialization or header trust.
Private-ingress configuration requires an approved verifier. Public-authenticated
configuration is a separate explicit contract, with operational (unattested) CF
input for login only. Caller owns the supplied Firestore client's lifecycle.
"""
from dataclasses import dataclass, field
import inspect

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.admin_composition import compose_admin_http
from app.api.admin_origin import resolve_cf_connecting_ip
from app.config.admin_admission import AdminAdmissionConfig
from app.config.admin_cors import admin_cors_options
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_admission import ComplementaryAdminAdmissionPolicy, validate_admission_policy

_ORIGIN_KEY = 'portal.admin.verified_network_origin'


@dataclass(frozen=True, repr=False)
class AdminEntryConfiguration:
    firestore_client: object
    admission_config: AdminAdmissionConfig
    security_config: AdminRequestSecurityConfig
    policy: ComplementaryAdminAdmissionPolicy
    ingress_verifier: object


@dataclass(frozen=True, repr=False)
class PublicAdminEntryConfiguration:
    """Explicit public authenticated API, NOT private/authenticated ingress.

    CF is operational input only; identity/aggregate budgets are mandatory.
    Selecting this object is not authorization to deploy the application.
    """
    firestore_client: object
    admission_config: AdminAdmissionConfig
    security_config: AdminRequestSecurityConfig
    policy: ComplementaryAdminAdmissionPolicy


def _unavailable():
    return JSONResponse({'detail':'Administrative entry unavailable.'}, status_code=503,
                        headers={'Cache-Control':'no-store'})


async def _disabled(scope, receive, send):
    if scope['type'] == 'websocket':
        await send({'type':'websocket.close','code':1008})
    else:
        await _unavailable()(scope,receive,send)


class _VerifiedIngress:
    def __init__(self, app, verifier):
        self.app, self.verifier = app, verifier

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await _disabled(scope,receive,send)
        # Never accept a scope value supplied by outer components as proof.
        scope.pop(_ORIGIN_KEY,None)
        try:
            if scope.get('scheme') != 'https':
                raise ValueError
            request = Request(scope,receive=receive)
            if inspect.iscoroutinefunction(self.verifier):
                value = await self.verifier(request)
            else:
                value = await run_in_threadpool(self.verifier,request)
                if inspect.isawaitable(value):
                    value = await value
            # This only canonicalizes verifier OUTPUT. It does not attest headers.
            if not isinstance(value,str):
                raise ValueError
            origin = resolve_cf_connecting_ip([(b'cf-connecting-ip',value.encode('ascii'))])
        except Exception:
            return await _unavailable()(scope,receive,send)
        scope[_ORIGIN_KEY] = origin
        try:
            await self.app(scope,receive,send)
        finally:
            scope.pop(_ORIGIN_KEY,None)


def _verified_origin(request):
    # Populated exclusively by the per-request ingress boundary, not headers.
    return request.scope[_ORIGIN_KEY]


def _operational_origin(request):
    """Login only: syntactically valid CF, without claiming trusted provenance."""
    return resolve_cf_connecting_ip(request.scope['headers'])


class _PublicHTTPS:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('scheme') != 'https':
            return await _disabled(scope,receive,send)
        # HTTPS is a transport prerequisite, not client authentication. Session,
        # permissions and mutation protections remain enforced by the routers.
        await self.app(scope,receive,send)


@dataclass(repr=False)
class AdminEntryPoint:
    public_app: object = field(repr=False)
    admin_app: object = field(repr=False)
    composition: object = field(default=None,repr=False)

    async def __call__(self,scope,receive,send):
        path = scope.get('path','')
        target = (self.admin_app if scope['type'] in ('http','websocket') and
                  (path == '/admin' or path.startswith('/admin/')) else self.public_app)
        # Public application owns lifespan; administrative composition is inert
        # after construction and has no separate startup/shutdown resources.
        await target(scope,receive,send)


def create_admin_entrypoint(*, admin_configuration=None, public_app=None):
    """Construct once per worker OUTSIDE the event loop, never per request.

    Missing/invalid administrative configuration disables the entire Admin branch
    while preserving the public app. PublicAdminEntryConfiguration explicitly
    selects a public authenticated API, not a private ingress. The separate
    AdminEntryConfiguration retains its verifier requirement. Neither selects
    itself from environment variables or authorizes a production deployment.
    """
    if public_app is None:
        from app.main import app as public_app
    entry = AdminEntryPoint(public_app,_disabled)
    if admin_configuration is None:
        return entry
    try:
        if not isinstance(admin_configuration,(AdminEntryConfiguration,PublicAdminEntryConfiguration)):
            raise ValueError
        config = admin_configuration
        public_mode = isinstance(config,PublicAdminEntryConfiguration)
        if (not isinstance(config.policy,ComplementaryAdminAdmissionPolicy) or
            (not public_mode and not callable(config.ingress_verifier))):
            raise ValueError
        policy = validate_admission_policy(config.policy)
        cors = admin_cors_options(config.security_config)
        composition = compose_admin_http(firestore_client=config.firestore_client,
            admission_config=config.admission_config,security_config=config.security_config,
            policy=policy,trusted_origin_dependency=_operational_origin if public_mode else _verified_origin)
        admin_app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
        admin_app.include_router(composition.router)
        # Preflight does not authenticate or run business logic. Exact CORS is
        # outermost so ingress errors also carry the approved origin's headers.
        guarded = _PublicHTTPS(admin_app) if public_mode else _VerifiedIngress(admin_app,config.ingress_verifier)
        wrapped = CORSMiddleware(guarded,**cors)
    except Exception:
        return entry  # No partial app, raw errors or insecure fallback.
    entry.admin_app, entry.composition = wrapped, composition
    return entry
