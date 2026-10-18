"""Synthetic transactional activation, audit and HTTP contracts."""
from app.domain.models import PortalEntitlement
import copy
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.admin_customers import create_admin_customers_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_activation import CustomerActivationConflict,CustomerActivationUnavailable,CustomerActivationResult
from app.domain.admin_customers import InvalidCustomerIdentifier
from app.domain.models import UserAccessState,Entitlement
from app.services.access_service import can_access_portal
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.services.admin_activation_service import AdminActivationService
from app.services.kirvano_event_service import digest
from test_admin_customers import document,headers
from test_admin_domain import admin
from test_admin_purchase_confirmation import purchase
from test_admin_sessions import sessions
PATH='/admin/customers/customer-a/activate'

def records():
    from test_kirvano_commerce_transaction import Client,receive,docs,payload
    commerce=Client();receive(commerce,payload())
    p=next(iter(docs(commerce,'purchases').values()));p['user_id']='customer-a'
    subscription=next(iter(docs(commerce,'subscriptions').values()));subscription['user_id']='customer-a'
    right_id=digest(['kirvano-entitlement',1,'purchase-a','portal'])
    return {'users/customer-a':document(),'admins/synthetic-admin':admin().model_dump(),
        'subscriptions/'+p['subscription_id']:subscription,
        'purchases/purchase-a':p,'entitlements/'+right_id:dict(schema_version=1,identity_version=1,
            purchase_id='purchase-a',user_id='customer-a',resource_key='portal',status='granted',
            valid_from=p['valid_from'],valid_until=p['valid_until'],created_at=p['created_at'])}


def harness(monkeypatch,mode='normal'):
    data=records();client=Mock();writes=[];filters=[]
    now=data['purchases/purchase-a']['valid_from']+timedelta(seconds=1)
    class Collection:
        def __init__(self,name):self.name=name;self.filters=[];self.bound=None;self.after=None
        def document(self,id):
            path=self.name+'/'+id
            def get(**kwargs):
                assert not writes
                return SimpleNamespace(exists=path in data,id=id,to_dict=lambda:copy.deepcopy(data.get(path)))
            return SimpleNamespace(path=path,get=get)
        def where(self,*,filter):self.filters.append(filter);filters.append(filter);return self
        def start_after(self,snapshot):self.after=snapshot.id;return self
        def limit(self,value):assert value==1;self.bound=value;return self
        def stream(self,**kwargs):
            assert self.bound==1 and not writes
            def matches(value):
                for f in self.filters:
                    actual=value.get(f.field_path)
                    if f.op_string=='==' and actual!=f.value:return False
                    if f.op_string=='<=' and actual>f.value:return False
                    if f.op_string=='>' and actual<=f.value:return False
                return True
            entries=[(k,v) for k,v in data.items() if k.startswith(self.name+'/') and matches(v)]
            if self.after is not None:
                index=next(i for i,(k,_) in enumerate(entries) if k.split('/')[1]==self.after)
                entries=entries[index+1:]
            return [SimpleNamespace(id=k.split('/')[1],to_dict=lambda v=v:copy.deepcopy(v)) for k,v in entries][:1]
    client.collection.side_effect=Collection
    tx=Mock()
    tx.update.side_effect=lambda ref,value:writes.append(('update',ref.path,value))
    def create(ref,value):
        if mode=='audit_failure':raise RuntimeError('synthetic-private')
        writes.append(('create',ref.path,value))
    tx.create.side_effect=create;client.transaction.return_value=tx
    def runner(fn):
        def run(transaction,*args):
            if mode=='before':raise RuntimeError('synthetic-private')
            result=fn(transaction,*args)
            committed=copy.deepcopy(data)
            for op,path,value in writes:
                if op=='create':assert path not in committed;committed[path]=value
                else:committed[path].update(value)
            data.clear();data.update(committed);writes.clear()
            if mode=='uncertain':raise RuntimeError('synthetic-private')
            return result
        return run
    monkeypatch.setattr('app.persistence.admin_activation_repository.firestore.transactional',runner)
    return AdminActivationRepository(client,clock=lambda:now),data,client

@pytest.mark.parametrize('role',['owner','operator'])
def test_atomic_transition_audit_and_idempotence(monkeypatch,role):
    repo,data,_=harness(monkeypatch);before=copy.deepcopy(data)
    state=UserAccessState(account_status='enabled',activation_status='pending')
    right=next(v for k,v in data.items() if k.startswith('entitlements/'))
    entitlement=PortalEntitlement(purchase_id="synthetic-purchase",subscription_id="synthetic-subscription",subscription_status="active",**{k:right[k] for k in ('user_id','resource_key','status','valid_from','valid_until')})
    now=right['valid_from']+timedelta(seconds=1)
    assert not can_access_portal('customer-a',state,[entitlement],now=now)
    data['admins/synthetic-admin']['role']=role
    assert repo.activate('customer-a',admin(role=role)).result=='activated'
    assert data['users/customer-a']==before['users/customer-a']|{'activation_status':'active'}
    for key in before:
        if key.startswith(('purchases/','entitlements/')):assert data[key]==before[key]
    audits=[v for k,v in data.items() if k.startswith('activation_audit/')]
    assert len(audits)==1 and audits[0]['admin_id']=='synthetic-admin'
    assert audits[0]['previous_activation_status']=='pending' and audits[0]['activation_status']=='active'
    assert audits[0]['customer_id']=='customer-a' and audits[0]['human_confirmation'] is True
    assert repo.activate('customer-a',admin(role=role)).result=='already_active'
    assert len([k for k in data if k.startswith('activation_audit/')])==1
    assert can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[entitlement],now=now)

@pytest.mark.parametrize('kind',['blocked','suspended','no_purchase','foreign_purchase','pending_purchase','expired',
    'future','no_entitlement','revoked_right','foreign_right','admin_disabled','version'])
def test_preconditions_fail_without_writes(monkeypatch,kind):
    repo,data,_=harness(monkeypatch)
    p=data['purchases/purchase-a'];right_key=next(k for k in data if k.startswith('entitlements/'))
    if kind=='blocked':data['users/customer-a']['account_status']='blocked'
    if kind=='suspended':data['users/customer-a']['activation_status']='suspended'
    if kind=='no_purchase':del data['purchases/purchase-a']
    if kind=='foreign_purchase':p['user_id']='other'
    if kind=='pending_purchase':p['status']='pending'
    if kind=='expired':p['valid_until']=p['valid_from']
    if kind=='future':p['valid_from']=p['valid_until']
    if kind=='no_entitlement':del data[right_key]
    if kind=='revoked_right':data[right_key]['status']='revoked'
    if kind=='foreign_right':data[right_key]['user_id']='other'
    if kind=='admin_disabled':data['admins/synthetic-admin']['status']='disabled'
    if kind=='version':data['admins/synthetic-admin']['auth_version']=2
    before=copy.deepcopy(data)
    with pytest.raises(CustomerActivationConflict):repo.activate('customer-a',admin())
    assert data==before

@pytest.mark.parametrize('mode',['before','audit_failure','uncertain'])
def test_failure_never_confirms_success(monkeypatch,mode):
    repo,data,_=harness(monkeypatch,mode);before=copy.deepcopy(data)
    with pytest.raises(CustomerActivationUnavailable) as caught:repo.activate('customer-a',admin())
    assert str(caught.value)=='Customer activation not confirmed.'
    if mode=='uncertain':
        assert data['users/customer-a']['activation_status']=='active'
        assert len([k for k in data if k.startswith('activation_audit/')])==1
    else:assert data==before

def test_missing_and_invalid(monkeypatch):
    repo,data,client=harness(monkeypatch)
    with pytest.raises(InvalidCustomerIdentifier):repo.activate('a/b',admin())
    client.collection.assert_not_called()
    del data['users/customer-a'];assert repo.activate('customer-a',admin()) is None


def app_for(session,service):
    app=FastAPI();app.include_router(create_admin_customers_router(session_service=session,customers_service=Mock(),
        security_config=AdminRequestSecurityConfig(('https://admin.example.test',)),activation_service=service));return app

def h():return dict(headers())|{'X-Admin-Request':'1','Content-Type':'application/json'}

@pytest.mark.parametrize('role',['owner','operator'])
def test_http_authority_from_session(role):
    session=Mock();session.validate.return_value=admin(role=role);service=Mock()
    service.activate.return_value=CustomerActivationResult(customer_id='customer-a',result='activated')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_activation':True})
    assert r.status_code==200 and r.json()=={'customer_id':'customer-a','activation_status':'active','result':'activated'}
    assert r.headers['cache-control']=='no-store'
    service.activate.assert_called_once_with('customer-a',admin(role=role))

@pytest.mark.parametrize('body',['{}','[]','null','{"confirm_activation":false}','{"confirm_activation":1}',
    '{"confirm_activation":true,"admin_id":"other"}','{"confirm_activation":true,"confirm_activation":true}','{bad'])
def test_invalid_body_no_write(body):
    session=Mock();session.validate.return_value=admin();service=Mock()
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),content=body)
    assert r.status_code==400 and r.headers['cache-control']=='no-store';service.activate.assert_not_called()

@pytest.mark.parametrize('kind,status',[('origin',403),('csrf',403),('content',415),('large',413),('query',400),('id',400),('permission',403),('get',405)])
def test_protocol_rejection(monkeypatch,kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock();headers=h();path=PATH;body='{"confirm_activation":true}'
    if kind=='origin':headers['Origin']='https://evil.test'
    if kind=='csrf':del headers['X-Admin-Request']
    if kind=='content':headers['Content-Type']='text/plain'
    if kind=='large':body=' '*4097
    if kind=='query':path+='?customer_id=other'
    if kind=='id':path=path.replace('customer-a','__bad__')
    if kind=='permission':monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    with TestClient(app_for(session,service)) as http:r=http.get(path,headers=headers) if kind=='get' else http.post(path,headers=headers,content=body)
    assert r.status_code==status and r.headers['cache-control']=='no-store';service.activate.assert_not_called()

@pytest.mark.parametrize('kind,status',[('missing',404),('conflict',409),('uncertain',503)])
def test_http_failure_sanitized(kind,status):
    session=Mock();session.validate.return_value=admin();service=Mock()
    if kind=='missing':service.activate.return_value=None
    else:service.activate.side_effect=CustomerActivationConflict() if kind=='conflict' else RuntimeError('synthetic-private')
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=h(),json={'confirm_activation':True})
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
    with TestClient(app_for(session,service)) as http:r=http.post(PATH,headers=headers,json={'confirm_activation':True})
    assert r.status_code==401;service.activate.assert_not_called()

def test_unpublished():
    from app.main import app
    with TestClient(app) as http:assert http.post(PATH,json={'confirm_activation':True}).status_code==404

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
    monkeypatch.setattr('app.persistence.admin_activation_repository.firestore.transactional',exhausted)
    with pytest.raises(CustomerActivationUnavailable) as caught:repo.activate('customer-a',admin())
    assert len(calls)==1 and data==before and 'synthetic-private' not in str(caught.value)



def test_only_activation_requests_eight_native_attempts(monkeypatch):
    from app.persistence.admin_activation_repository import _ACTIVATION_MAX_ATTEMPTS
    repo,data,client=harness(monkeypatch)
    assert _ACTIVATION_MAX_ATTEMPTS==8
    assert repo.activate('customer-a',admin()).result=='activated'
    client.transaction.assert_called_once_with(max_attempts=8)
