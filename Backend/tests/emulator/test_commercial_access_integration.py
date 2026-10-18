"""Real cancellation-aware resolution; no new grants, rewrites or production I/O."""
import copy
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import pytest
from google.cloud import firestore
from app.domain.models import UserAccessState
from app.services.access_service import can_access_portal
from app.persistence.admin_access_eligibility import has_eligible_portal_access,_resolve_candidate
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from app.domain.admin_activation import CustomerActivationConflict
from test_commerce import http
from test_admin_auth_integration import seed
from test_admin_domain import admin
from test_kirvano_commercial import payload,cancellation_payload
from test_kirvano_commerce_transaction import renewal_payload
from test_admin_customers_integration import state
pytestmark=pytest.mark.firestore_emulator


def sale_payload():
    data=payload();local=datetime.now(ZoneInfo('America/Sao_Paulo'))
    data['payment']['finished_at']=(local-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    data['plan']['next_charge_date']=(local+timedelta(days=29)).strftime('%Y-%m-%d %H:%M:%S')
    return data


def current_access(client,uid,now):
    def read(tx):
        user=client.document('users/'+uid).get(transaction=tx,timeout=5).to_dict()
        # Administrative preconditions come from persisted user, not proposed ACTIVE.
        if user['activation_status']!='active' or user['account_status']!='enabled':return False
        return has_eligible_portal_access(tx,client,uid,user['account_status'],now)
    return firestore.transactional(read)(client.transaction())


def test_purchase_activation_cancellation_is_immediate_and_idempotent(http,emulator_client):
    seed(emulator_client);sale=sale_payload()
    assert http.post('/webhooks/kirvano',json=sale).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    assert user.to_dict()['activation_status']=='pending'
    assert not current_access(emulator_client,user.id,now)
    assert AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin()).result=='activated'
    assert current_access(emulator_client,user.id,now)
    before=state(emulator_client);negative=copy.deepcopy(sale);negative.update(event='SUBSCRIPTION_CANCELED',status='CANCELED')
    for _ in range(2):assert http.post('/webhooks/kirvano',json=negative).status_code==200
    after=state(emulator_client)
    for collection,value in before.items():
        if collection not in ('subscriptions','kirvano_events'):assert after[collection]==value
    assert after['users'][user.id][0]['activation_status']=='active'
    assert not current_access(emulator_client,user.id,now)
    right=next(emulator_client.collection('entitlements').stream(timeout=5)).to_dict()
    assert right['status']=='granted' and right['valid_until']>now
    # Old proven delivery and new delayed charge cannot reopen the canceled subscription.
    assert http.post('/webhooks/kirvano',json=sale).status_code==200
    renewal=copy.deepcopy(sale);renewal['event']='SUBSCRIPTION_RENEWED';renewal['plan']['charge_number']=2
    assert http.post('/webhooks/kirvano',json=renewal).status_code==200
    assert not current_access(emulator_client,user.id,now)
    assert len(list(emulator_client.collection('purchases').stream(timeout=5)))==1


def test_activation_after_cancellation_is_conflict_without_admin_or_commercial_writes(http,emulator_client):
    seed(emulator_client);sale=sale_payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    canceled=copy.deepcopy(sale);canceled.update(event='SUBSCRIPTION_CANCELED',status='CANCELED')
    assert http.post('/webhooks/kirvano',json=canceled).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));before=state(emulator_client)
    with pytest.raises(CustomerActivationConflict):AdminActivationRepository(emulator_client).activate(user.id,admin())
    assert state(emulator_client)==before


def test_unrelated_cancel_does_not_veto_new_sale_same_product_and_customer(http,emulator_client):
    seed(emulator_client);sale=sale_payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    assert AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin()).result=='activated'
    canceled=copy.deepcopy(sale);canceled.update(event='SUBSCRIPTION_CANCELED',status='CANCELED')
    assert http.post('/webhooks/kirvano',json=canceled).status_code==200
    assert not current_access(emulator_client,user.id,now)
    another=copy.deepcopy(sale);another['sale_id']='another-valid-sale'
    another['payment']['finished_at']=(datetime.strptime(sale['payment']['finished_at'],'%Y-%m-%d %H:%M:%S')+timedelta(seconds=10)).strftime('%Y-%m-%d %H:%M:%S')
    assert http.post('/webhooks/kirvano',json=another).status_code==200
    assert len(list(emulator_client.collection('users').stream(timeout=5)))==1
    assert len(list(emulator_client.collection('subscriptions').stream(timeout=5)))==2
    assert current_access(emulator_client,user.id,now)
    canceled_sub=next(row for row in emulator_client.collection('subscriptions').stream(timeout=5) if row.to_dict()['status']=='canceled')
    assert canceled_sub.to_dict()['sale_id']==sale['sale_id']
    # Earlier period puts the canceled candidate first; check the actual query.
    from google.cloud.firestore_v1.base_query import FieldFilter
    query=emulator_client.collection('purchases')
    for field,op,value in [('user_id','==',user.id),('status','==','active'),('valid_from','<=',now),('valid_until','>',now)]:
        query=query.where(filter=FieldFilter(field,op,value))
    first=next(query.limit(1).stream(timeout=5))
    assert first.to_dict()['subscription_id']==canceled_sub.id
    purchases=list(emulator_client.collection('purchases').stream(timeout=5))
    cancelled_purchase=next(row for row in purchases if row.to_dict()['subscription_id']==canceled_sub.id)
    assert _resolve_candidate(None,emulator_client,user.id,cancelled_purchase).subscription_status=='canceled'


def test_renewal_validity_and_administrative_suspension_are_independent(http,emulator_client):
    seed(emulator_client);sale=sale_payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    assert AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin()).result=='activated'
    right=next(emulator_client.collection('entitlements').stream(timeout=5)).to_dict();end=right['valid_until']
    assert not current_access(emulator_client,user.id,end)
    renewal=copy.deepcopy(sale);renewal['event']='SUBSCRIPTION_RENEWED';renewal['plan']['charge_number']=2
    local_end=end.astimezone(ZoneInfo('America/Sao_Paulo'))
    renewal['payment']['finished_at']=local_end.strftime('%Y-%m-%d %H:%M:%S')
    renewal['plan']['next_charge_date']=(local_end+timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    assert http.post('/webhooks/kirvano',json=renewal).status_code==200
    assert current_access(emulator_client,user.id,end)
    assert AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend(user.id,admin()).result=='suspended'
    assert http.post('/webhooks/kirvano',json=renewal).status_code==200
    assert not current_access(emulator_client,user.id,end)


@pytest.mark.parametrize('change',['missing_subscription','wrong_user','unknown_status','missing_purchase'])
def test_missing_and_inconsistent_linked_data_never_authorize(http,emulator_client,change):
    seed(emulator_client);sale=sale_payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin())
    sub=next(emulator_client.collection('subscriptions').stream(timeout=5))
    if change=='missing_subscription':sub.reference.delete(timeout=5)
    if change=='wrong_user':sub.reference.update({'user_id':'other'},timeout=5)
    if change=='unknown_status':sub.reference.update({'status':'unknown'},timeout=5)
    if change=='missing_purchase':next(emulator_client.collection('purchases').stream(timeout=5)).reference.delete(timeout=5)
    if change=='unknown_status':
        with pytest.raises(ValueError):current_access(emulator_client,user.id,now)
    else:assert not current_access(emulator_client,user.id,now)


@pytest.mark.parametrize('operation',['activate','resume'])
def test_cancellation_between_read_and_admin_commit_is_revalidated(http,emulator_client,monkeypatch,operation):
    from google.cloud.firestore_v1.transaction import Transaction
    from google.api_core.exceptions import Aborted
    from app.persistence.admin_resumption_repository import AdminResumptionRepository
    from app.domain.admin_resumption import CustomerResumptionConflict
    seed(emulator_client);sale=sale_payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    user=next(emulator_client.collection('users').stream(timeout=5));now=datetime.now(timezone.utc)+timedelta(seconds=1)
    if operation=='resume':
        AdminActivationRepository(emulator_client,clock=lambda:now).activate(user.id,admin())
        AdminSuspensionRepository(emulator_client,clock=lambda:now).suspend(user.id,admin())
    before=state(emulator_client);original=Transaction._commit;attempts=[]
    canceled=copy.deepcopy(sale);canceled.update(event='SUBSCRIPTION_CANCELED',status='CANCELED')
    def inject(self,*args,**kwargs):
        if any('/activation_audit/' in write.update.name for write in self._write_pbs):
            attempts.append(1);self._rollback()
            assert http.post('/webhooks/kirvano',json=canceled).status_code==200
            raise Aborted('synthetic-confirmed-conflict')
        return original(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_commit',inject)
        repository=AdminActivationRepository if operation=='activate' else AdminResumptionRepository
        exception=CustomerActivationConflict if operation=='activate' else CustomerResumptionConflict
        with pytest.raises(exception):getattr(repository(emulator_client,clock=lambda:now),operation)(user.id,admin())
    after=state(emulator_client)
    assert attempts==[1]
    for collection,value in before.items():
        if collection not in ('subscriptions','kirvano_events'):assert after[collection]==value
    assert not current_access(emulator_client,user.id,now)
