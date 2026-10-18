"""Synthetic HTTP-only composition; no production Firebase clients."""
from datetime import datetime, timedelta, timezone
from threading import get_ident
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from app.api.admin_auth import create_admin_auth_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin import AdminSession
from app.services.admin_session_service import IssuedAdminSession
from app.services.admin_auth_service import InvalidAdminCredentials, AdminAuthenticationUnavailable
from app.services.admin_login_service import AdminLoginLimited
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable

ORIGIN = 'https://admin.example.test'
TOKEN = 'a'*64
PASSWORD = 'synthetic login password'


def issued():
    now = datetime.now(timezone.utc)
    return IssuedAdminSession(SecretStr(TOKEN), AdminSession(admin_id='synthetic-admin',
        auth_version_at_issue=1, authentication_method='password', created_at=now, expires_at=now+timedelta(hours=8)))


def app_for(login, origin=lambda request: '192.0.2.1'):
    app = FastAPI()
    app.include_router(create_admin_auth_router(session_service=Mock(), login_service=login,
        security_config=AdminRequestSecurityConfig((ORIGIN,)), trusted_origin_dependency=origin))
    return app


def headers(): return [('Origin', ORIGIN), ('X-Admin-Request','1'), ('Content-Type','application/json')]


def check(response, status):
    assert response.status_code == status
    assert response.headers['cache-control'] == 'no-store'
    if status != 200: assert 'set-cookie' not in response.headers
    assert TOKEN not in response.text and PASSWORD not in response.text


def test_success_and_threadpool():
    threads = {}
    login = Mock()
    def authenticate(*args):
        threads['service'] = get_ident()
        return issued()
    login.authenticate.side_effect = authenticate
    app = app_for(login)
    @app.middleware('http')
    async def thread(request, call_next):
        threads['loop'] = get_ident()
        return await call_next(request)
    with TestClient(app, base_url='https://testserver') as client:
        response = client.post('/admin/auth/login', headers=headers(), json={'email':'admin@example.com','password':PASSWORD})
    check(response,200)
    assert response.json() == {'admin_id':'synthetic-admin'}
    value = response.headers['set-cookie']
    assert all(p in value for p in ('__Host-admin_session=', 'HttpOnly','Secure','SameSite=lax','Path=/'))
    assert 'Domain=' not in value
    assert threads['service'] != threads['loop']
    login.authenticate.assert_called_once_with('192.0.2.1','admin@example.com',PASSWORD)


@pytest.mark.parametrize('error,status', [(InvalidAdminCredentials(),401), (AdminLoginLimited(60),429),
    (AdminAdmissionUnavailable(),503), (AdminAuthenticationUnavailable(),503), (RuntimeError(TOKEN+PASSWORD),503)])
def test_errors(error,status,caplog,capsys):
    login = Mock()
    login.authenticate.side_effect = error
    with TestClient(app_for(login)) as client:
        response = client.post('/admin/auth/login',headers=headers(),json={'email':'invalid','password':PASSWORD})
    check(response,status)
    if status == 429: assert response.headers['retry-after'] == '60'
    output = capsys.readouterr()
    assert TOKEN not in output.out+output.err+caplog.text
    assert PASSWORD not in output.out+output.err+caplog.text
    login.authenticate.assert_called_once_with('192.0.2.1','invalid',PASSWORD)


@pytest.mark.parametrize('origin', [None, lambda r: None, lambda r: ''])
def test_missing_origin(origin):
    login = Mock()
    with TestClient(app_for(login, origin)) as client:
        check(client.post('/admin/auth/login',headers=headers(),json={'email':'x','password':PASSWORD}),503)
    login.authenticate.assert_not_called()


@pytest.mark.parametrize('h,status', [([],403), ([('Origin',ORIGIN)],403),
    (headers()+[('Origin',ORIGIN)],403), (headers()+[('X-Admin-Request','1')],403),
    ([('Origin','https://evil.test'),('X-Admin-Request','1')],403),
    ([('Origin',ORIGIN),('X-Admin-Request','wrong')],403),
    ([('Origin',ORIGIN),('X-Admin-Request','1'),('Content-Type','application/x-www-form-urlencoded')],415)])
def test_security(h,status):
    login = Mock()
    with TestClient(app_for(login)) as client:
        check(client.post('/admin/auth/login',headers=h,content='{}'),status)
    login.authenticate.assert_not_called()


@pytest.mark.parametrize('body,status', [('x'*4097,413), ('{',400), ('[]',400),
    ('{"email":"x","password":"p","role":"owner"}',400), ('{"email":1,"password":"p"}',400),
    ('{"email":"x","email":"y","password":"p"}',400), ('{}',400)])
def test_body(body,status):
    login = Mock()
    with TestClient(app_for(login)) as client:
        check(client.post('/admin/auth/login',headers=headers(),content=body),status)
    login.authenticate.assert_not_called()


def test_query_rejected():
    login = Mock()
    with TestClient(app_for(login)) as client:
        check(client.post('/admin/auth/login?email=synthetic',headers=headers(),json={'email':'x','password':PASSWORD}),400)
    login.authenticate.assert_not_called()


def test_no_service():
    with TestClient(app_for(None)) as client:
        check(client.post('/admin/auth/login',headers=headers(),json={'email':'x','password':PASSWORD}),503)


def test_expired_session():
    login = Mock()
    value = issued()
    login.authenticate.return_value = IssuedAdminSession(value.token, value.session.model_copy(update={
        'created_at':value.session.created_at-timedelta(days=1), 'expires_at':value.session.expires_at-timedelta(days=1)}))
    with TestClient(app_for(login)) as client:
        check(client.post('/admin/auth/login',headers=headers(),json={'email':'x','password':PASSWORD}),503)


# Existing fixtures use real policies/Argon2 and isolated atomic storage.
from test_admin_admission import admission
from test_admin_auth import setup_auth, encoded
from app.services.admin_login_service import AdminLoginService
from app.persistence.admin_records import AdminRecord
from test_admin_domain import admin
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY


@pytest.mark.parametrize('kind', ['success', 'missing', 'disabled', 'wrong', 'invalid', 'session_failure'])
def test_real_internal_composition(admission, setup_auth, encoded, kind):
    from test_admin_auth import PASSWORD as REAL_SYNTHETIC_PASSWORD
    client_store, _, build = admission
    auth, repository, sessions, _ = setup_auth
    sessions.create.return_value = issued()
    email, password = 'admin@example.com', REAL_SYNTHETIC_PASSWORD
    if kind == 'missing': repository.find_by_email.return_value = None
    elif kind == 'disabled': repository.find_by_email.return_value = AdminRecord(**admin(status='disabled').model_dump(), password_hash=encoded)
    elif kind == 'wrong': password = 'incorrect synthetic password'
    elif kind == 'invalid': email = 'invalid'
    elif kind == 'session_failure': sessions.create.side_effect = RuntimeError('synthetic private failure')
    login = AdminLoginService(build(INITIAL_ADMIN_ADMISSION_POLICY), auth)
    with TestClient(app_for(login)) as client:
        response = client.post('/admin/auth/login', headers=headers(), json={'email':email,'password':password})
    check(response, 200 if kind == 'success' else 503 if kind == 'session_failure' else 401)
    assert len(client_store.data) == 2
    if kind in {'success', 'session_failure'}: sessions.create.assert_called_once()
    else: sessions.create.assert_not_called()
    if kind == 'invalid': repository.find_by_email.assert_not_called()


def test_real_rate_limit_stops_authentication(admission, setup_auth, monkeypatch):
    import app.services.admin_auth_service as auth_module
    storage, _, build = admission
    auth, repository, sessions, _ = setup_auth
    login = AdminLoginService(build(INITIAL_ADMIN_ADMISSION_POLICY), auth)
    with TestClient(app_for(login)) as client:
        for _ in range(5):
            check(client.post('/admin/auth/login',headers=headers(),json={'email':'invalid','password':PASSWORD}),401)
        forbidden = Mock(side_effect=AssertionError('Argon must not run'))
        monkeypatch.setattr(auth_module,'verify_admin_password',forbidden)
        response = client.post('/admin/auth/login',headers=headers(),json={'email':'different-invalid','password':PASSWORD})
        check(response,429)
        assert response.headers['retry-after'] == '60'
    forbidden.assert_not_called()
    repository.find_by_email.assert_not_called()
    sessions.create.assert_not_called()


def test_hmac_missing_cannot_initialize_login():
    from app.config.admin_admission import load_admin_admission_config, AdminAdmissionConfigurationError
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_config(environ={},env_file=None)
    # No constructed login service: HTTP composition remains unavailable.
    with TestClient(app_for(None)) as client:
        check(client.post('/admin/auth/login',headers=headers(),json={'email':'x','password':PASSWORD}),503)


def test_spoofed_origin_headers_never_supply_missing_dependency():
    login = Mock()
    with TestClient(app_for(login, None)) as client:
        response = client.post('/admin/auth/login',headers=headers()+[
            ('CF-Connecting-IP','192.0.2.99'),('X-Forwarded-For','192.0.2.99')],
            json={'email':'x','password':PASSWORD})
    check(response,503)
    login.authenticate.assert_not_called()


def test_async_origin_dependency():
    async def synthetic_origin(request): return '192.0.2.2'
    login = Mock()
    login.authenticate.return_value = issued()
    with TestClient(app_for(login, synthetic_origin)) as client:
        check(client.post('/admin/auth/login',headers=headers(),json={'email':'x','password':PASSWORD}),200)
    login.authenticate.assert_called_once_with('192.0.2.2','x',PASSWORD)
