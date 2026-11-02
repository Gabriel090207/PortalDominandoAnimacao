"""Public authenticated composition ONLY in synthetic apps, never a Render probe."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.admin_entrypoint import create_admin_entrypoint, PublicAdminEntryConfiguration
from app.config.admin_admission_policy import load_admin_admission_policy
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_records import AdminRecord
from test_admin_composition import config, ORIGIN
from test_admin_sessions import sessions


def configuration(storage):
    return PublicAdminEntryConfiguration(storage,config(),AdminRequestSecurityConfig((ORIGIN,)),
        load_admin_admission_policy(selection='complementary-local-v1'))


@pytest.fixture
def public_entry(sessions):
    storage,_ = sessions
    entry = create_admin_entrypoint(admin_configuration=configuration(storage))
    auth = entry.composition.login_service.auth_service
    auth.repository.find_by_email = Mock(side_effect=lambda email:
        AdminRecord.from_document(storage.data['admins/synthetic-admin']) if email=='admin@example.com' else None)
    return storage,entry


def h(ip='192.0.2.1'):
    return {'Origin':ORIGIN,'X-Admin-Request':'1','CF-Connecting-IP':ip}


def login(http, ip='192.0.2.1', password='synthetic session admin password', email='admin@example.com'):
    return http.post('/admin/auth/login',headers=h(ip),json={'email':email,'password':password})


@pytest.mark.parametrize('role',['owner','operator'])
def test_direct_login_session_and_logout_without_private_ingress(public_entry,role):
    storage,entry=public_entry
    storage.data['admins/synthetic-admin']['role']=role
    with TestClient(entry,base_url='https://testserver') as http:
        for path in ['/admin/auth/session','/admin/customers','/admin/customers/synthetic-customer']:
            assert http.get(path,headers={'Origin':ORIGIN,'X-Admin-Role':'owner'}).status_code==401
        assert login(http,password='wrong synthetic password').status_code==401
        response=login(http)
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert all(p in cookie for p in ['Secure','HttpOnly','SameSite=lax','Path=/']) and 'Domain=' not in cookie
        assert len([d for d in storage.data.values() if d.get('scope')])==4
        # Session operations have no need for IP/CF, and still require a session.
        response=http.get('/admin/auth/session',headers={'Origin':ORIGIN})
        assert response.status_code==200 and response.json()['role']==role
        assert http.post('/admin/auth/logout',headers={'Origin':ORIGIN}).status_code==403
        assert http.post('/admin/auth/logout',headers={'Origin':ORIGIN,'X-Admin-Request':'1'}).status_code==200
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code==401


@pytest.mark.parametrize('failure',['missing','invalid','list','duplicate'])
def test_ip_failure_is_not_replaced_by_other_client_claims(public_entry,failure):
    storage,entry=public_entry
    login_service=entry.composition.login_service
    authenticate=Mock(wraps=login_service.authenticate)
    login_service.authenticate=authenticate
    headers=[('Origin',ORIGIN),('X-Admin-Request','1'),('X-Forwarded-For','198.51.100.1'),('X-Real-IP','198.51.100.1')]
    if failure!='missing': headers.append(('CF-Connecting-IP',{'invalid':'invalid','list':'192.0.2.1, 192.0.2.2','duplicate':'192.0.2.1'}[failure]))
    if failure=='duplicate':headers.append(('cf-connecting-ip','192.0.2.1'))
    before=dict(storage.data)
    with TestClient(entry,base_url='https://testserver') as http:
        response=http.post('/admin/auth/login',headers=headers,json={'email':'admin@example.com','password':'synthetic password'})
    assert response.status_code==503
    assert storage.data==before
    authenticate.assert_not_called()


def test_forged_cf_rotation_cannot_reset_identity_budget(public_entry,monkeypatch):
    storage,entry=public_entry
    with TestClient(entry,base_url='https://testserver') as http:
        for i in range(5):
            assert login(http,f'192.0.2.{i+1}',password='wrong synthetic password',email=' ADMIN@EXAMPLE.COM ').status_code==401
        verify=Mock(side_effect=AssertionError('Argon2 must not start'))
        monkeypatch.setattr('app.services.admin_auth_service.verify_admin_password',verify)
        assert login(http,'198.51.100.1').status_code==429
        verify.assert_not_called()
    assert not any(p.startswith('admin_sessions/') for p in storage.data)


def test_distributed_identity_rotation_hits_aggregate(public_entry):
    storage,entry=public_entry
    with TestClient(entry,base_url='https://testserver') as http:
        for i in range(20):
            assert login(http,f'192.0.2.{i+1}',email=f'missing{i}@example.com').status_code==401
        assert login(http,'198.51.100.1').status_code==429
    assert not any(p.startswith('admin_sessions/') for p in storage.data)


@pytest.mark.parametrize('change',[{'policy':INITIAL_ADMIN_ADMISSION_POLICY},{'policy':None},
    {'admission_config':None},{'firestore_client':None},{'security_config':None}])
def test_incomplete_public_config_disables_whole_branch(change):
    storage=Mock()
    entry=create_admin_entrypoint(admin_configuration=replace(configuration(storage),**change))
    with TestClient(entry,base_url='https://testserver') as http:
        assert login(http).status_code==503
        assert http.get('/admin/auth/session',headers=h()).status_code==503
        assert http.get('/health').status_code==200
    assert entry.composition is None and storage.mock_calls==[]


def test_origin_and_csrf_remain_mandatory(public_entry):
    storage,entry=public_entry
    before=dict(storage.data)
    with TestClient(entry,base_url='https://testserver') as http:
        assert http.post('/admin/auth/login',headers=h() | {'Origin':'https://attacker.example.test'},json={}).status_code==403
        assert http.post('/admin/auth/login',headers={'Origin':ORIGIN,'CF-Connecting-IP':'192.0.2.1'},json={}).status_code==403
    assert storage.data==before


@pytest.mark.parametrize('state',['expired','disabled'])
def test_session_invalidated_without_ip_dependency(public_entry,state):
    storage,entry=public_entry
    with TestClient(entry,base_url='https://testserver') as http:
        assert login(http).status_code==200
        if state=='disabled': storage.data['admins/synthetic-admin']['status']='disabled'
        else:
            for path,doc in storage.data.items():
                if path.startswith('admin_sessions/'):
                    end=datetime.now(timezone.utc)-timedelta(hours=1)
                    doc.update(created_at=end-timedelta(hours=8),expires_at=end)
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code==401


def test_authenticated_permission_denial_is_not_overridden_by_headers(public_entry,monkeypatch):
    _,entry=public_entry
    with TestClient(entry,base_url='https://testserver') as http:
        assert login(http).status_code==200
        # Current owner/operator have all operational permissions. Exercise the
        # denial branch explicitly, without inventing a new production role.
        monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
        response=http.get('/admin/customers',headers=h() | {'X-Admin-Role':'owner','X-Admin-Permission':'read_customers'})
        assert response.status_code==403


@pytest.mark.parametrize('layer',['admission','session'])
def test_infrastructure_failure_is_unavailable_not_authorized(public_entry,layer):
    _,entry=public_entry
    with TestClient(entry,base_url='https://testserver') as http:
        if layer=='admission':
            entry.composition.admission_service.repository.admit=Mock(side_effect=RuntimeError('synthetic-private'))
            auth=Mock();entry.composition.login_service.auth_service.authenticate=auth
            response=login(http)
            auth.assert_not_called()
        else:
            assert login(http).status_code==200
            entry.composition.session_service.validate=Mock(side_effect=RuntimeError('synthetic-private'))
            response=http.get('/admin/auth/session',headers={'Origin':ORIGIN})
        assert response.status_code==503
        assert 'synthetic-private' not in response.text and 'set-cookie' not in response.headers


def test_public_mode_still_does_not_enable_main_or_default(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-token')
    for application in [app,create_admin_entrypoint()]:
        with TestClient(application) as http:
            assert http.get('/health').status_code==200
            assert http.post('/webhooks/kirvano',json={}).status_code==401
            assert http.get('/admin/auth/session').status_code in (404,503)
    assert not any(getattr(r,'path','').startswith('/admin') for r in app.routes)


def test_public_transport_cors_and_sanitization(public_entry,caplog,capsys):
    _,entry=public_entry
    with TestClient(entry,base_url='http://testserver') as http:
        assert login(http).status_code==503
    with TestClient(entry,base_url='https://testserver') as http:
        preflight={'Origin':ORIGIN,'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'content-type,x-admin-request'}
        response=http.options('/admin/auth/login',headers=preflight)
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']==ORIGIN
        assert response.headers['access-control-allow-credentials']=='true'
        assert http.options('/admin/auth/login',headers=preflight | {'Origin':'https://attacker.example.test'}).status_code==400
        response=login(http,password='synthetic-private-password')
        assert response.status_code==401
        assert 'synthetic-private-password' not in response.text
    out=capsys.readouterr()
    assert 'synthetic-private-password' not in out.out+out.err+caplog.text
