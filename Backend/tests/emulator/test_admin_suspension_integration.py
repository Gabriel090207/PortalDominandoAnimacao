"""Real SDK transactions against the guarded synthetic emulator only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import Transaction
from google.api_core.exceptions import Aborted
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.domain.admin_suspension import CustomerSuspensionUnavailable,CustomerSuspensionConflict
from app.domain.admin_activation import CustomerActivationConflict
from app.domain.models import UserAccessState,Entitlement
from app.services.access_service import can_access_portal
from test_admin_domain import admin
from test_admin_activation_integration import prepare,composition,ORIGIN
from test_admin_customers_integration import state
from test_admin_auth_integration import seed
from test_kirvano_commerce_transaction import prepared,renewal_payload
from test_kirvano_commercial import payload,cancellation_payload
from app.persistence.kirvano_commerce_repository import commercial_transaction
pytestmark=pytest.mark.firestore_emulator


def active(client,role='owner'):
    now=prepare(client,role)
    client.document('users/customer-a').update({'activation_status':'active'},timeout=5)
    return now


@pytest.mark.parametrize('role',['owner','operator'])
def test_http_suspension_atomic_preserves_commerce_and_denies_access(emulator_client,role):
    now=active(emulator_client,role);composed=composition(emulator_client,now)
    app=FastAPI();app.include_router(composed.router)
    token=composed.session_service.create(admin(role=role)).token.get_secret_value()
    before=state(emulator_client)
    right=next(emulator_client.collection('entitlements').stream(timeout=5)).to_dict()
    entitlement=Entitlement(**{k:right[k] for k in ('user_id','resource_key','status','valid_from','valid_until')})
    assert can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[entitlement],now=now)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Admin-Request':'1'}
    with TestClient(app) as http:
        path='/admin/customers/customer-a/suspend'
        response=http.post(path,headers=headers,json={'confirm_suspension':True})
        assert response.status_code==200 and response.json()['result']=='suspended'
        assert response.headers['cache-control']=='no-store'
        after=state(emulator_client)
        assert http.post(path,headers=headers,json={'confirm_suspension':True}).json()['result']=='already_suspended'
        assert state(emulator_client)==after
        assert http.get('/admin/customers/customer-a',headers=headers).json()['activation_status']=='suspended'
    assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'suspended'}
    for collection,value in before.items():
        if collection!='users':assert after[collection]==value
    audit=next(iter(after['activation_audit'].values()))[0]
    assert len(after['activation_audit'])==1
    assert audit==dict(schema_version=1,admin_id='synthetic-admin',customer_id='customer-a',operation='suspend_customer',
        previous_activation_status='active',activation_status='suspended',occurred_at=now,human_confirmation=True)
    assert not can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='suspended'),[entitlement],now=now)


@pytest.mark.parametrize('other',['suspend','activate'])
def test_concurrent_restriction_never_reactivated(emulator_client,other):
    now=active(emulator_client);barrier=Barrier(2);before=state(emulator_client)
    def run(operation):
        barrier.wait(timeout=10)
        if operation=='suspend':return AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend('customer-a',admin()).result
        try:return AdminActivationRepository(emulator_client,clock=lambda:now).activate('customer-a',admin()).result
        except CustomerActivationConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['suspend',other]))
    after=state(emulator_client)
    assert results.count('suspended')==1
    assert set(results)<={'suspended','already_suspended','already_active','conflict'}
    assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'suspended'}
    assert len(after['activation_audit'])==1
    audit=next(iter(after['activation_audit'].values()))[0]
    assert audit['operation']=='suspend_customer' and audit['occurred_at']==now
    for collection,value in before.items():
        if collection!='users':assert after[collection]==value


@pytest.mark.parametrize('kind',['audit','commit','uncertain','recover','exhausted','blocked'])
def test_atomic_failures_and_native_retry(emulator_client,monkeypatch,kind):
    now=active(emulator_client);before=state(emulator_client);attempts=[]
    original_commit=Transaction._commit;original_create=Transaction.create
    def create(self,ref,data):
        if kind=='audit' and ref.parent.id=='activation_audit':raise RuntimeError('synthetic-private')
        return original_create(self,ref,data)
    def commit(self,*args,**kwargs):
        if not any('/activation_audit/' in write.update.name for write in self._write_pbs):return original_commit(self,*args,**kwargs)
        attempts.append(1)
        if kind=='uncertain':
            original_commit(self,*args,**kwargs)
            raise RuntimeError('synthetic-private')
        if kind=='commit':raise RuntimeError('synthetic-private')
        if kind in ('recover','exhausted','blocked') and (kind!='recover' or len(attempts)<5):
            self._rollback()
            if kind=='blocked':emulator_client.document('users/customer-a').update({'account_status':'blocked'},timeout=5)
            raise Aborted('synthetic-confirmed-abort')
        return original_commit(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'create',create);patch.setattr(Transaction,'_commit',commit)
        repo=AdminSuspensionRepository(emulator_client,clock=lambda:now)
        if kind=='recover':assert repo.suspend('customer-a',admin()).result=='suspended'
        else:
            with pytest.raises(CustomerSuspensionConflict if kind=='blocked' else CustomerSuspensionUnavailable):repo.suspend('customer-a',admin())
    after=state(emulator_client)
    assert len(attempts)==(0 if kind=='audit' else 5 if kind in ('recover','exhausted') else 1)
    if kind in ('recover','uncertain'):
        assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'suspended'}
        assert len(after['activation_audit'])==1
    elif kind=='blocked':
        assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'account_status':'blocked'}
        assert not after.get('activation_audit')
    else:assert after==before


@pytest.mark.parametrize('event',['SALE_APPROVED','SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED'])
def test_kirvano_events_preserve_manual_suspension(emulator_client,event):
    seed(emulator_client)
    def receive(data):
        return firestore.transactional(commercial_transaction)(emulator_client.transaction(),emulator_client,*prepared(data),uuid4().hex)
    receive(payload())
    user=next(emulator_client.collection('users').stream(timeout=5))
    user.reference.update({'activation_status':'active'},timeout=5)
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    assert AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend(user.id,admin()).result=='suspended'
    before=user.reference.get(timeout=5).to_dict()
    audit=list(emulator_client.collection('activation_audit').stream(timeout=5))[0].to_dict()
    if event=='SUBSCRIPTION_RENEWED':data=renewal_payload()
    elif event=='SUBSCRIPTION_CANCELED':data=cancellation_payload()
    else:
        data=payload();data['sale_id']='second-synthetic-sale'
    receive(data)
    assert user.reference.get(timeout=5).to_dict()==before
    assert list(emulator_client.collection('activation_audit').stream(timeout=5))[0].to_dict()==audit
    roots=list(emulator_client.collection('kirvano_events').stream(timeout=5))
    assert all(row.to_dict()['business_status']=='applied' for row in roots)
