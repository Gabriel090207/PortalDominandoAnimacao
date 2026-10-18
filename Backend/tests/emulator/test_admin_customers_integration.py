"""Real projected cursor queries only on the guarded synthetic emulator."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.persistence.admin_customers_repository import AdminCustomersRepository
from test_admin_auth_integration import seed
from test_admin_domain import admin,START

pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'


def state(client):
    return {collection.id:{snap.id:(snap.to_dict(),snap.update_time) for snap in collection.stream(timeout=5)}
        for collection in client.collections(timeout=5)}


def test_composed_customer_listing_stable_cursor_no_mutations(emulator_client):
    seed(emulator_client)
    for identifier in ('z','b','c','a'):
        emulator_client.collection('users').document(identifier).create(dict(schema_version=1,
            email_normalization_version=1,email_normalized=f'{identifier}@example.com',account_status='enabled',
            activation_status='pending',created_at=START,private_internal='synthetic-private'),timeout=5)
    for collection in ('purchases','subscriptions','entitlements'):
        emulator_client.collection(collection).document('synthetic').create({'sentinel':'unchanged'},timeout=5)
    composition=compose_admin_http(firestore_client=emulator_client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)))
    issued=composition.session_service.create(admin())
    before=state(emulator_client)
    app=FastAPI();app.include_router(composition.router)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+issued.token.get_secret_value()}
    with TestClient(app) as http:
        first=http.get('/admin/customers?limit=2',headers=headers)
        assert first.status_code==200
        assert [item['customer_id'] for item in first.json()['items']]==['a','b']
        cursor=first.json()['next_cursor']
        assert cursor
        second=http.get('/admin/customers',params={'limit':2,'cursor':cursor},headers=headers)
        assert second.status_code==200
        assert [item['customer_id'] for item in second.json()['items']]==['c','z']
        assert second.json()['next_cursor'] is None
        for response in (first,second):
            assert response.headers['cache-control']=='no-store'
            assert 'set-cookie' not in response.headers
            assert 'synthetic-private' not in response.text
            assert set(response.json()['items'][0])=={'customer_id','email','account_status','activation_status','created_at'}
        assert http.get('/admin/customers?limit=51',headers=headers).status_code==400
        assert http.get('/admin/auth/session',headers=headers).status_code==200
    assert state(emulator_client)==before


def test_empty_and_cursor_past_end(emulator_client):
    repo=AdminCustomersRepository(emulator_client)
    assert repo.list_page().model_dump()=={'items':[],'next_cursor':None}
    from app.domain.admin_customers import encode_customer_cursor
    assert repo.list_page(cursor=encode_customer_cursor('last')).items==[]
