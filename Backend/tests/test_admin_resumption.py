"""Synthetic resumption provenance, eligibility, audit and HTTP contracts."""
from app.domain.models import PortalEntitlement
import copy
from datetime import timedelta
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.admin_customers import create_admin_customers_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_activation import CustomerActivationAudit
from app.domain.admin_suspension import CustomerSuspensionAudit
from app.domain.admin_resumption import CustomerResumptionConflict,CustomerResumptionUnavailable,CustomerResumptionResult
from app.domain.admin_customers import InvalidCustomerIdentifier
from app.persistence.admin_resumption_repository import AdminResumptionRepository
from test_admin_activation import harness as activation_harness
from test_admin_customers import headers
from test_admin_domain import admin
from test_admin_sessions import sessions
PATH='/admin/customers/customer-a/resume'

def harness(monkeypatch,mode='normal'):
    previous,data,client=activation_harness(monkeypatch,mode)
    now=previous.clock()
    data['users/customer-a']['activation_status']='suspended'
    data['activation_audit/initial']=CustomerActivationAudit(admin_id='synthetic-admin',customer_id='customer-a',occurred_at=now-timedelta(seconds=1)).model_dump()
    data['activation_audit/restriction']=CustomerSuspensionAudit(admin_id='synthetic-admin',customer_id='customer-a',occurred_at=now-timedelta(microseconds=1)).model_dump()
    return AdminResumptionRepository(client,clock=previous.clock),data,client

def test_missing_and_invalid(monkeypatch):
    repo,data,client=harness(monkeypatch)
    with pytest.raises(InvalidCustomerIdentifier):repo.resume('a/b',admin())
    client.collection.assert_not_called()
    del data['users/customer-a'];assert repo.resume('customer-a',admin()) is None


def app_for(session,service):
    app=FastAPI();app.include_router(create_admin_customers_router(session_service=session,customers_service=Mock(),
        security_config=AdminRequestSecurityConfig(('https://admin.example.test',)),resumption_service=service));return app

def h():return dict(headers())|{'X-Admin-Request':'1','Content-Type':'application/json'}

@pytest.mark.parametrize('role',['owner','operator'])
def test_http_authority_from_session(role):
    session=Mock();session.validate.return_value=admin(role=role);service=Mock()
    service.resume.return_value=CustomerResumptionResult(customer_id='customer-a',result='resumed')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_resumption':True})
    assert r.status_code==200 and r.json()=={'customer_id':'customer-a','activation_status':'active','result':'resumed'}
    assert r.headers['cache-control']=='no-store'
    service.resume.assert_called_once_with('customer-a',admin(role=role))

@pytest.mark.parametrize('body',['','{}','[]','null','{"confirm_resumption":false}','{"confirm_resumption":1}',
    '{"confirm_resumption":true,"admin_id":"other"}','{"confirm_resumption":true,"confirm_resumption":true}','{bad'])
def test_invalid_body_no_write(body):
    session=Mock();session.validate.return_value=admin();service=Mock()
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),content=body)
    assert r.status_code==400 and r.headers['cache-control']=='no-store';service.resume.assert_not_called()

@pytest.mark.parametrize('kind,status',[('origin',403),('csrf',403),('content',415),('large',413),('query',400),('id',400),('permission',403),('get',405)])
def test_protocol_rejection(monkeypatch,kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock();headers=h();path=PATH;body='{"confirm_resumption":true}'
    if kind=='origin':headers['Origin']='https://evil.test'
    if kind=='csrf':del headers['X-Admin-Request']
    if kind=='content':headers['Content-Type']='text/plain'
    if kind=='large':body=' '*4097
    if kind=='query':path+='?customer_id=other'
    if kind=='id':path=path.replace('customer-a','__bad__')
    if kind=='permission':monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    with TestClient(app_for(session,service)) as http:r=http.get(path,headers=headers) if kind=='get' else http.post(path,headers=headers,content=body)
    assert r.status_code==status and r.headers['cache-control']=='no-store';service.resume.assert_not_called()

@pytest.mark.parametrize('kind,status',[('missing',404),('conflict',409),('uncertain',503)])
def test_http_failure_sanitized(kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock()
    if kind=='missing':service.resume.return_value=None
    else:service.resume.side_effect=CustomerResumptionConflict() if kind=='conflict' else RuntimeError('synthetic-private')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_resumption':True})
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
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=headers,json={'confirm_resumption':True})
    assert r.status_code==401;service.resume.assert_not_called()

def test_unpublished():
    from app.main import app
    with TestClient(app) as http:assert http.post(PATH,json={'confirm_resumption':True}).status_code==404

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
    monkeypatch.setattr('app.persistence.admin_resumption_repository.firestore.transactional',exhausted)
    with pytest.raises(CustomerResumptionUnavailable) as caught:repo.resume('customer-a',admin())
    assert len(calls)==1 and data==before and 'synthetic-private' not in str(caught.value)


@pytest.mark.parametrize('role',['owner','operator'])
def test_atomic_provenance_commercial_access_audit_and_idempotence(monkeypatch,role):
    from app.domain.models import UserAccessState,Entitlement
    from app.services.access_service import can_access_portal
    repo,data,client=harness(monkeypatch)
    data['admins/synthetic-admin']['role']=role
    data['subscriptions/sentinel']={'status':'canceled','unknown':'preserved'}
    before=copy.deepcopy(data)
    right=next(v for k,v in data.items() if k.startswith('entitlements/'))
    entitlement=PortalEntitlement(purchase_id="synthetic-purchase",subscription_id="synthetic-subscription",subscription_status="active",**{k:right[k] for k in ('user_id','resource_key','status','valid_from','valid_until')})
    assert not can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='suspended'),[entitlement],now=repo.clock())
    assert repo.resume('customer-a',admin(role=role)).result=='resumed'
    assert data['users/customer-a']==before['users/customer-a']|{'activation_status':'active'}
    for key,value in before.items():
        if key!='users/customer-a':assert data[key]==value
    audits=[v for k,v in data.items() if k.startswith('activation_audit/') and k not in before]
    assert audits==[dict(schema_version=1,admin_id='synthetic-admin',customer_id='customer-a',operation='resume_customer',
        previous_activation_status='suspended',activation_status='active',human_confirmation=True,occurred_at=repo.clock())]
    resumed=copy.deepcopy(data)
    assert repo.resume('customer-a',admin(role=role)).result=='already_active' and data==resumed
    assert can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[entitlement],now=repo.clock())
    assert all(call.kwargs=={'max_attempts':8} for call in client.transaction.call_args_list)

@pytest.mark.parametrize('kind',['pending','blocked','blocked_active','missing_actor','disabled','version','role',
    'missing_initial','missing_suspension','only_suspension','old_user','future_suspension','wrong_chronology',
    'missing_purchase','foreign_purchase','pending_purchase','expired_purchase','future_purchase',
    'missing_right','revoked_right','expired_right','foreign_right','wrong_purchase'])
def test_rejected_preconditions_never_write(monkeypatch,kind):
    repo,data,_=harness(monkeypatch);user=data['users/customer-a'];actor=data['admins/synthetic-admin']
    right_key=next(k for k in data if k.startswith('entitlements/'));purchase=data['purchases/purchase-a']
    if kind=='pending':user['activation_status']='pending'
    if kind.startswith('blocked'):user['account_status']='blocked'
    if kind=='blocked_active':user['activation_status']='active'
    if kind=='missing_actor':del data['admins/synthetic-admin']
    if kind=='disabled':actor['status']='disabled'
    if kind=='version':actor['auth_version']=2
    if kind=='role':actor['role']='operator'
    if kind in ('missing_initial','only_suspension'):del data['activation_audit/initial']
    if kind=='missing_suspension':del data['activation_audit/restriction']
    if kind=='old_user':user['created_at']=repo.clock()
    if kind=='future_suspension':data['activation_audit/restriction']['occurred_at']=repo.clock()+timedelta(seconds=1)
    if kind=='wrong_chronology':data['activation_audit/initial']['occurred_at']=repo.clock()
    if kind=='missing_purchase':del data['purchases/purchase-a']
    if kind=='foreign_purchase':purchase['user_id']='other'
    if kind=='pending_purchase':purchase['status']='pending'
    if kind=='expired_purchase':purchase['valid_until']=purchase['valid_from']
    if kind=='future_purchase':purchase['valid_from']=purchase['valid_until']
    if kind=='missing_right':del data[right_key]
    if kind=='revoked_right':data[right_key]['status']='revoked'
    if kind=='expired_right':data[right_key]['valid_until']=repo.clock()
    if kind=='foreign_right':data[right_key]['user_id']='other'
    if kind=='wrong_purchase':data[right_key]['purchase_id']='other'
    before=copy.deepcopy(data)
    with pytest.raises(CustomerResumptionConflict):repo.resume('customer-a',admin())
    assert data==before

@pytest.mark.parametrize('audit',['initial','restriction'])
@pytest.mark.parametrize('change',['missing_field','false_confirmation','int_confirmation','bool_version','wrong_transition','foreign_customer','invalid_actor','naive_time'])
def test_missing_or_malformed_provenance_denied_without_inventing_defaults(monkeypatch,audit,change):
    repo,data,_=harness(monkeypatch);record=data['activation_audit/'+audit]
    if change=='missing_field':del record['previous_activation_status']
    if change=='false_confirmation':record['human_confirmation']=False
    if change=='int_confirmation':record['human_confirmation']=1
    if change=='bool_version':record['schema_version']=True
    if change=='wrong_transition':record['previous_activation_status']='blocked'
    if change=='foreign_customer':record['customer_id']='other'
    if change=='invalid_actor':record['admin_id']='not/a/reference'
    if change=='naive_time':record['occurred_at']=repo.clock().replace(tzinfo=None)
    before=copy.deepcopy(data)
    with pytest.raises(CustomerResumptionConflict):repo.resume('customer-a',admin())
    assert data==before

@pytest.mark.parametrize('mode',['before','audit_failure','uncertain'])
def test_failure_no_partial_transition_or_false_success(monkeypatch,mode,caplog):
    repo,data,client=harness(monkeypatch,mode);before=copy.deepcopy(data)
    with pytest.raises(CustomerResumptionUnavailable) as caught:repo.resume('customer-a',admin())
    assert str(caught.value)=='Customer resumption not confirmed.'
    assert 'synthetic-private' not in str(caught.value)+caplog.text and client.transaction.call_count==1
    if mode=='uncertain':
        assert data['users/customer-a']['activation_status']=='active'
        assert len([k for k in data if k.startswith('activation_audit/')])==3
    else:assert data==before


def test_already_active_is_noop_without_claiming_commercial_access_or_resumption(monkeypatch):
    repo,data,client=harness(monkeypatch);data['users/customer-a']['activation_status']='active'
    for key in list(data):
        if key.startswith(('activation_audit/','purchases/','entitlements/')):del data[key]
    before=copy.deepcopy(data)
    assert repo.resume('customer-a',admin()).result=='already_active' and data==before
    assert {call.args[0] for call in client.collection.call_args_list}<={'users','admins','activation_audit'}
