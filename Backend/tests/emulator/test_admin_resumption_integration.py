"""Real activation -> suspension -> resumption on guarded anonymous demo client."""
from app.domain.models import PortalEntitlement
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.transaction import Transaction
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from app.persistence.admin_resumption_repository import AdminResumptionRepository
from app.domain.admin_resumption import CustomerResumptionConflict,CustomerResumptionUnavailable
from app.domain.models import Entitlement,UserAccessState
from app.services.access_service import can_access_portal
from test_admin_activation_integration import prepare,composition,ORIGIN
from test_admin_customers_integration import state
from test_admin_domain import admin
pytestmark=pytest.mark.firestore_emulator


def suspended(client,role='owner'):
    now=prepare(client,role)
    assert AdminActivationRepository(client,clock=lambda:now).activate('customer-a',admin(role=role)).result=='activated'
    assert AdminSuspensionRepository(client,clock=lambda:now+timedelta(seconds=1)).suspend('customer-a',admin(role=role)).result=='suspended'
    return now+timedelta(seconds=2)


def operation_audits(client,operation):
    return [row.to_dict() for row in client.collection('activation_audit').stream(timeout=5) if row.to_dict()['operation']==operation]


@pytest.mark.parametrize('role',['owner','operator'])
def test_http_atomic_resumption_and_idempotence_preserve_all_facts(emulator_client,role):
    now=suspended(emulator_client,role);composed=composition(emulator_client,now)
    app=FastAPI();app.include_router(composed.router)
    token=composed.session_service.create(admin(role=role)).token.get_secret_value()
    before=state(emulator_client)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Admin-Request':'1'}
    with TestClient(app) as http:
        path='/admin/customers/customer-a/resume'
        response=http.post(path,headers=headers,json={'confirm_resumption':True})
        assert response.status_code==200 and response.json()=={'customer_id':'customer-a','activation_status':'active','result':'resumed'}
        assert response.headers['cache-control']=='no-store'
        after=state(emulator_client)
        repeat=http.post(path,headers=headers,json={'confirm_resumption':True})
        assert repeat.status_code==200 and repeat.json()['result']=='already_active'
        assert state(emulator_client)==after
        assert http.get('/admin/customers/customer-a',headers=headers).json()['activation_status']=='active'
    for collection,value in before.items():
        if collection not in ('users','activation_audit'):assert after[collection]==value
    assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'active'}
    assert len(after['activation_audit'])==3
    for key,value in before['activation_audit'].items():assert after['activation_audit'][key]==value
    assert operation_audits(emulator_client,'resume_customer')==[dict(schema_version=1,admin_id='synthetic-admin',customer_id='customer-a',
        operation='resume_customer',previous_activation_status='suspended',activation_status='active',occurred_at=now,human_confirmation=True)]
    data=next(emulator_client.collection('entitlements').stream(timeout=5)).to_dict()
    right=PortalEntitlement(purchase_id="synthetic-purchase",subscription_id="synthetic-subscription",subscription_status="active",**{k:data[k] for k in ('user_id','resource_key','status','valid_from','valid_until')})
    assert can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[right],now=now)
    assert not can_access_portal('customer-a',UserAccessState(account_status='enabled',activation_status='active'),[right],now=right.valid_until)


@pytest.mark.parametrize('kind',['pending','blocked','no_history','suspension_only','no_initial','no_restriction','purchase','entitlement'])
def test_incompatible_and_legacy_records_unchanged(emulator_client,kind):
    if kind in ('pending','no_history','suspension_only'):
        now=prepare(emulator_client)
        if kind!='pending':emulator_client.document('users/customer-a').update({'activation_status':'active'},timeout=5)
        if kind=='suspension_only':AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend('customer-a',admin())
        if kind=='no_history':emulator_client.document('users/customer-a').update({'activation_status':'suspended'},timeout=5)
    else:
        now=suspended(emulator_client)
        if kind=='blocked':emulator_client.document('users/customer-a').update({'account_status':'blocked'},timeout=5)
        if kind in ('no_initial','no_restriction'):
            for row in emulator_client.collection('activation_audit').stream(timeout=5):
                if row.to_dict()['operation']==('activate_customer' if kind=='no_initial' else 'suspend_customer'):row.reference.delete(timeout=5)
        if kind=='purchase':emulator_client.document('purchases/purchase-a').update({'status':'expired'},timeout=5)
        if kind=='entitlement':next(emulator_client.collection('entitlements').stream(timeout=5)).reference.update({'status':'revoked'},timeout=5)
    before=state(emulator_client)
    with pytest.raises(CustomerResumptionConflict):AdminResumptionRepository(emulator_client,clock=lambda:now).resume('customer-a',admin())
    assert state(emulator_client)==before


@pytest.mark.parametrize('other',['resume','suspend'])
def test_concurrent_operations_serialize_without_assuming_winner(emulator_client,other):
    now=suspended(emulator_client);before=state(emulator_client);barrier=Barrier(2)
    def run(operation):
        barrier.wait(timeout=10)
        if operation=='resume':return AdminResumptionRepository(emulator_client,clock=lambda:now).resume('customer-a',admin()).result
        return AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend('customer-a',admin()).result
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['resume',other]))
    after=state(emulator_client)
    assert results.count('resumed')==1
    assert len(operation_audits(emulator_client,'resume_customer'))==1
    if other=='resume':assert results.count('already_active')==1;expected='active';count=3
    elif 'suspended' in results:expected='suspended';count=4
    else:assert 'already_suspended' in results;expected='active';count=3
    assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':expected}
    assert len(after['activation_audit'])==count
    for key,value in before['activation_audit'].items():assert after['activation_audit'][key]==value
    for collection,value in before.items():
        if collection not in ('users','activation_audit'):assert after[collection]==value


@pytest.mark.parametrize('kind',['audit','commit','uncertain','recover','exhausted'])
def test_atomic_failures_and_explicit_native_budget(emulator_client,monkeypatch,kind):
    now=suspended(emulator_client);before=state(emulator_client);attempts=[]
    original_commit=Transaction._commit;original_create=Transaction.create
    def create(self,ref,data):
        if kind=='audit' and data.get('operation')=='resume_customer':raise RuntimeError('synthetic-private')
        return original_create(self,ref,data)
    def commit(self,*args,**kwargs):
        attempts.append(1)
        if kind=='uncertain':
            original_commit(self,*args,**kwargs)
            raise RuntimeError('synthetic-private')
        if kind=='commit':raise RuntimeError('synthetic-private')
        if kind in ('recover','exhausted') and (kind=='exhausted' or len(attempts)<8):
            # Confirmed server rollback precedes synthetic Aborted: not an uncertain network result.
            self._rollback();raise Aborted('synthetic-confirmed-abort')
        return original_commit(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'create',create);patch.setattr(Transaction,'_commit',commit)
        repo=AdminResumptionRepository(emulator_client,clock=lambda:now)
        if kind=='recover':assert repo.resume('customer-a',admin()).result=='resumed'
        else:
            with pytest.raises(CustomerResumptionUnavailable) as caught:repo.resume('customer-a',admin())
            assert 'synthetic-private' not in str(caught.value)
    after=state(emulator_client)
    assert len(attempts)==(0 if kind=='audit' else 8 if kind in ('recover','exhausted') else 1)
    if kind in ('recover','uncertain'):
        assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'active'}
        assert len(operation_audits(emulator_client,'resume_customer'))==1
        assert AdminResumptionRepository(emulator_client,clock=lambda:now).resume('customer-a',admin()).result=='already_active'
    else:assert after==before


@pytest.mark.parametrize('change',['account','purchase','entitlement','history'])
def test_native_retry_revalidates_restrictions_and_eligibility(emulator_client,monkeypatch,change):
    now=suspended(emulator_client);before=state(emulator_client);original=Transaction._commit;attempts=[]
    def inject(self,*args,**kwargs):
        attempts.append(1);self._rollback()
        if change=='account':emulator_client.document('users/customer-a').update({'account_status':'blocked'},timeout=5)
        elif change=='purchase':emulator_client.document('purchases/purchase-a').update({'status':'expired'},timeout=5)
        elif change=='entitlement':next(emulator_client.collection('entitlements').stream(timeout=5)).reference.update({'status':'revoked'},timeout=5)
        else:
            for row in emulator_client.collection('activation_audit').stream(timeout=5):
                if row.to_dict()['operation']=='activate_customer':row.reference.delete(timeout=5)
        raise Aborted('synthetic-confirmed-abort')
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_commit',inject)
        with pytest.raises(CustomerResumptionConflict):AdminResumptionRepository(emulator_client,clock=lambda:now).resume('customer-a',admin())
    assert len(attempts)==1 and not operation_audits(emulator_client,'resume_customer')
    after=state(emulator_client)
    assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|({'account_status':'blocked'} if change=='account' else {})
    for collection,value in before.items():
        if collection not in ('users',{'purchase':'purchases','entitlement':'entitlements','history':'activation_audit'}.get(change,'')):
            assert after[collection]==value


def test_kirvano_cancellation_preserves_history_but_denies_resumption(emulator_client):
    import copy
    from datetime import datetime,timezone
    from zoneinfo import ZoneInfo
    from uuid import uuid4
    from google.cloud import firestore
    from app.persistence.kirvano_commerce_repository import commercial_transaction
    from test_kirvano_commerce_transaction import prepared
    from test_kirvano_commercial import payload
    from test_admin_auth_integration import seed
    seed(emulator_client)
    base=datetime.now(ZoneInfo('America/Sao_Paulo'))
    sale=payload()
    sale['payment']['finished_at']=(base-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    sale['plan']['next_charge_date']=(base+timedelta(days=29)).strftime('%Y-%m-%d %H:%M:%S')
    def receive(data):
        return firestore.transactional(commercial_transaction)(emulator_client.transaction(),emulator_client,*prepared(data),uuid4().hex)
    receive(sale)
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    assert AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin()).result=='activated'
    assert AdminSuspensionRepository(emulator_client,clock=lambda:now+timedelta(seconds=1)).suspend(user.id,admin()).result=='suspended'
    canceled=copy.deepcopy(sale);canceled.update(event='SUBSCRIPTION_CANCELED',status='CANCELED')
    receive(canceled)
    assert user.reference.get(timeout=5).to_dict()['activation_status']=='suspended'
    assert next(emulator_client.collection('subscriptions').stream(timeout=5)).to_dict()['status']=='canceled'
    before=state(emulator_client)
    resumed_at=now+timedelta(seconds=2)
    with pytest.raises(CustomerResumptionConflict):
        AdminResumptionRepository(emulator_client,clock=lambda:resumed_at).resume(user.id,admin())
    assert state(emulator_client)==before
    from app.persistence.admin_access_eligibility import has_eligible_portal_access
    assert not has_eligible_portal_access(None,emulator_client,user.id,'enabled',resumed_at)
