"""Isolated HTTP logout with existing session service/fake atomic persistence."""
import copy
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from threading import get_ident
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable

from app.api.admin_auth import create_admin_auth_router
from app.api.admin_dependencies import ADMIN_SESSION_COOKIE_NAME as NAME
from app.config.admin_http_security import AdminRequestSecurityConfig
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
    return [('Origin', ORIGIN), ('X-Admin-Request','1'), ('Cookie',f'{NAME}={token}; portal-user=synthetic-user')]


def check(response,status):
    assert response.status_code == status
    assert response.headers['cache-control'] == 'no-store'
    assert TOKEN not in response.text
    if status != 200: assert 'set-cookie' not in response.headers


def assert_removed(response):
    assert len(response.headers.get_list('set-cookie')) == 1
    parsed = SimpleCookie()
    parsed.load(response.headers['set-cookie'])
    assert set(parsed) == {NAME}
    value = parsed[NAME]
    assert value.value == '' and value['max-age'] == '0'
    assert value['secure'] and value['httponly']
    assert value['samesite'] == 'lax' and value['path'] == '/' and value['domain'] == ''
    assert parsedate_to_datetime(value['expires']) <= datetime.now(timezone.utc)


@pytest.mark.parametrize('confirmed',[True,False])
def test_confirmation_before_removal_and_threadpool(confirmed, monkeypatch):
    import app.api.admin_auth as module
    threads, events = {}, []
    service = Mock()
    def revoke(token):
        threads['storage'] = get_ident()
        events.append('confirmed')
        return confirmed
    service.revoke.side_effect = revoke
    original = module.remove_admin_session_cookie
    def remove(response):
        assert events == ['confirmed']
        events.append('removed')
        original(response)
    monkeypatch.setattr(module,'remove_admin_session_cookie',remove)
    app = app_for(service)
    @app.middleware('http')
    async def record_thread(request, call_next):
        threads['loop'] = get_ident()
        return await call_next(request)
    with TestClient(app, base_url='https://testserver') as client:
        response = client.post('/admin/auth/logout',headers=headers())
    check(response,200)
    assert response.json() == {'success':True}
    assert_removed(response)
    assert events == ['confirmed','removed'] and threads['storage'] != threads['loop']
    assert service.method_calls == [('revoke',(TOKEN,),{})]


@pytest.mark.parametrize('kind',['valid','already_revoked','expired','missing','disabled'])
def test_real_service_idempotence_only_selected_session(sessions,kind):
    storage, service = sessions
    now = datetime.now(timezone.utc)
    selected = service.create(admin(),now=now-timedelta(hours=9) if kind == 'expired' else now)
    other = service.create(admin(),now=now)
    token = selected.token.get_secret_value()
    if kind == 'already_revoked': service.revoke(token,reason='manual_revocation')
    elif kind == 'missing': token = '0'*64
    elif kind == 'disabled': storage.data['admins/synthetic-admin']['status'] = 'disabled'
    before = copy.deepcopy(storage.data)
    other_before = service.get_session(other.token.get_secret_value())
    selected_before = service.get_session(selected.token.get_secret_value())
    with TestClient(app_for(service)) as client:
        for index in range(2):
            response = client.post('/admin/auth/logout',headers=headers(token))
            check(response,200)
            assert_removed(response)
            state = service.get_session(selected.token.get_secret_value())
            if index == 0: first_revocation = state
            else: assert state == first_revocation
        assert client.get('/admin/auth/session',headers=headers(token)).status_code == 401
    assert service.validate(token) is None
    assert service.get_session(other.token.get_secret_value()) == other_before
    assert set(storage.data) == set(before)
    assert storage.data['admins/synthetic-admin'] == before['admins/synthetic-admin']
    if kind == 'missing': assert storage.data == before
    revoked = service.get_session(selected.token.get_secret_value())
    if kind != 'missing': assert revoked.revoked_at is not None
    if kind == 'already_revoked': assert revoked == selected_before


@pytest.mark.parametrize('cookie', [None,'', 'invalid', TOKEN+'; '+NAME+'='+TOKEN])
def test_bad_cookie(cookie):
    service = Mock()
    h = headers()[:2]
    if cookie is not None: h.append(('Cookie',f'{NAME}={cookie}'))
    with TestClient(app_for(service)) as client:
        check(client.post('/admin/auth/logout',headers=h),401)
    assert service.mock_calls == []


@pytest.mark.parametrize('h', [headers()+[('Cookie',f'{NAME}={TOKEN}')],
    [('Origin',ORIGIN),('X-Admin-Request','1'),('Authorization','Bearer '+TOKEN)]])
def test_no_ambiguous_cookie_or_bearer_fallback(h):
    service = Mock()
    with TestClient(app_for(service)) as client:
        check(client.post('/admin/auth/logout',headers=h),401)
    assert service.mock_calls == []


@pytest.mark.parametrize('h', [headers()[1:], [('Origin','https://evil.test')]+headers()[1:],
    headers()+[('Origin',ORIGIN)], [headers()[0],headers()[2]],
    [('Origin',ORIGIN),('X-Admin-Request','wrong'),headers()[2]], headers()+[('X-Admin-Request','1')]])
def test_csrf_before_storage(h):
    service = Mock()
    with TestClient(app_for(service)) as client:
        check(client.post('/admin/auth/logout',headers=h),403)
    assert service.mock_calls == []


@pytest.mark.parametrize('target,content,status', [('/admin/auth/logout?token=synthetic','',400),
    ('/admin/auth/logout','{"token":"synthetic"}',400), ('/admin/auth/logout','{}',400)])
def test_reject_query_and_bodies(target,content,status):
    service = Mock()
    with TestClient(app_for(service)) as client:
        check(client.post(target,headers=headers(),content=content),status)
    assert service.mock_calls == []


def test_get_not_allowed():
    service = Mock()
    with TestClient(app_for(service)) as client:
        check(client.get('/admin/auth/logout',headers=headers()),405)
    assert service.mock_calls == []


@pytest.mark.parametrize('kind',['storage','timeout','unexpected'])
def test_uncertainty_never_clears_cookie(kind,caplog,capsys):
    service = Mock()
    if kind == 'unexpected': service.revoke.return_value = None
    else: service.revoke.side_effect = ServiceUnavailable(TOKEN+'synthetic-private') if kind == 'storage' else TimeoutError(TOKEN)
    with TestClient(app_for(service)) as client:
        response = client.post('/admin/auth/logout',headers=headers())
    check(response,503)
    assert 'success' not in response.json()
    output = capsys.readouterr()
    assert TOKEN not in response.text+output.out+output.err+caplog.text
    assert 'synthetic-private' not in response.text+output.out+output.err+caplog.text


def test_possible_commit_then_lost_confirmation(sessions,monkeypatch):
    _,service = sessions
    selected = service.create(admin())
    token = selected.token.get_secret_value()
    original = service.repository.revoke
    def uncertain(*args,**kwargs):
        original(*args,**kwargs)
        raise ServiceUnavailable('synthetic lost confirmation')
    with TestClient(app_for(service)) as client:
        with monkeypatch.context() as patch:
            patch.setattr(service.repository,'revoke',uncertain)
            check(client.post('/admin/auth/logout',headers=headers(token)),503)
        assert service.validate(token) is None
        response = client.post('/admin/auth/logout',headers=headers(token))
        check(response,200)
        assert_removed(response)


def test_public_main_unchanged(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-webhook')
    with TestClient(app) as client:
        assert client.post('/admin/auth/logout',headers=headers()).status_code == 404
        assert client.get('/health').status_code == 200
        assert client.post('/webhooks/kirvano',json={}).status_code == 401
