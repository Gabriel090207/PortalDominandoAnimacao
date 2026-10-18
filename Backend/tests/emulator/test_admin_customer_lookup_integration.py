"""Exact indexed lookup with synthetic users and guarded localhost only."""
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
def test_exact_lookup_ambiguity_and_no_writes(emulator_client,role):
    seed(emulator_client,role)
    for id,email in [('a','buyer@example.com'),('b','buyer+tag@example.com'),('c','buyer.other@example.com'),
        ('dup-a','duplicate@example.com'),('dup-b','duplicate@example.com')]:
        emulator_client.collection('users').document(id).create(dict(schema_version=1,email_normalization_version=1,
            email_normalized=email,account_status='enabled',activation_status='pending',created_at=START,
            internal='synthetic-private'),timeout=5)
    # Legacy documents without the canonical field are never scanned or guessed.
    emulator_client.collection('users').document('legacy').create({'email':'legacy@example.com'},timeout=5)
    for collection in ('purchases','subscriptions','entitlements'):
        emulator_client.collection(collection).document('other-customer').create({'user_id':'b','sentinel':True},timeout=5)
    composition=compose_admin_http(firestore_client=emulator_client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)))
    token=composition.session_service.create(admin(role=role)).token.get_secret_value()
    before=state(emulator_client);app=FastAPI();app.include_router(composition.router)
    h={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Admin-Request':'1'}
    with TestClient(app) as http:
        for email,identifier in [(' BUYER@EXAMPLE.COM ','a'),('buyer+tag@example.com','b'),('buyer.other@example.com','c')]:
            r=http.post('/admin/customers/lookup',headers=h,json={'email':email})
            assert r.status_code==200 and r.json()['customer_id']==identifier
            assert set(r.json())=={'customer_id','email','account_status','activation_status','created_at'}
            assert r.headers['cache-control']=='no-store' and 'synthetic-private' not in r.text
        for email,status in [('missing@example.com',404),('duplicate@example.com',409),('legacy@example.com',404)]:
            r=http.post('/admin/customers/lookup',headers=h,json={'email':email})
            assert r.status_code==status and r.headers['cache-control']=='no-store'
            assert email not in r.text
        assert http.get('/admin/customers/a',headers=h).status_code==200
        assert http.get('/admin/customers/a/purchase-confirmation',headers=h).json()['approved_purchase_recorded'] is False
        assert http.get('/admin/auth/session',headers=h).status_code==200
    assert state(emulator_client)==before
