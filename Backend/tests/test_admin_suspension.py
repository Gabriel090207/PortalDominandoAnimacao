"""Manual restriction contracts using the existing synthetic transactional store."""
import copy
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.admin_customers import create_admin_customers_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_suspension import CustomerSuspensionConflict,CustomerSuspensionUnavailable,CustomerSuspensionResult
from app.domain.admin_customers import InvalidCustomerIdentifier
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from test_admin_activation import harness as activation_harness
from test_admin_customers import headers
from test_admin_domain import admin
from test_admin_sessions import sessions
PATH='/admin/customers/customer-a/suspend'

def harness(monkeypatch,mode='normal'):
    previous,data,client=activation_harness(monkeypatch,mode)
    data['users/customer-a']['activation_status']='active'
    return AdminSuspensionRepository(client,clock=previous.clock),data,client

def test_missing_and_invalid(monkeypatch):
    repo,data,client=harness(monkeypatch)
    with pytest.raises(InvalidCustomerIdentifier):repo.suspend('a/b',admin())
    client.collection.assert_not_called()
    del data['users/customer-a'];assert repo.suspend('customer-a',admin()) is None


def app_for(session,service):
    app=FastAPI();app.include_router(create_admin_customers_router(session_service=session,customers_service=Mock(),
        security_config=AdminRequestSecurityConfig(('https://admin.example.test',)),suspension_service=service));return app

def h():return dict(headers())|{'X-Admin-Request':'1','Content-Type':'application/json'}

@pytest.mark.parametrize('role',['owner','operator'])
def test_http_authority_from_session(role):
    session=Mock();session.validate.return_value=admin(role=role);service=Mock()
    service.suspend.return_value=CustomerSuspensionResult(customer_id='customer-a',result='suspended')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_suspension':True})
    assert r.status_code==200 and r.json()=={'customer_id':'customer-a','activation_status':'suspended','result':'suspended'}
    assert r.headers['cache-control']=='no-store'
    service.suspend.assert_called_once_with('customer-a',admin(role=role))

@pytest.mark.parametrize('body',['','{}','[]','null','{"confirm_suspension":false}','{"confirm_suspension":1}',
    '{"confirm_suspension":true,"admin_id":"other"}','{"confirm_suspension":true,"confirm_suspension":true}','{bad'])
def test_invalid_body_no_write(body):
    session=Mock();session.validate.return_value=admin();service=Mock()
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),content=body)
    assert r.status_code==400 and r.headers['cache-control']=='no-store';service.suspend.assert_not_called()

@pytest.mark.parametrize('kind,status',[('origin',403),('csrf',403),('content',415),('large',413),('query',400),('id',400),('permission',403),('get',405)])
def test_protocol_rejection(monkeypatch,kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock();headers=h();path=PATH;body='{"confirm_suspension":true}'
    if kind=='origin':headers['Origin']='https://evil.test'
    if kind=='csrf':del headers['X-Admin-Request']
    if kind=='content':headers['Content-Type']='text/plain'
    if kind=='large':body=' '*4097
    if kind=='query':path+='?customer_id=other'
    if kind=='id':path=path.replace('customer-a','__bad__')
    if kind=='permission':monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    with TestClient(app_for(session,service)) as http:r=http.get(path,headers=headers) if kind=='get' else http.post(path,headers=headers,content=body)
    assert r.status_code==status and r.headers['cache-control']=='no-store';service.suspend.assert_not_called()

@pytest.mark.parametrize('kind,status',[('missing',404),('conflict',409),('uncertain',503)])
def test_http_failure_sanitized(kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock()
    if kind=='missing':service.suspend.return_value=None
    else:service.suspend.side_effect=CustomerSuspensionConflict() if kind=='conflict' else RuntimeError('synthetic-private')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_suspension':True})
    assert r.status_code==status and r.headers['cache-control']=='no-store' and 'synthetic-private' not in r.text

@pytest.mark.parametrize('kind',['invalid','absent','disabled','revoked'])
def test_invalid_session(sessions,kind):
    data,session=sessions;token=session.create(admin()).token.get_secret_value()
    if kind=='invalid':token='bad'
    if kind=='disabled':data.data['admins/synthetic-admin']['status']='disabled'
    if kind=='revoked':session.revoke(token)
    headers=dict(h());headers['Cookie']='__Host-admin_session='+token
    if kind=='absent':del headers['Cookie']
    service=Mock()
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=headers,json={'confirm_suspension':True})
    assert r.status_code==401;service.suspend.assert_not_called()

def test_unpublished():
    from app.main import app
    with TestClient(app) as http:assert http.post(PATH,json={'confirm_suspension':True}).status_code==404

@pytest.mark.parametrize('wrapped',[False,True])
def test_sdk_contention_exhaustion_is_unconfirmed_without_external_retry(monkeypatch,wrapped):
    from google.api_core.exceptions import Aborted
    repo,data,client=harness(monkeypatch);before=copy.deepcopy(data);calls=[]
    def exhausted(fn):
        def run(*args):
            calls.append(1)
            error=Aborted('synthetic-private')
            if wrapped:
                try:raise error
                except Aborted as cause:raise ValueError('synthetic-private') from cause
            raise error
        return run
    monkeypatch.setattr('app.persistence.admin_suspension_repository.firestore.transactional',exhausted)
    with pytest.raises(CustomerSuspensionUnavailable) as caught:repo.suspend('customer-a',admin())
    assert len(calls)==1 and data==before and 'synthetic-private' not in str(caught.value)

@pytest.mark.parametrize('role',['owner','operator'])
def test_atomic_restriction_and_idempotence(monkeypatch,role):
    from app.domain.models import UserAccessState,Entitlement
    from app.services.access_service import can_access_portal
    repo,data,client=harness(monkeypatch)
    data['admins/synthetic-admin']['role']=role
    data['subscriptions/sentinel']={'status':'active','unknown':'preserved'}
    before=copy.deepcopy(data)
    right=next(v for k,v in data.items() if k.startswith('entitlements/'))
    entitlement=Entitlement(**{k:right[k] for k in ('user_id','resource_key','status','valid_from','valid_until')})
    assert can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[entitlement],now=repo.clock())
    assert repo.suspend('customer-a',admin(role=role)).result=='suspended'
    assert data['users/customer-a']==before['users/customer-a']|{'activation_status':'suspended'}
    for key,value in before.items():
        if key!='users/customer-a':assert data[key]==value
    audits=[v for k,v in data.items() if k.startswith('activation_audit/')]
    assert len(audits)==1
    assert audits[0]==dict(schema_version=1,admin_id='synthetic-admin',customer_id='customer-a',
        operation='suspend_customer',previous_activation_status='active',activation_status='suspended',
        human_confirmation=True,occurred_at=repo.clock())
    suspended=copy.deepcopy(data)
    assert repo.suspend('customer-a',admin(role=role)).result=='already_suspended'
    assert data==suspended
    assert not can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='suspended'),[entitlement],now=repo.clock())
    assert {call.args[0] for call in client.collection.call_args_list}<={'users','admins','activation_audit'}
    assert all(call.kwargs=={'max_attempts':5} for call in client.transaction.call_args_list)

@pytest.mark.parametrize('kind',['pending','blocked','blocked_suspended','disabled','version','role','missing_actor'])
def test_transition_and_actor_rejected_without_writes(monkeypatch,kind):
    repo,data,_=harness(monkeypatch)
    if kind=='pending':data['users/customer-a']['activation_status']='pending'
    if kind.startswith('blocked'):data['users/customer-a']['account_status']='blocked'
    if kind=='blocked_suspended':data['users/customer-a']['activation_status']='suspended'
    if kind=='disabled':data['admins/synthetic-admin']['status']='disabled'
    if kind=='version':data['admins/synthetic-admin']['auth_version']=2
    if kind=='role':data['admins/synthetic-admin']['role']='operator'
    if kind=='missing_actor':del data['admins/synthetic-admin']
    before=copy.deepcopy(data)
    with pytest.raises(CustomerSuspensionConflict):repo.suspend('customer-a',admin())
    assert data==before

@pytest.mark.parametrize('mode',['before','audit_failure','uncertain'])
def test_transaction_failure_no_false_success(monkeypatch,mode,caplog):
    repo,data,client=harness(monkeypatch,mode);before=copy.deepcopy(data)
    with pytest.raises(CustomerSuspensionUnavailable) as caught:repo.suspend('customer-a',admin())
    assert str(caught.value)=='Customer suspension not confirmed.'
    assert 'synthetic-private' not in str(caught.value)+caplog.text
    assert client.transaction.call_count==1
    if mode=='uncertain':
        assert data['users/customer-a']['activation_status']=='suspended'
        assert len([k for k in data if k.startswith('activation_audit/')])==1
    else:assert data==before


def test_no_commercial_record_required(monkeypatch):
    repo,data,_=harness(monkeypatch)
    for key in list(data):
        if key.startswith(('purchases/','entitlements/')):del data[key]
    assert repo.suspend('customer-a',admin()).result=='suspended'
