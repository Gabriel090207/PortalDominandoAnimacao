"""Persisted role/session and current permission policy on guarded demo only."""
from types import MappingProxyType
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.domain.admin as domain
from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from test_admin_auth_integration import seed
from test_admin_domain import admin
from test_admin_customers_integration import state
from test_admin_operational_permissions import EXPECTED,PREVIOUS
pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'

@pytest.mark.parametrize('role',['owner','operator'])
def test_persisted_session_policy_transition_without_migration(emulator_client,monkeypatch,role):
    seed(emulator_client,role)
    composed=compose_admin_http(firestore_client=emulator_client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)))
    app=FastAPI();app.include_router(composed.router)
    with monkeypatch.context() as old:
        matrix=dict(domain._ROLE_PERMISSIONS);matrix[domain.AdminRole.OPERATOR]=frozenset(domain.AdminPermission(p) for p in PREVIOUS)
        old.setattr(domain,'_ROLE_PERMISSIONS',MappingProxyType(matrix))
        issued=composed.session_service.create(admin(role=role));token=issued.token.get_secret_value()
        headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Role':'owner','X-Permissions':'*'}
        before=state(emulator_client)
        with TestClient(app) as http:
            result=http.get('/admin/auth/session',headers=headers)
            assert set(result.json()['permissions'])==(EXPECTED if role=='owner' else PREVIOUS)
    with TestClient(app) as http:
        result=http.get('/admin/auth/session',headers=headers)
        assert result.status_code==200 and set(result.json()['permissions'])==EXPECTED
        assert result.json()['role']==role
        assert result.headers['cache-control']=='no-store'
        # Suspension now exists in the isolated router and must enforce CSRF.
        rejected=http.post('/admin/customers/synthetic/suspend',headers=headers,json={'confirm_suspension':True})
        assert rejected.status_code==403 and rejected.headers['cache-control']=='no-store'
        missing=http.post('/admin/customers/synthetic/suspend',headers=headers|{'X-Admin-Request':'1'},json={'confirm_suspension':True})
        assert missing.status_code==404 and missing.json()=={'detail':'Customer not found.'}
        for action in ('resume','block','unblock'):
            assert http.post('/admin/customers/synthetic/'+action,headers=headers,json={}).status_code==404
    assert state(emulator_client)==before
    assert 'permissions' not in next(iter(before['admins'].values()))[0]
    assert 'permissions' not in next(iter(before['admin_sessions'].values()))[0]
