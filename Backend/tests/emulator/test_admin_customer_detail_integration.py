"""Direct projected reads on guarded demo emulator only."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from test_admin_auth_integration import seed
from test_admin_domain import admin, START
from test_admin_customers_integration import state

pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'


@pytest.mark.parametrize('role',['owner','operator'])
def test_detail_projected_read_no_writes_and_listing_preserved(emulator_client,role):
    seed(emulator_client,role)
    emulator_client.collection('users').document('synthetic-customer').create(dict(schema_version=1,
        email_normalization_version=1,email_normalized='customer@example.com',account_status='enabled',
        activation_status='pending',created_at=START,password_hash='synthetic-private'),timeout=5)
    for collection in ('purchases','subscriptions','entitlements'):
        emulator_client.collection(collection).document('synthetic').create({'sentinel':'unchanged'},timeout=5)
    composition=compose_admin_http(firestore_client=emulator_client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)))
    issued=composition.session_service.create(admin(role=role))
    before=state(emulator_client)
    app=FastAPI();app.include_router(composition.router)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+issued.token.get_secret_value()}
    with TestClient(app) as http:
        response=http.get('/admin/customers/synthetic-customer',headers=headers)
        assert response.status_code==200
        assert response.json()==dict(customer_id='synthetic-customer',email='customer@example.com',
            account_status='enabled',activation_status='pending',created_at=START.isoformat().replace('+00:00','Z'))
        assert response.headers['cache-control']=='no-store'
        assert 'synthetic-private' not in response.text
        missing=http.get('/admin/customers/nonexistent',headers=headers)
        assert missing.status_code==404 and missing.headers['cache-control']=='no-store'
        listing=http.get('/admin/customers',headers=headers)
        assert listing.status_code==200 and listing.json()['items']==[response.json()]
        assert http.get('/admin/auth/session',headers=headers).status_code==200
    assert state(emulator_client)==before
