"""Real SDK transactions, synthetic requests, only guarded local emulator."""
from concurrent.futures import ThreadPoolExecutor
import copy
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.persistence.kirvano_commerce_repository import commercial_transaction
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import prepared
from google.cloud import firestore
from uuid import uuid4

pytestmark = pytest.mark.firestore_emulator


@pytest.fixture
def http(emulator_client, monkeypatch):
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN', 'synthetic-webhook-token')
    monkeypatch.setenv('KIRVANO_WEBHOOK_TIMEZONE', 'America/Sao_Paulo')
    monkeypatch.setenv('EMAIL_IDENTITY_HMAC_SECRET', 'synthetic-hmac-secret')
    monkeypatch.setattr('app.api.kirvano.load_dotenv', lambda *a, **k: None)
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client', lambda: emulator_client)
    return TestClient(app, headers={'security-token':'synthetic-webhook-token'})


def count(client, name):
    return len(list(client.collection(name).stream(timeout=5)))


def test_first_atomic(http, emulator_client):
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    for name in ('users','email_identities','subscriptions','purchases','entitlements','kirvano_events'):
        assert count(emulator_client, name) == 1
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['business_status'] == 'applied'


def test_concurrent_same_email(http, emulator_client):
    first = payload(); second = copy.deepcopy(first); second['sale_id'] = 'another-synthetic-sale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda data: http.post('/webhooks/kirvano', json=data), (first, second)))
    diagnostics = {}
    for label, response in zip(('A', 'B'), responses):
        try:
            body = response.json()
        except ValueError:
            body = None
        # Render only fixed safe bodies, never arbitrary response content.
        safe_body = 'omitted'
        if body == {'received': True}:
            safe_body = {'received': True}
        elif body == {'detail': 'Service unavailable'}:
            safe_body = {'detail': 'Service unavailable'}
        diagnostics[label] = {'status_code': response.status_code, 'body': safe_body}
    statuses = tuple(response.status_code for response in responses)
    assert statuses == (200, 200), f'Sanitized request results: {diagnostics}'
    assert count(emulator_client, 'users') == count(emulator_client, 'email_identities') == 1
    assert count(emulator_client, 'purchases') == 2


def test_concurrent_identical(http, emulator_client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: http.post('/webhooks/kirvano', json=payload()), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert count(emulator_client, 'purchases') == count(emulator_client, 'entitlements') == 1
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['receipt_count'] == 2 and event['variant_count'] == 1


def test_concurrent_conflict(http, emulator_client):
    first = payload(); second = copy.deepcopy(first); second['total_price'] = '20'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda data: http.post('/webhooks/kirvano', json=data), (first, second)))
    assert all(response.status_code == 200 for response in responses)
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['processing_status'] == 'conflict' and event['business_status'] == 'review_required'
    assert event['variant_count'] == 2 and event['receipt_count'] == 2
    assert count(emulator_client, 'purchases') == count(emulator_client, 'entitlements') == 1
    assert 'application' in event


def test_abort_has_no_partial_writes(emulator_client):
    @firestore.transactional
    def abort(transaction):
        commercial_transaction(transaction, emulator_client, *prepared(payload()), uuid4().hex)
        raise RuntimeError('Synthetic abort before commit')
    with pytest.raises(RuntimeError): abort(emulator_client.transaction())
    for name in ('users','email_identities','subscriptions','purchases','entitlements','kirvano_events'):
        assert count(emulator_client, name) == 0


def test_retry_after_commit(http, emulator_client):
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    before = next(emulator_client.collection('kirvano_events').stream()).to_dict()['application']
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    after = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert before == after['application'] and after['receipt_count'] == 2
    for name in ('users','email_identities','subscriptions','purchases','entitlements'):
        assert count(emulator_client, name) == 1


from test_kirvano_commerce_transaction import renewal_payload
from app.services.kirvano_event_service import normalize_event


def inbox_document(client, data):
    return client.collection('kirvano_events').document(normalize_event(data).logical_id)


def entitlement_history(client):
    return {snapshot.id:snapshot.to_dict() for snapshot in client.collection('entitlements').stream(timeout=5)}


def assert_renewal_shared(client, charges, previous):
    for name in ('users','email_identities','subscriptions'):
        assert count(client,name)==1
    for name in ('purchases','entitlements'):
        assert count(client,name)==charges
    current=entitlement_history(client)
    for identifier,value in previous.items():
        assert current[identifier]==value


@pytest.fixture
def renewal_seed(http, emulator_client):
    assert http.post('/webhooks/kirvano',json=payload()).status_code==200
    return entitlement_history(emulator_client)


def test_initial_sale_then_renewal(http, emulator_client, renewal_seed):
    data=renewal_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert inbox_document(emulator_client,data).get().to_dict()['business_status']=='applied'
    assert_renewal_shared(emulator_client,2,renewal_seed)


def test_renewal_retry(http, emulator_client, renewal_seed):
    data=renewal_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    application=inbox_document(emulator_client,data).get().to_dict()['application']
    history=entitlement_history(emulator_client)
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    event=inbox_document(emulator_client,data).get().to_dict()
    assert event['application']==application and event['receipt_count']==2
    assert_renewal_shared(emulator_client,2,history)


def test_renewal_charge_three_before_two(http, emulator_client, renewal_seed):
    for data in (renewal_payload(3,'2026-12-05 12:00:00','2027-01-05 12:00:00'),renewal_payload()):
        assert http.post('/webhooks/kirvano',json=data).status_code==200
        assert inbox_document(emulator_client,data).get().to_dict()['business_status']=='applied'
    assert_renewal_shared(emulator_client,3,renewal_seed)


@pytest.mark.parametrize('distinct',[False,True])
def test_concurrent_renewals(http, emulator_client, renewal_seed, distinct):
    first=renewal_payload()
    second=renewal_payload(3,'2026-12-05 12:00:00','2027-01-05 12:00:00') if distinct else copy.deepcopy(first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda data:http.post('/webhooks/kirvano',json=data),(first,second)))
    assert tuple(r.status_code for r in responses)==(200,200)
    assert_renewal_shared(emulator_client,3 if distinct else 2,renewal_seed)
    if not distinct:
        event=inbox_document(emulator_client,first).get().to_dict()
        assert event['receipt_count']==2 and event['variant_count']==1


def test_renewal_before_initial_sale(http, emulator_client):
    data=renewal_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    event=inbox_document(emulator_client,data).get().to_dict()
    assert event['business_reason_codes']==['renewal_identity_missing']
    for name in ('users','email_identities','subscriptions','purchases','entitlements'):assert count(emulator_client,name)==0


def test_renewal_new_post_after_initial_sale(http, emulator_client):
    data=renewal_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert http.post('/webhooks/kirvano',json=payload()).status_code==200
    previous=entitlement_history(emulator_client)
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    event=inbox_document(emulator_client,data).get().to_dict()
    assert event['business_status']=='applied' and event['receipt_count']==2 and event['variant_count']==1
    assert_renewal_shared(emulator_client,2,previous)


def test_renewal_different_email(http, emulator_client, renewal_seed):
    data=renewal_payload();data['customer']['email']='other@example.com'
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert inbox_document(emulator_client,data).get().to_dict()['business_status']=='review_required'
    assert_renewal_shared(emulator_client,1,renewal_seed)


@pytest.mark.parametrize('status',['canceled','expired','pending','refunded','chargeback'])
def test_renewal_nonactive_subscription(http, emulator_client, renewal_seed, status):
    subscription=next(emulator_client.collection('subscriptions').stream())
    subscription.reference.update({'status':status})
    data=renewal_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert inbox_document(emulator_client,data).get().to_dict()['business_reason_codes']==['subscription_not_active']
    assert subscription.reference.get().to_dict()['status']==status
    assert_renewal_shared(emulator_client,1,renewal_seed)


@pytest.mark.parametrize('reverse',[False,True])
def test_same_charge_different_types(http, emulator_client, renewal_seed, reverse):
    renewal=renewal_payload();sale=copy.deepcopy(renewal);sale['event']='SALE_APPROVED'
    first,second=(renewal,sale) if reverse else (sale,renewal)
    assert http.post('/webhooks/kirvano',json=first).status_code==200
    application=inbox_document(emulator_client,first).get().to_dict()['application']
    purchase_ref=emulator_client.collection('purchases').document(application['purchase_id']);purchase=purchase_ref.get().to_dict()
    assert http.post('/webhooks/kirvano',json=second).status_code==200
    assert inbox_document(emulator_client,second).get().to_dict()['business_reason_codes']==['commercial_binding_mismatch']
    assert inbox_document(emulator_client,first).get().to_dict()['application']==application
    assert purchase_ref.get().to_dict()==purchase
    assert_renewal_shared(emulator_client,2,renewal_seed)


@pytest.mark.parametrize('start',['2026-11-10 12:00:00','2026-10-25 12:00:00'])
def test_renewal_gap_overlap(http, emulator_client, renewal_seed, start):
    data=renewal_payload(start=start)
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    candidate=prepared(data)[1].candidate;event=inbox_document(emulator_client,data).get().to_dict()
    entitlement=emulator_client.collection('entitlements').document(event['application']['entitlement_id']).get().to_dict()
    assert (entitlement['valid_from'],entitlement['valid_until'])==(candidate.valid_from,candidate.valid_until)
    assert_renewal_shared(emulator_client,2,renewal_seed)


def test_renewal_abort_no_partial_writes(emulator_client, renewal_seed):
    data=renewal_payload()
    @firestore.transactional
    def abort(transaction):
        commercial_transaction(transaction,emulator_client,*prepared(data),uuid4().hex)
        raise RuntimeError('Synthetic renewal abort')
    with pytest.raises(RuntimeError):abort(emulator_client.transaction())
    assert not inbox_document(emulator_client,data).get().exists
    assert_renewal_shared(emulator_client,1,renewal_seed)


def test_concurrent_conflicting_renewals(http, emulator_client, renewal_seed):
    first=renewal_payload();second=copy.deepcopy(first);second['total_price']='20'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda data:http.post('/webhooks/kirvano',json=data),(first,second)))
    assert tuple(r.status_code for r in responses)==(200,200)
    event=inbox_document(emulator_client,first).get().to_dict()
    assert event['processing_status']=='conflict' and event['business_status']=='review_required'
    assert event['variant_count']==2 and 'application' in event
    assert_renewal_shared(emulator_client,2,renewal_seed)

from test_kirvano_commercial import cancellation_payload


def all_commercial(client):
    return {name:{s.id:s.to_dict() for s in client.collection(name).stream(timeout=5)}
            for name in ('users','email_identities','subscriptions','purchases','entitlements')}


def assert_cancel_preserves(client,before):
    after=all_commercial(client)
    for name in ('users','email_identities','purchases','entitlements'):
        assert after[name]==before[name]
    assert len(after['subscriptions'])==len(before['subscriptions'])
    for identifier,sub in after['subscriptions'].items():
        assert sub['status']=='canceled'
        assert {k:v for k,v in sub.items() if k not in ('status','cancellation')}=={
            k:v for k,v in before['subscriptions'][identifier].items() if k not in ('status','cancellation')}


def test_cancellation_normal_retry_and_legacy(http,emulator_client,renewal_seed):
    before=all_commercial(emulator_client);data=cancellation_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert_cancel_preserves(emulator_client,before)
    applied=inbox_document(emulator_client,data).get().to_dict()['application']
    state=all_commercial(emulator_client)
    assert applied['result']=='state_changed'
    for request in (data,payload()):
        assert http.post('/webhooks/kirvano',json=request).status_code==200
    assert all_commercial(emulator_client)==state
    assert inbox_document(emulator_client,data).get().to_dict()['application']==applied


@pytest.mark.parametrize('distinct',[False,True])
def test_concurrent_cancellations(http,emulator_client,renewal_seed,distinct):
    before=all_commercial(emulator_client)
    first=cancellation_payload();second=cancellation_payload(2) if distinct else copy.deepcopy(first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda data:http.post('/webhooks/kirvano',json=data),(first,second)))
    assert tuple(r.status_code for r in responses)==(200,200)
    assert_cancel_preserves(emulator_client,before)
    events=[inbox_document(emulator_client,d).get().to_dict() for d in (first,second)]
    assert all(e['business_status']=='applied' for e in events)
    if distinct:
        assert {e['application']['result'] for e in events}=={'state_changed','already_canceled'}
    else:
        assert events[0]['receipt_count']==2 and events[0]['variant_count']==1


def test_cancellation_concurrent_renewal(http,emulator_client,renewal_seed):
    first=cancellation_payload();second=renewal_payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda data:http.post('/webhooks/kirvano',json=data),(first,second)))
    assert tuple(r.status_code for r in responses)==(200,200)
    cancel=inbox_document(emulator_client,first).get().to_dict()
    renewal=inbox_document(emulator_client,second).get().to_dict()
    assert cancel['business_status']=='applied'
    assert next(iter(all_commercial(emulator_client)['subscriptions'].values()))['status']=='canceled'
    if renewal['business_status']=='applied':
        assert count(emulator_client,'purchases')==2
        assert count(emulator_client,'entitlements')==2
    else:
        assert renewal['business_reason_codes']==['subscription_not_active']
        assert count(emulator_client,'purchases')==1
        assert count(emulator_client,'entitlements')==1
    for identifier,value in renewal_seed.items():
        assert entitlement_history(emulator_client)[identifier]==value
    state=all_commercial(emulator_client)
    assert http.post('/webhooks/kirvano',json=second).status_code==200
    assert all_commercial(emulator_client)==state


def test_cancellation_before_sale_new_post(http,emulator_client):
    data=cancellation_payload()
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert inbox_document(emulator_client,data).get().to_dict()['business_reason_codes']==['cancellation_identity_missing']
    assert all(not values for values in all_commercial(emulator_client).values())
    assert http.post('/webhooks/kirvano',json=payload()).status_code==200
    before=all_commercial(emulator_client)
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    assert inbox_document(emulator_client,data).get().to_dict()['business_status']=='applied'
    assert_cancel_preserves(emulator_client,before)


@pytest.mark.parametrize('mode',['email','canceled','pending','expired','refunded','chargeback'])
def test_cancellation_review(http,emulator_client,renewal_seed,mode):
    data=cancellation_payload()
    if mode=='email':data['customer']['email']='other@example.com'
    else:
        sub=next(emulator_client.collection('subscriptions').stream())
        sub.reference.update({'status':mode})
    before=all_commercial(emulator_client)
    assert http.post('/webhooks/kirvano',json=data).status_code==200
    event=inbox_document(emulator_client,data).get().to_dict()
    assert event['business_status']=='review_required'
    expected='cancellation_identity_missing' if mode=='email' else (
        'cancellation_provenance_missing' if mode=='canceled' else 'subscription_not_active')
    assert event['business_reason_codes']==[expected]
    assert all_commercial(emulator_client)==before


def test_cancellation_abort(http,emulator_client,renewal_seed):
    data=cancellation_payload();before=all_commercial(emulator_client)
    @firestore.transactional
    def abort(transaction):
        commercial_transaction(transaction,emulator_client,*prepared(data),uuid4().hex)
        raise RuntimeError('Synthetic cancellation abort')
    with pytest.raises(RuntimeError):abort(emulator_client.transaction())
    assert not inbox_document(emulator_client,data).get().exists
    assert all_commercial(emulator_client)==before


def test_cancellation_conflicting_variants(http,emulator_client,renewal_seed):
    first=cancellation_payload();second=copy.deepcopy(first);second['total_price']='20'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda data:http.post('/webhooks/kirvano',json=data),(first,second)))
    assert tuple(r.status_code for r in responses)==(200,200)
    event=inbox_document(emulator_client,first).get().to_dict()
    assert event['processing_status']=='conflict' and event['business_status']=='review_required'
    assert event['variant_count']==2 and event['application']['result']=='state_changed'
    assert next(iter(all_commercial(emulator_client)['subscriptions'].values()))['status']=='canceled'
    assert entitlement_history(emulator_client)==renewal_seed
