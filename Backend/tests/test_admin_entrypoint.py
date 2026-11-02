"""Synthetic prepared entrypoint; no Render assumptions or Firebase network."""
from dataclasses import replace
from unittest.mock import Mock
import runpy

import pytest
from fastapi.testclient import TestClient

from app.admin_entrypoint import create_admin_entrypoint, AdminEntryConfiguration
from app.config.admin_admission_policy import load_admin_admission_policy
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.persistence.admin_records import AdminRecord
from test_admin_composition import config, ORIGIN
from test_admin_sessions import sessions


def settings(storage, **changes):
    # Explicit synthetic verifier, never claims to validate Render headers.
    base = AdminEntryConfiguration(storage,config(),AdminRequestSecurityConfig((ORIGIN,)),
        load_admin_admission_policy(selection='complementary-local-v1'),lambda request:'192.0.2.1')
    return replace(base,**changes)


def headers():
    return {'Origin':ORIGIN,'X-Admin-Request':'1'}


def login(http, **changes):
    return http.post('/admin/auth/login',headers=headers(),json={
        'email':'admin@example.com','password':'synthetic session admin password'} | changes)


@pytest.mark.parametrize('configuration',[None,{},True,'enabled'])
def test_default_or_untyped_config_disables_every_admin_path(configuration):
    entry = create_admin_entrypoint(admin_configuration=configuration)
    with TestClient(entry) as http:
        for path in ['/admin','/admin/','/admin/auth/session','/admin/customers','/admin/auth/login']:
            response = http.get(path,headers={'CF-Connecting-IP':'192.0.2.1'})
            assert response.status_code == 503
            assert response.headers['cache-control'] == 'no-store'
            assert 'set-cookie' not in response.headers
        assert http.get('/').json() == {'status':'online'}
        assert http.get('/health').status_code == 200
        assert http.get('/administrator').status_code == 404
    assert entry.composition is None


@pytest.mark.parametrize('changes',[{'firestore_client':None},{'admission_config':None},
    {'security_config':None},{'ingress_verifier':None},{'policy':None},
    {'ingress_verifier':'CF-Connecting-IP'}])
def test_invalid_config_cannot_publish_partial_branch(changes):
    storage = Mock()
    entry = create_admin_entrypoint(admin_configuration=settings(storage,**changes))
    with TestClient(entry) as http:
        assert login(http).status_code == 503
        assert http.get('/health').status_code == 200
    assert entry.composition is None and storage.mock_calls == []


def test_two_bucket_policy_not_silently_used():
    from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
    entry = create_admin_entrypoint(admin_configuration=settings(Mock(),policy=INITIAL_ADMIN_ADMISSION_POLICY))
    assert entry.composition is None


@pytest.mark.parametrize('value',[None,'','not-an-ip','192.0.2.1, 198.51.100.1'])
def test_unattested_headers_never_reach_storage(value):
    storage = Mock()
    verifier = Mock(return_value=value)
    entry = create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verifier))
    with TestClient(entry,base_url='https://testserver') as http:
        result=http.get('/admin/auth/session',headers={'Origin':ORIGIN,
            'CF-Connecting-IP':'192.0.2.1','X-Forwarded-For':'192.0.2.1'})
    assert result.status_code == 503
    assert result.headers['access-control-allow-origin'] == ORIGIN
    assert storage.mock_calls == []
    verifier.assert_called_once()


def test_cors_preflight_isolated_from_public_app():
    storage = Mock();verifier = Mock(return_value='192.0.2.1')
    entry=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verifier))
    with TestClient(entry,base_url='https://testserver') as http:
        h={'Origin':ORIGIN,'Access-Control-Request-Method':'POST',
           'Access-Control-Request-Headers':'content-type,x-admin-request'}
        response=http.options('/admin/auth/login',headers=h)
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']==ORIGIN
        assert response.headers['access-control-allow-credentials']=='true'
        assert '*' not in response.headers['access-control-allow-methods']
        assert http.options('/admin/auth/login',headers=h | {'Origin':'https://attacker.example.test'}).status_code==400
        assert 'access-control-allow-origin' not in http.get('/health',headers={'Origin':ORIGIN}).headers
        assert http.get('/admin/auth/session',headers={'Origin':'https://attacker.example.test'}).status_code==403
    assert storage.mock_calls==[]


def test_full_login_cookie_csrf_logout_and_mandatory_admission(sessions):
    storage,_=sessions
    verifier=Mock(return_value='::ffff:192.0.2.1')
    entry=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verifier))
    composition=entry.composition
    assert composition is not None
    composition.login_service.auth_service.repository.find_by_email=Mock(
        return_value=AdminRecord.from_document(storage.data['admins/synthetic-admin']))
    with TestClient(entry,base_url='https://testserver') as http:
        assert http.post('/admin/auth/login',json={}).status_code==403
        response=login(http)
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert all(part in cookie for part in ['__Host-admin_session=','HttpOnly','Secure','SameSite=lax','Path=/'])
        assert 'Domain=' not in cookie
        assert len([d for d in storage.data.values() if d.get('scope')])==4
        assert http.get('/admin/auth/session',headers=headers()).status_code==200
        assert http.post('/admin/auth/logout',headers={'Origin':ORIGIN}).status_code==403
        assert http.post('/admin/auth/logout',headers=headers()).status_code==200
        assert http.get('/admin/auth/session',headers=headers()).status_code==401
        composition.admission_service.repository.admit=Mock(side_effect=RuntimeError('synthetic-private'))
        auth=Mock();composition.login_service.auth_service.authenticate=auth
        response=login(http)
        assert response.status_code==503 and 'synthetic-private' not in response.text
        assert 'set-cookie' not in response.headers
        auth.assert_not_called()
    assert verifier.call_count>1


def test_unverified_ingress_blocks_even_valid_session(sessions):
    from test_admin_domain import admin
    storage,service=sessions
    token=service.create(admin()).token.get_secret_value()
    verifier=Mock(side_effect=RuntimeError('synthetic private ingress'))
    entry=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verifier))
    with TestClient(entry,base_url='https://testserver') as http:
        response=http.get('/admin/auth/session',headers=headers() | {'Cookie':'__Host-admin_session='+token})
    assert response.status_code==503 and token not in response.text
    assert 'synthetic private' not in response.text


def test_public_main_and_webhook_contract_unchanged(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-only')
    entry=create_admin_entrypoint(admin_configuration=settings(Mock()))
    with TestClient(entry) as http:
        assert http.post('/webhooks/kirvano',json={}).status_code==401
        assert http.get('/health').status_code==200
    with TestClient(app) as http:
        assert http.post('/admin/auth/login').status_code==404
    assert entry.public_app is app
    assert not any(getattr(route,'path','').startswith('/admin') for route in app.routes)


def test_import_does_not_load_configuration_or_firebase(monkeypatch):
    import app.admin_entrypoint as module
    forbidden=Mock(side_effect=AssertionError('No automatic initialization'))
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr('app.config.admin_admission.load_admin_admission_config',forbidden)
    runpy.run_path(module.__file__)
    forbidden.assert_not_called()


def test_plain_http_cannot_reach_ingress_or_administration():
    storage=Mock();verifier=Mock(return_value='192.0.2.1')
    entry=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verifier))
    with TestClient(entry,base_url='http://testserver') as http:
        assert login(http).status_code==503
    verifier.assert_not_called()
    assert storage.mock_calls==[]


def test_async_ingress_and_sync_threadpool_are_supported():
    from threading import get_ident
    storage=Mock();threads={}
    def verify(request):
        threads['verifier']=get_ident()
        return '192.0.2.1'
    entry=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=verify))
    original=entry.admin_app.app
    async def capture(scope,receive,send):
        threads['loop']=get_ident()
        return await original(scope,receive,send)
    entry.admin_app.app=capture
    with TestClient(entry,base_url='https://testserver') as http:
        # Missing Origin stops before Firestore even after verified ingress.
        assert http.get('/admin/auth/session').status_code==403
    assert threads['loop']!=threads['verifier']
    async def async_verify(request): return '192.0.2.1'
    second=create_admin_entrypoint(admin_configuration=settings(storage,ingress_verifier=async_verify))
    with TestClient(second,base_url='https://testserver') as http:
        assert http.get('/admin/auth/session').status_code==403
    assert storage.mock_calls==[]
