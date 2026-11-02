"""Non-destructive demo tests: override the global wipe fixture intentionally.

Only UUID-namespaced documents created here are removed. Safe alongside manual
local homologation; never calls the shared clear_test_emulator utility.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from uuid import uuid4
import secrets
import pytest
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from app.services.admin_admission_service import derive_bucket_identifiers
from fastapi.testclient import TestClient
from app.tools import prepare_local_customer as tool
from app.tools import admin_local as local
from app.persistence.collections import CollectionName as C
from app.persistence.kirvano_commerce_repository import _is_retryable_contention
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_access_eligibility import _resolve_candidate
from app.persistence.admin_customers_repository import AdminCustomersRepository
from app.services.access_service import can_access_portal
from app.domain.models import UserAccessState
from app.services.admin_password_service import hash_admin_password
from emulator_support import create_test_client,configured_emulator
from test_admin_local import environment

pytestmark=pytest.mark.firestore_emulator


@pytest.fixture(autouse=True)
def emulator_client(monkeypatch):
    # Overrides conftest's destructive fixture, rather than depending on it.
    configured_emulator()
    env=environment();env['ADMIN_ADMISSION_HMAC_SECRET']=secrets.token_hex(32)
    monkeypatch.setattr('os.environ',env)
    def forbidden(*args,**kwargs):raise AssertionError('Production and global cleanup forbidden')
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr('emulator_support.clear_test_emulator',forbidden)
    namespace=uuid4().hex
    monkeypatch.setattr(tool,'EMAIL',f'step74-{namespace}@example.com')
    monkeypatch.setattr(tool,'USER_ID',f'step74-{namespace}')
    monkeypatch.setattr(tool,'SALE_ID',f'step74-{namespace}')
    client=create_test_client()
    refs=tool.references(client)
    owned=[]
    yield client,refs,owned
    root=refs[C.KIRVANO_EVENTS]
    # Exact one fixture variant, using its stored purchase period.
    if root.get(timeout=5).exists:
        fingerprint=root.get(timeout=5).to_dict().get('first_fingerprint')
        if fingerprint:root.collection('variants').document(fingerprint).delete(timeout=5)
    for ref in [*refs.values(),*owned]:ref.delete(timeout=5)
    client.close()


def test_valid_commercial_graph_pending_and_idempotent(emulator_client):
    client,refs,_=emulator_client
    assert tool.prepare_customer()=='created'
    before={key:(ref.get().to_dict(),ref.get().update_time) for key,ref in refs.items()}
    assert tool.prepare_customer()=='already_consistent'
    assert before=={key:(ref.get().to_dict(),ref.get().update_time) for key,ref in refs.items()}
    def check(tx):
        user=refs[C.USERS].get(transaction=tx).to_dict()
        projection=_resolve_candidate(tx,client,tool.USER_ID,refs[C.PURCHASES].get(transaction=tx))
        now=datetime.now(timezone.utc)
        assert projection.is_valid_at(now) and projection.subscription_status=='active'
        assert user['account_status']=='enabled' and user['activation_status']=='pending'
        assert not can_access_portal(tool.USER_ID,UserAccessState(account_status=user['account_status'],activation_status=user['activation_status']),[projection],now=now)
    firestore.transactional(check)(client.transaction())
    assert AdminCustomersRepository(client).has_approved_purchase(tool.USER_ID)


def test_concurrent_preparation_is_single_customer(emulator_client):
    def run(_):
        client=local.create_local_client()
        try:return firestore.transactional(tool._prepare)(client.transaction(),client,datetime.now(timezone.utc))
        except Exception as error:
            if not _is_retryable_contention(error):raise
            return 'recognized_contention'
        finally:client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
    assert results.count('created')==1
    assert set(results)<={'created','already_consistent','recognized_contention'}
    assert tool.prepare_customer()=='already_consistent'


@pytest.mark.parametrize('collection,field,value',[
    (C.USERS,'activation_status','active'),(C.SUBSCRIPTIONS,'status','canceled'),
    (C.ENTITLEMENTS,'purchase_id','unrelated'),(C.PURCHASES,'product_id','unrelated'),
])
def test_changed_fixture_is_not_overwritten(emulator_client,collection,field,value):
    client,refs,_=emulator_client
    tool.prepare_customer();refs[collection].update({field:value})
    before={key:ref.get().to_dict() for key,ref in refs.items()}
    with pytest.raises(tool.LocalCustomerError):tool.prepare_customer()
    assert before=={key:ref.get().to_dict() for key,ref in refs.items()}


def test_real_login_lookup_detail_confirmation_and_cursor(emulator_client):
    client,refs,owned=emulator_client
    tool.prepare_customer()
    now=datetime.now(timezone.utc);identifier=uuid4().hex
    password=secrets.token_urlsafe(24)
    record=AdminRecord(admin_id=identifier,email_normalized=f'{identifier}@example.com',
        role='operator',status='enabled',created_by='bootstrap',created_at=now,updated_at=now,
        password_changed_at=now,password_hash=hash_admin_password(password))
    admin=client.collection('admins').document(identifier);admin.create(record.to_document());owned.append(admin)
    for bucket in derive_bucket_identifiers('127.0.0.1',record.email_normalized,
        admission_hmac_secret=local.require_local_environment().secret.get_secret_value()):
        owned.append(client.collection('auth_throttles').document(bucket))
    app=local.create_local_app();h={'Origin':local.ORIGIN,'X-Admin-Request':'1'}
    try:
        with TestClient(app,base_url='https://localhost:8443',client=('127.0.0.1',1234)) as http:
            assert http.post('/admin/customers/lookup',headers=h,json={'email':tool.EMAIL}).status_code==401
            assert http.post('/admin/auth/login',headers=h,json={'email':record.email_normalized,'password':password}).status_code==200
            found=http.post('/admin/customers/lookup',headers=h,json={'email':' '+tool.EMAIL.upper()+' '})
            assert found.status_code==200 and found.json()['customer_id']==tool.USER_ID
            assert found.json()['account_status']=='enabled' and found.json()['activation_status']=='pending'
            assert http.post('/admin/customers/lookup',headers=h,json={'email':'missing-'+tool.EMAIL}).status_code==404
            assert http.post('/admin/customers/lookup',headers=h,json={'email':'bad'}).status_code==400
            detail=http.get('/admin/customers/'+tool.USER_ID,headers=h)
            assert detail.json()==found.json()
            confirmation=http.get('/admin/customers/'+tool.USER_ID+'/purchase-confirmation',headers=h)
            assert confirmation.json()=={'customer_id':tool.USER_ID,'approved_purchase_recorded':True,
                'current_payment_validity':'not_verified','requires_kirvano_review':True}
            page=http.get('/admin/customers?limit=1',headers=h).json()
            assert len(page['items'])<=1
            if page['next_cursor']:
                after=http.get('/admin/customers',params={'limit':1,'cursor':page['next_cursor']},headers=h).json()
                assert not {x['customer_id'] for x in page['items']} & {x['customer_id'] for x in after['items']}
            assert len(http.get('/admin/customers',headers=h).json()['items'])<=20
            assert http.get('/admin/customers?limit=51',headers=h).status_code==400
            assert http.get('/admin/customers/'+tool.USER_ID,headers={'Origin':'https://evil.example'}).status_code==403
            assert http.post('/admin/auth/logout',headers=h).status_code==200
            assert refs[C.USERS].get().to_dict()['activation_status']=='pending'
    finally:
        for row in client.collection('admin_sessions').where(filter=FieldFilter('admin_id','==',identifier)).stream():owned.append(row.reference)


def test_existing_email_with_other_identity_is_not_adopted(emulator_client):
    client,refs,owned=emulator_client
    foreign=client.collection('users').document('foreign-'+uuid4().hex)
    foreign.create({'schema_version':1,'email_normalization_version':1,'email_normalized':tool.EMAIL,
        'account_status':'enabled','activation_status':'pending','created_at':datetime.now(timezone.utc)})
    owned.append(foreign)
    before=foreign.get().to_dict()
    with pytest.raises(tool.LocalCustomerError):tool.prepare_customer()
    assert foreign.get().to_dict()==before
    assert not any(ref.get().exists for ref in refs.values())


def test_partial_fixture_is_not_repaired(emulator_client):
    client,refs,_=emulator_client
    tool.prepare_customer();refs[C.ENTITLEMENTS].delete()
    before={key:ref.get().to_dict() for key,ref in refs.items()}
    with pytest.raises(tool.LocalCustomerError):tool.prepare_customer()
    assert before=={key:ref.get().to_dict() for key,ref in refs.items()}
