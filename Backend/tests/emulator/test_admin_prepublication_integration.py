"""PASSO 89: real demo persistence + public ASGI entry, never project-wide wipe."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import secrets

import pytest
from fastapi.testclient import TestClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.admin_entrypoint import create_admin_entrypoint, PublicAdminEntryConfiguration
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_admission_policy import load_admin_admission_policy
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.persistence.admin_records import AdminRecord
from app.persistence.collections import CollectionName as C
from app.services.admin_password_service import hash_admin_password
from app.tools import prepare_local_customer as tool
from test_local_customer_lookup_integration import emulator_client

pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'
API='https://api.example.test'
PASSWORD='synthetic step89 administrative password'


@pytest.fixture
def case(emulator_client):
    client,refs,owned=emulator_client
    tool.prepare_customer()
    identifier='step89-'+uuid4().hex
    now=datetime.now(timezone.utc)
    record=AdminRecord(admin_id=identifier,email_normalized=identifier+'@example.com',role='owner',
        status='enabled',created_by='bootstrap',created_at=now,updated_at=now,password_changed_at=now,
        password_hash=hash_admin_password(PASSWORD))
    admin=client.collection('admins').document(identifier)
    admin.create(record.to_document());owned.append(admin)
    config=PublicAdminEntryConfiguration(client,
        load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':secrets.token_hex(32)},env_file=None),
        AdminRequestSecurityConfig((ORIGIN,)),load_admin_admission_policy(selection='complementary-local-v1'))
    entry=create_admin_entrypoint(admin_configuration=config)
    entry.composition.admission_service.clock=lambda: now  # Fixed admission time, not wall-clock timing.
    repository=entry.composition.admission_service.repository
    original=repository.admit
    def track(identifiers,*args,**kwargs):
        owned.extend(client.collection('auth_throttles').document(key) for key in identifiers)
        return original(identifiers,*args,**kwargs)
    repository.admit=track  # Record exact IDs for cleanup, no behavior replacement.
    try:
        yield client,refs,admin,record,entry
    finally:
        owned.extend(row.reference for row in client.collection('admin_sessions').where(
            filter=FieldFilter('admin_id','==',identifier)).stream(timeout=10))
        owned.extend(row.reference for row in client.collection('activation_audit').where(
            filter=FieldFilter('customer_id','==',tool.USER_ID)).stream(timeout=10))


def h(ip='192.0.2.1'):
    return {'Origin':ORIGIN,'X-Admin-Request':'1','CF-Connecting-IP':ip}


def login(http,record,*,password=PASSWORD,ip='192.0.2.1',email=None):
    return http.post('/admin/auth/login',headers=h(ip),json={
        'email':email or record.email_normalized,'password':password})


@pytest.mark.parametrize('role',['owner','operator'])
def test_public_login_customer_lifecycle_and_audit(case,role):
    client,refs,admin,record,entry=case
    admin.update({'role':role})
    commerce={key:(refs[key].get().to_dict(),refs[key].get().update_time)
              for key in (C.PURCHASES,C.SUBSCRIPTIONS,C.ENTITLEMENTS)}
    with TestClient(entry,base_url=API) as http:
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code==401
        assert http.post('/admin/customers/lookup',headers=h(),json={'email':tool.EMAIL}).status_code==401
        preflight=http.options('/admin/auth/login',headers={'Origin':ORIGIN,
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-admin-request'})
        assert preflight.status_code==200 and preflight.headers['access-control-allow-origin']==ORIGIN
        assert preflight.headers['access-control-allow-credentials']=='true'
        assert login(http,record,password='incorrect synthetic password').status_code==401
        assert not list(client.collection('admin_sessions').where(filter=FieldFilter('admin_id','==',record.admin_id)).stream())
        response=login(http,record)
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert all(value in cookie for value in ('__Host-admin_session=','Secure','HttpOnly','SameSite=lax','Path=/'))
        assert 'Domain=' not in cookie
        token=http.cookies.get('__Host-admin_session')
        assert token not in response.text
        jar=next(c for c in http.cookies.jar if c.name=='__Host-admin_session')
        assert not jar.domain_specified and jar.domain=='api.example.test'
        # This is httpx cookie transport, NOT a browser SameSite policy test.
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).json()['role']==role
        assert http.get(ORIGIN+'/admin/auth/session',headers={'Origin':ORIGIN}).status_code==401
        found=http.post('/admin/customers/lookup',headers=h(),json={'email':' '+tool.EMAIL.upper()+' '})
        assert found.status_code==200 and found.json()['customer_id']==tool.USER_ID
        path='/admin/customers/'+tool.USER_ID
        assert http.get(path,headers=h()).json()==found.json()
        confirmation=http.get(path+'/purchase-confirmation',headers=h()).json()
        assert confirmation=={'customer_id':tool.USER_ID,'approved_purchase_recorded':True,
            'current_payment_validity':'not_verified','requires_kirvano_review':True}
        assert http.post(path+'/activate',headers={'Origin':ORIGIN},json={'confirm_activation':True}).status_code==403
        for operation,body,result in [('activate','confirm_activation','activated'),
            ('suspend','confirm_suspension','suspended'),('resume','confirm_resumption','resumed')]:
            response=http.post(path+'/'+operation,headers=h(),json={body:True})
            assert response.status_code==200, response.text
            assert response.json()['result']==result
        assert http.get(path,headers=h()).json()['activation_status']=='active'
        audits=list(client.collection('activation_audit').where(filter=FieldFilter('customer_id','==',tool.USER_ID)).stream())
        assert len(audits)==3
        from app.domain.admin_activation import CustomerActivationAudit
        from app.domain.admin_suspension import CustomerSuspensionAudit
        from app.domain.admin_resumption import CustomerResumptionAudit
        models={'activate_customer':CustomerActivationAudit,'suspend_customer':CustomerSuspensionAudit,
                'resume_customer':CustomerResumptionAudit}
        assert {row.to_dict()['operation'] for row in audits}==set(models)
        for row in audits:
            data=row.to_dict()
            assert data['admin_id']==record.admin_id and data['human_confirmation'] is True
            models[data['operation']].model_validate(data)
        assert http.post('/admin/auth/logout',headers=h()).json()=={'success':True}
        assert entry.composition.session_service.validate(token) is None
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token}).status_code==401
    for key,before in commerce.items():
        assert (refs[key].get().to_dict(),refs[key].get().update_time)==before


@pytest.mark.parametrize('state',['expired','disabled'])
def test_real_session_invalidation(case,state):
    client,_,admin,record,entry=case
    with TestClient(entry,base_url=API) as http:
        assert login(http,record).status_code==200
        if state=='disabled':
            admin.update({'status':'disabled'})
            assert login(http,record,ip='192.0.2.2').status_code==401
        else:
            end=datetime.now(timezone.utc)-timedelta(hours=1)
            rows=client.collection('admin_sessions').where(filter=FieldFilter('admin_id','==',record.admin_id)).stream()
            for row in rows:row.reference.update({'created_at':end-timedelta(hours=8),'expires_at':end})
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code==401


@pytest.mark.parametrize('scope',['identity','aggregate'])
def test_four_real_buckets_limit_rotated_cf(case,scope):
    client,_,_,record,entry=case
    budget=5 if scope=='identity' else 20
    with TestClient(entry,base_url=API) as http:
        for i in range(budget):
            email=record.email_normalized if scope=='identity' else f'missing-{i}-{record.admin_id}@example.com'
            assert login(http,record,password='incorrect synthetic password',ip=f'192.0.2.{i+1}',email=email).status_code==401
        authenticate=entry.composition.login_service.auth_service.authenticate
        def forbidden(*args):raise AssertionError('Admission must block authentication')
        entry.composition.login_service.auth_service.authenticate=forbidden
        try:
            response=login(http,record,ip='198.51.100.1')
            assert response.status_code==429 and response.headers['retry-after'] in ('30','60')
        finally:entry.composition.login_service.auth_service.authenticate=authenticate
    assert not list(client.collection('admin_sessions').where(filter=FieldFilter('admin_id','==',record.admin_id)).stream())
