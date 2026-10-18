"""Only test apps register the router. No production Firebase access."""
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from app.api.admin_auth import create_admin_auth_router
from app.api.admin_dependencies import ADMIN_SESSION_COOKIE_NAME
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin import AdminPermission, role_has_permission
from test_admin_domain import admin
from test_admin_sessions import sessions

TOKEN = 'a'*64
ORIGIN = 'https://admin.example.test'


def app_for(service):
    app = FastAPI()
    app.include_router(create_admin_auth_router(session_service=service,
        security_config=AdminRequestSecurityConfig((ORIGIN,))))
    return app


def headers(token=TOKEN):
    return [('Origin', ORIGIN), ('Cookie', f'{ADMIN_SESSION_COOKIE_NAME}={token}')]


def check(response, status):
    assert response.status_code == status
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('role', ['owner', 'operator'])
def test_server_permissions(role, caplog, capsys):
    service = Mock()
    service.validate.return_value = admin(role=role)
    with TestClient(app_for(service)) as client:
        response = client.get('/admin/auth/session?role=owner', headers=headers())
    check(response, 200)
    assert response.json() == {'admin_id': 'synthetic-admin', 'email': 'admin@example.com', 'role': role,
        'permissions': [p.value for p in AdminPermission if role_has_permission(role, p)]}
    assert service.method_calls == [('validate', (TOKEN,), {})]
    output = capsys.readouterr()
    assert TOKEN not in response.text+caplog.text+output.out+output.err


@pytest.mark.parametrize('cookies', [[], [('Cookie', f'{ADMIN_SESSION_COOKIE_NAME}=invalid')],
    [('Cookie', f'{ADMIN_SESSION_COOKIE_NAME}={TOKEN}; {ADMIN_SESSION_COOKIE_NAME}={TOKEN}')]])
def test_bad_cookie(cookies):
    service = Mock()
    with TestClient(app_for(service)) as client:
        response = client.get('/admin/auth/session', headers=[('Origin', ORIGIN)]+cookies)
    check(response, 401)
    assert service.mock_calls == []


@pytest.mark.parametrize('origin', [None, 'null', 'https://evil.test', ORIGIN+'/path', 'http://admin.example.test'])
def test_bad_origin_precedes_storage(origin):
    service = Mock()
    h = [('Cookie', f'{ADMIN_SESSION_COOKIE_NAME}={TOKEN}')]
    if origin is not None: h.append(('Origin', origin))
    with TestClient(app_for(service)) as client:
        response = client.get('/admin/auth/session', headers=h)
    check(response, 403)
    assert service.mock_calls == []


def test_duplicate_origin():
    service = Mock()
    with TestClient(app_for(service)) as client:
        response = client.get('/admin/auth/session', headers=headers()+[('origin', ORIGIN)])
    check(response, 403)
    assert service.mock_calls == []


@pytest.mark.parametrize('kind', ['valid', 'missing', 'expired', 'revoked', 'disabled', 'version'])
def test_existing_service_no_renewal(sessions, kind):
    storage, service = sessions
    now = datetime.now(timezone.utc)
    issued = service.create(admin(), now=now-timedelta(hours=9) if kind == 'expired' else now)
    token = issued.token.get_secret_value()
    if kind == 'missing': token = '0'*64
    elif kind == 'revoked': service.revoke(token)
    elif kind == 'disabled': storage.data['admins/synthetic-admin']['status'] = 'disabled'
    elif kind == 'version': storage.data['admins/synthetic-admin']['auth_version'] += 1
    before = copy.deepcopy(storage.data)
    with TestClient(app_for(service)) as client:
        for _ in range(2):
            response = client.get('/admin/auth/session', headers=headers(token))
            check(response, 200 if kind == 'valid' else 401)
    assert storage.data == before
    assert token not in response.text


def test_firestore_error_sanitized(sessions, monkeypatch, caplog, capsys):
    _, service = sessions
    private = 'synthetic-password-hash-hmac'
    monkeypatch.setattr(service.repository, 'lookup', Mock(side_effect=ServiceUnavailable(TOKEN+private)))
    with TestClient(app_for(service)) as client:
        response = client.get('/admin/auth/session', headers=headers())
    check(response, 503)
    output = capsys.readouterr()
    assert all(v not in response.text+output.out+output.err+caplog.text for v in (TOKEN, private))


def test_main_public_only(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv', lambda *a, **k: None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN', 'synthetic-webhook')
    with TestClient(app) as client:
        assert client.get('/admin/auth/session', headers=headers()).status_code == 404
        assert client.get('/health').status_code == 200
        assert client.post('/webhooks/kirvano', json={}).status_code == 401



def test_method_rejection_not_cached():
    service = Mock()
    with TestClient(app_for(service)) as client:
        response = client.post('/admin/auth/session', headers=headers())
    check(response, 405)
    assert service.mock_calls == []
