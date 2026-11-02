"""Actual commerce transaction, UUID-only cleanup. NEVER uses global emulator wipe."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import copy
import pytest
from google.cloud import firestore
from emulator_support import configured_emulator, create_test_client
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import prepared
from app.persistence.kirvano_commerce_repository import commercial_transaction
from app.persistence.admin_customers_repository import AdminCustomersRepository
from app.domain.welcome_email import WelcomeEmailIntent, welcome_intent_id

pytestmark=pytest.mark.firestore_emulator


@pytest.fixture(autouse=True)
def emulator_client(monkeypatch):
    host,project=configured_emulator()
    monkeypatch.setattr('os.environ',{'FIRESTORE_EMULATOR_HOST':host,'FIRESTORE_TEST_PROJECT_ID':project})
    def forbidden(*a,**kw):raise AssertionError('Production Firebase/global cleanup forbidden')
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr('emulator_support.clear_test_emulator',forbidden)
    client=create_test_client();owned=[]
    def prepare(data=None):
        data=copy.deepcopy(data if data is not None else payload())
        namespace=uuid4().hex
        data['sale_id']='step93-'+namespace
        data['customer']={'email':f'step93-{namespace}@example.com','name':'Cliente Sintético'}
        event,result,identity=prepared(data);candidate=result.candidate
        user_id='step93-'+namespace
        from app.services.kirvano_event_service import digest
        from app.domain.states import ResourceKey
        root=client.collection('kirvano_events').document(event.logical_id)
        owned.extend([root.collection('variants').document(event.fingerprint),root,
            client.collection('users').document(user_id),
            client.collection('email_identities').document(identity.identity_id),
            client.collection('purchases').document(candidate.purchase_id),
            client.collection('subscriptions').document(candidate.subscription_id),
            client.collection('entitlements').document(digest(['kirvano-entitlement',1,candidate.purchase_id,ResourceKey.PORTAL.value])),
            client.collection('transactional_emails').document(welcome_intent_id(candidate.purchase_id))])
        return event,result,identity,user_id
    yield client,prepare,owned
    for ref in owned:ref.delete(timeout=5)
    client.close()


def test_approved_purchase_search_list_and_duplicate(emulator_client):
    client,prepare,owned=emulator_client;args=prepare()
    def run():return firestore.transactional(commercial_transaction)(client.transaction(),client,*args)
    run()
    event,result,_,user_id=args
    customer=AdminCustomersRepository(client).find_by_email(result.candidate.email_normalized.upper())
    assert customer.customer_id==user_id and customer.activation_status=='pending'
    repository=AdminCustomersRepository(client);cursor=None;found=False
    for _ in range(100):
        page=repository.list_page(limit=50,cursor=cursor)
        found|=any(item.customer_id==user_id for item in page.items)
        if found or page.next_cursor is None:break
        cursor=page.next_cursor
    assert found and repository.has_approved_purchase(user_id)
    mail=client.collection('transactional_emails').document(welcome_intent_id(result.candidate.purchase_id))
    snapshot=mail.get(timeout=5);record=WelcomeEmailIntent.model_validate(snapshot.to_dict())
    assert record.user_id==user_id and record.status=='pending' and record.customer_name=='Cliente Sintético'
    user=client.collection('users').document(user_id).get(timeout=5).to_dict()
    assert user['display_name']=='Cliente Sintético' and user['activation_status']=='pending'
    run()
    assert mail.get(timeout=5).update_time==snapshot.update_time


def test_real_commit_failure_is_atomic(emulator_client):
    client,prepare,owned=emulator_client;args=prepare();_,result,_,user_id=args
    # A deterministic failed commit: create precondition on a fixture-only sentinel.
    sentinel=client.collection('transactional_emails').document('step93-sentinel-'+uuid4().hex)
    owned.append(sentinel)
    sentinel.create({'synthetic_sentinel':True},timeout=5)
    def fail(tx):
        commercial_transaction(tx,client,*args)
        tx.create(sentinel,{'synthetic_sentinel':True})
    from google.api_core.exceptions import AlreadyExists
    with pytest.raises(AlreadyExists):firestore.transactional(fail)(client.transaction())
    assert sentinel.get(timeout=5).to_dict()=={'synthetic_sentinel':True}
    for name,identifier in [('purchases',result.candidate.purchase_id),
        ('transactional_emails',welcome_intent_id(result.candidate.purchase_id)),
        ('users',user_id),('email_identities',args[2].identity_id),
        ('subscriptions',result.candidate.subscription_id),('kirvano_events',args[0].logical_id)]:
        assert not client.collection(name).document(identifier).get(timeout=5).exists


def test_concurrent_duplicate_produces_single_intent(emulator_client,monkeypatch):
    client,prepare,owned=emulator_client;args=prepare()
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client',lambda:client)
    from app.persistence.kirvano_commerce_repository import record_commercial_event
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:record_commercial_event(*args),range(2)))
    assert len(results)==2
    event,result,_,user_id=args
    mail=client.collection('transactional_emails').document(welcome_intent_id(result.candidate.purchase_id)).get(timeout=5)
    assert WelcomeEmailIntent.model_validate(mail.to_dict()).user_id==user_id
    assert client.collection('kirvano_events').document(event.logical_id).get(timeout=5).to_dict()['receipt_count']==2
