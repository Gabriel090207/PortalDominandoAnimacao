"""Test-only routes and isolated sessions; nothing registered in production."""
from datetime import datetime, timedelta, timezone
from threading import get_ident
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import ServiceUnavailable
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.admin_dependencies import AdminHTTPAuthentication, ADMIN_SESSION_COOKIE_NAME as COOKIE
from app.domain.admin import AdminPermission
from app.services.admin_session_service import AdminSessionService
from test_admin_domain import admin
from test_admin_sessions import sessions

TOKEN = 'a'*64


def test_app(service, permission=None):
    dependency = AdminHTTPAuthentication(service)
    app = FastAPI()
    @app.get('/protected')
    async def protected(request: Request, administrator=Depends(
        dependency if permission is None else dependency.require_permission(permission))):
        return {'id': administrator.admin_id, 'role': administrator.role}
    return app

# Helper is not a pytest test.
test_app.__test__ = False


@pytest.mark.parametrize('role,permission,status', [
    ('owner', AdminPermission.BLOCK_CUSTOMER, 200),
    ('operator', AdminPermission.READ_CUSTOMERS, 200),
    ('operator', AdminPermission.ACTIVATE_CUSTOMER, 200),
    ('operator', AdminPermission.BLOCK_CUSTOMER, 403),
])
def test_permissions_from_validated_admin(role, permission, status):
    service = Mock()
    service.validate.return_value = admin(role=role)
    with TestClient(test_app(service, permission)) as client:
        response = client.get('/protected?role=owner', headers={'Cookie': f'{COOKIE}={TOKEN}', 'X-Role': 'owner'})
    assert response.status_code == status
    service.validate.assert_called_once_with(TOKEN)
    assert TOKEN not in response.text
    service.create.assert_not_called()
    service.revoke.assert_not_called()


@pytest.mark.parametrize('headers', [[], [('Cookie', 'other=abc')], [('Cookie', f'{COOKIE}=')],
    [('Cookie', f'{COOKIE}=invalid')], [('Cookie', f'{COOKIE}={TOKEN}; {COOKIE}={TOKEN}')],
    [('Cookie', f'{COOKIE}={TOKEN}'), ('Cookie', f'{COOKIE}={TOKEN}')],
    [('Cookie', f'{COOKIE}={TOKEN}; {COOKIE}=broken')],
    [('Cookie', f'{COOKIE}={TOKEN}; {COOKIE} =broken')], [('Cookie', COOKIE)],
    [('Cookie', f'{COOKIE}="{TOKEN}"')], [('Cookie', f'{COOKIE}={TOKEN.upper()}')]])
def test_bad_cookie_never_calls_validation(headers, caplog, capsys):
    service = Mock()
    with TestClient(test_app(service)) as client:
        response = client.get('/protected?token='+TOKEN, headers=headers)
    assert response.status_code == 401
    assert response.json() == {'detail': 'Invalid administrative session.'}
    assert service.mock_calls == []
    output = capsys.readouterr()
    # The test client's own request logging may contain URLs; application code
    # must not log inputs. Do not enable debug HTTP client logs with real tokens.
    assert TOKEN not in response.text+output.out+output.err


def test_no_authorization_header_fallback():
    service = Mock()
    with TestClient(test_app(service)) as client:
        assert client.get('/protected', headers={'Authorization': 'Bearer '+TOKEN}).status_code == 401
    assert service.mock_calls == []


@pytest.mark.parametrize('kind', ['missing', 'expired', 'revoked', 'disabled', 'version', 'binding', 'valid'])
def test_real_session_validation(sessions, kind):
    storage, service = sessions
    instant = datetime.now(timezone.utc)
    issued = service.create(admin(), now=instant-timedelta(hours=9) if kind == 'expired' else instant)
    token = issued.token.get_secret_value()
    if kind == 'missing': token = '0'*64
    elif kind == 'revoked': service.revoke(token)
    elif kind == 'disabled': storage.data['admins/synthetic-admin']['status'] = 'disabled'
    elif kind == 'version': storage.data['admins/synthetic-admin']['auth_version'] += 1
    elif kind == 'binding':
        path = next(path for path in storage.data if path.startswith('admin_sessions/'))
        storage.data[path]['admin_id'] = 'another-admin'
    before = str(storage.data)
    with TestClient(test_app(service)) as client:
        response = client.get('/protected', headers={'Cookie': f'{COOKIE}={token}'})
    assert response.status_code == (200 if kind == 'valid' else 401)
    assert str(storage.data) == before  # No creation, renewal or revocation.
    assert token not in response.text


@pytest.mark.parametrize('result', ['storage_error', 'unexpected_result'])
def test_failure_never_authorizes(result, caplog, capsys):
    service = Mock()
    if result == 'storage_error':
        repository = Mock()
        repository.lookup.side_effect = ServiceUnavailable(TOKEN+'private-hash')
        service = AdminSessionService(repository)
    else: service.validate.return_value = {'role': 'owner'}
    with TestClient(test_app(service, AdminPermission.READ_CUSTOMERS)) as client:
        response = client.get('/protected', headers={'Cookie': f'{COOKIE}={TOKEN}'})
    assert response.status_code == 503
    output = capsys.readouterr()
    assert TOKEN not in response.text+output.out+output.err+caplog.text
    assert 'private-hash' not in response.text+output.out+output.err+caplog.text


def test_synchronous_validation_is_off_event_loop():
    threads = {}
    service = Mock()
    def validate(token):
        threads['validation'] = get_ident()
        return admin()
    service.validate.side_effect = validate
    app = test_app(service)
    @app.middleware('http')
    async def record_thread(request, call_next):
        threads['event_loop'] = get_ident()
        return await call_next(request)
    with TestClient(app) as client:
        assert client.get('/protected', headers={'Cookie': f'{COOKIE}={TOKEN}'}).status_code == 200
    assert threads['validation'] != threads['event_loop']


def test_no_production_routes_registered():
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/admin/auth/session').status_code == 404
        assert client.post('/admin/auth/login').status_code == 404
        assert client.post('/admin/auth/logout').status_code == 404
