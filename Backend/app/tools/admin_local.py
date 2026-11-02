"""Explicit loopback-only emulator entry point. Never imported by app.main.

Run this module, not an ASGI import string: the runner disables proxy headers
and binds IPv4 loopback. No dotenv or Firebase Admin initialization is used.
"""
import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from getpass import getpass
import ipaddress
import os
import ssl
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_cors import admin_cors_options
from app.config.admin_http_security import AdminRequestSecurityConfig

PROJECT = 'demo-dominando-animacao-test'
EMULATOR = '127.0.0.1:8080'
ORIGIN = 'https://localhost:5174'
API_HOST = 'localhost:8443'


class LocalAdminError(RuntimeError):
    def __init__(self):
        super().__init__('Local administrative environment unavailable; verify the local configuration.')


def require_local_environment(environ=None):
    env = os.environ if environ is None else environ
    if (env.get('ADMIN_LOCAL_ENABLED') != 'true' or
        env.get('ADMIN_LOCAL_ENVIRONMENT') != 'development' or
        env.get('FIRESTORE_EMULATOR_HOST') != EMULATOR or
        env.get('FIRESTORE_TEST_PROJECT_ID') != PROJECT or
        env.get('DATASTORE_EMULATOR_HOST') not in (None, '', EMULATOR)):
        raise LocalAdminError()
    return load_admin_admission_config(environ=env, env_file=None)


def create_local_client():
    require_local_environment()
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.firestore import Client
    client = Client(project=PROJECT, database='(default)', credentials=AnonymousCredentials(),
                    client_options={'api_endpoint': EMULATOR})
    if client.project != PROJECT or client._emulator_host != EMULATOR:
        client.close()
        raise LocalAdminError()
    return client


def local_connection_origin(request):
    # Only the transport peer; forwarded headers are deliberately ignored.
    try:
        address = ipaddress.ip_address(request.client.host)
        if not address.is_loopback:
            raise ValueError
        return address.compressed
    except Exception:
        raise LocalAdminError() from None


def create_local_app():
    config = require_local_environment()  # Before client creation or any I/O.
    client = create_local_client()
    try:
        composition = compose_admin_http(firestore_client=client, admission_config=config,
            security_config=AdminRequestSecurityConfig((ORIGIN,)),
            trusted_origin_dependency=local_connection_origin)
    except Exception:
        client.close()
        raise LocalAdminError() from None

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            client.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(composition.router)
    app.add_middleware(CORSMiddleware, **admin_cors_options(AdminRequestSecurityConfig((ORIGIN,))))

    @app.middleware('http')
    async def local_boundary(request, call_next):
        try:
            local_connection_origin(request)
            hosts = request.headers.getlist('host')
            if request.url.scheme != 'https' or hosts != [API_HOST]:
                raise ValueError
        except Exception:
            return JSONResponse({'detail': 'Local administrative request rejected.'}, status_code=403)
        return await call_next(request)
    return app


def prepare_owner(password):
    """Reuse the atomic first-owner writer, ONLY against the guarded emulator."""
    require_local_environment()
    from app.persistence.admin_records import AdminRecord
    from app.persistence.admin_repository import create_first_owner
    from app.services.admin_password_service import hash_admin_password
    now = datetime.now(timezone.utc)
    record = AdminRecord(admin_id=uuid4().hex, email_normalized='local-admin@example.com',
        status='enabled', role='owner', created_by='bootstrap', created_at=now,
        updated_at=now, password_changed_at=now, password_hash=hash_admin_password(password))
    client = create_local_client()
    try:
        create_first_owner(client, record)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description='Loopback-only synthetic Admin environment')
    parser.add_argument('--prepare-owner', action='store_true')
    args = parser.parse_args()
    try:
        require_local_environment()
        if args.prepare_owner:
            password = getpass('Synthetic local password (never use a real password): ')
            if password != getpass('Repeat synthetic local password: '):
                raise LocalAdminError()
            prepare_owner(password)
            print('Synthetic emulator owner created: local-admin@example.com')
            return
        cert, key = os.environ['ADMIN_LOCAL_TLS_CERT'], os.environ['ADMIN_LOCAL_TLS_KEY']
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        app = create_local_app()
        import uvicorn
        uvicorn.run(app, host='127.0.0.1', port=8443, proxy_headers=False,
                    ssl_certfile=cert, ssl_keyfile=key, access_log=False)
    except Exception:
        raise SystemExit(str(LocalAdminError())) from None


if __name__ == '__main__':
    main()
