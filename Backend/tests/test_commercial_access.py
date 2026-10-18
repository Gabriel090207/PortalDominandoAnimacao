"""Cancellation-aware access evidence, canonical binding and bounded resolution."""
import copy
from datetime import timedelta
import pytest
from pydantic import ValidationError
from app.domain.models import Entitlement,PortalEntitlement,UserAccessState
from app.services.access_service import can_access_portal
from app.persistence.admin_access_eligibility import has_eligible_portal_access,_resolve_candidate
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.persistence.admin_resumption_repository import AdminResumptionRepository
from app.domain.admin_activation import CustomerActivationConflict
from app.domain.admin_resumption import CustomerResumptionConflict
from test_admin_activation import harness
from test_admin_resumption import harness as resume_harness
from test_admin_domain import admin


def facts():
    from test_admin_domain import START
    return dict(user_id='customer-a',resource_key='portal',status='granted',valid_from=START,
        valid_until=START+timedelta(days=30))


def test_bare_entitlement_cannot_bypass_subscription_confirmation():
    raw=Entitlement(**facts());user=UserAccessState(account_status='enabled',activation_status='active')
    assert not can_access_portal('customer-a',user,[raw],now=raw.valid_from)
    right=PortalEntitlement(**facts(),purchase_id='p',subscription_id='s',subscription_status='active')
    assert can_access_portal('customer-a',user,[right],now=right.valid_from)
    for status in ('canceled','expired','pending'):
        assert not can_access_portal('customer-a',user,[right.model_copy(update={'subscription_status':status})],now=right.valid_from)
    assert not can_access_portal('customer-a',user,[right],now=right.valid_until)
    for change in ({'account_status':'blocked'},{'activation_status':'suspended'},{'activation_status':'pending'}):
        assert not can_access_portal('customer-a',user.model_copy(update=change),[right],now=right.valid_from)
    with pytest.raises(ValidationError):PortalEntitlement(**(facts()|{'valid_until':None}),purchase_id='p',subscription_id='s',subscription_status='active')


@pytest.mark.parametrize('kind',['canceled','expired','pending','missing_subscription','foreign_user','foreign_product','foreign_scope','foreign_offer','wrong_canonical_id','missing_right'])
def test_ineligible_linked_records_deny_without_writes(monkeypatch,kind):
    repo,data,client=harness(monkeypatch);subkey=next(k for k in data if k.startswith('subscriptions/'))
    if kind in ('canceled','expired','pending'):data[subkey]['status']=kind
    if kind=='missing_subscription':del data[subkey]
    if kind=='foreign_user':data[subkey]['user_id']='other'
    if kind=='foreign_product':data[subkey]['product_id']='other'
    if kind=='foreign_scope':data[subkey]['source_scope']='other'
    if kind=='foreign_offer':data[subkey]['offer_id']='other'
    if kind=='wrong_canonical_id':data[subkey]['sale_id']='other'
    if kind=='missing_right':del data[next(k for k in data if k.startswith('entitlements/'))]
    before=copy.deepcopy(data)
    assert not has_eligible_portal_access(client.transaction(),client,'customer-a','enabled',repo.clock())
    with pytest.raises(CustomerActivationConflict):repo.activate('customer-a',admin())
    assert data==before


@pytest.mark.parametrize('kind',['unknown_status','active_cancellation','corrupt_period','invalid_subscription_path','firestore'])
def test_corruption_and_io_errors_are_not_positive_business_decisions(monkeypatch,kind):
    repo,data,client=harness(monkeypatch);subkey=next(k for k in data if k.startswith('subscriptions/'))
    if kind=='unknown_status':data[subkey]['status']='unknown'
    if kind=='active_cancellation':data[subkey]['cancellation']={'processed_at':repo.clock(),'origin_event_id':'a'*64,'origin_fingerprint':'b'*64}
    if kind=='corrupt_period':data[next(k for k in data if k.startswith('entitlements/'))]['valid_until']=repo.clock().replace(tzinfo=None)
    if kind=='invalid_subscription_path':data['purchases/purchase-a']['subscription_id']='a/b/c'
    if kind=='firestore':client.collection.side_effect=RuntimeError('synthetic-private')
    expected=ValueError if kind in ('unknown_status','active_cancellation','invalid_subscription_path') else RuntimeError
    with pytest.raises(expected):has_eligible_portal_access(client.transaction(),client,'customer-a','enabled',repo.clock())


def test_canceled_history_does_not_veto_another_real_valid_subscription(monkeypatch):
    from test_kirvano_commerce_transaction import Client,receive,docs,payload
    repo,data,client=harness(monkeypatch)
    first=next(k for k in data if k.startswith('subscriptions/'));data[first]['status']='canceled'
    other=Client();sale=payload();sale['sale_id']='another-synthetic-sale';receive(other,sale)
    for collection in ('subscriptions','purchases','entitlements'):
        for path,value in docs(other,collection).items():data[path]=value|{'user_id':'customer-a'}
    before=copy.deepcopy(data)
    assert has_eligible_portal_access(client.transaction(),client,'customer-a','enabled',repo.clock())
    assert data==before
    assert repo.activate('customer-a',admin()).result=='activated'
    assert data[first]['status']=='canceled'


def test_resume_cannot_remove_suspension_when_linked_subscription_canceled(monkeypatch):
    repo,data,client=resume_harness(monkeypatch)
    data[next(k for k in data if k.startswith('subscriptions/'))]['status']='canceled'
    before=copy.deepcopy(data)
    with pytest.raises(CustomerResumptionConflict):repo.resume('customer-a',admin())
    assert data==before
