"""Bounded evidence query on guarded demo emulator, never production."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from test_admin_auth_integration import seed
from test_admin_domain import admin, START
from test_admin_customers_integration import state
from test_admin_purchase_confirmation import purchase

pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'

@pytest.mark.parametrize('role',['owner','operator'])
def test_confirmation_filtered_read_only_composition(emulator_client,role):
    seed(emulator_client,role)
    for id in ('approved','pending','empty'):
        emulator_client.collection('users').document(id).create(dict(schema_version=1,
            email_normalization_version=1,email_normalized=id+'@example.com',account_status='enabled',
            activation_status='pending',created_at=START),timeout=5)
    base=purchase()
    for id,user,status in [('active-a','approved','active'),('active-b','approved','active'),
        ('pending','pending','pending'),('refunded','pending','refunded'),('other','other','active')]:
        emulator_client.collection('purchases').document(id).create(base|{'user_id':user,'status':status,
            'private_payment':'synthetic-private'},timeout=5)
    for collection in ('subscriptions','entitlements'):
        emulator_client.collection(collection).document('sentinel').create({'unchanged':True},timeout=5)
    composition=compose_admin_http(firestore_client=emulator_client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)))
    issued=composition.session_service.create(admin(role=role))
    before=state(emulator_client);app=FastAPI();app.include_router(composition.router)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+issued.token.get_secret_value()}
    with TestClient(app) as http:
        for customer,expected in [('approved',True),('pending',False),('empty',False)]:
            response=http.get(f'/admin/customers/{customer}/purchase-confirmation',headers=headers)
            assert response.status_code==200
            assert response.json()==dict(customer_id=customer,approved_purchase_recorded=expected,
                current_payment_validity='not_verified',requires_kirvano_review=True)
            assert response.headers['cache-control']=='no-store'
            assert 'synthetic-private' not in response.text
        assert http.get('/admin/customers/missing/purchase-confirmation',headers=headers).status_code==404
        assert http.get('/admin/customers/approved',headers=headers).status_code==200
        assert http.get('/admin/customers',headers=headers).status_code==200
        assert http.get('/admin/auth/session',headers=headers).status_code==200
    assert state(emulator_client)==before
