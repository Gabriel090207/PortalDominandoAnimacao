"""Explicit operational policy, persisted contracts and pre-existing sessions."""
import copy
from types import MappingProxyType
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.domain.admin as domain
from app.api.admin_auth import create_admin_auth_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.persistence.admin_records import AdminRecord,AdminSessionRecord,InvalidAdminRecordError
from test_admin_domain import admin
from test_admin_sessions import sessions,admin_document
from test_admin_http_dependencies import test_app,TOKEN,COOKIE

EXPECTED={'read_customers','read_dashboard','read_audit','activate_customer',
    'suspend_customer','resume_customer','block_customer','unblock_customer'}
PREVIOUS={'read_customers','read_dashboard','read_audit','activate_customer'}

@pytest.mark.parametrize('role',['owner','operator'])
@pytest.mark.parametrize('permission',sorted(EXPECTED))
def test_explicit_operational_permissions_and_http(role,permission):
    assert domain.role_has_permission(role,permission)
    service=Mock();service.validate.return_value=admin(role=role)
    with TestClient(test_app(service,domain.AdminPermission(permission))) as http:
        response=http.get('/protected',headers={'Cookie':f'{COOKIE}={TOKEN}'})
    assert response.status_code==200

@pytest.mark.parametrize('role',['owner','operator'])
@pytest.mark.parametrize('permission',['*','provision_owner','manage_admins','manage_secrets','configure_security','unknown'])
def test_no_technical_or_wildcard_privileges(role,permission):
    assert not domain.role_has_permission(role,permission)


def test_matrix_is_exact_explicit_and_roles_remain_distinct():
    assert set(domain.AdminPermission)==EXPECTED
    assert domain.AdminRole.OWNER!=domain.AdminRole.OPERATOR
    for role in domain.AdminRole:
        assert {p.value for p in domain.AdminPermission if domain.role_has_permission(role,p)}==EXPECTED


def test_browser_claims_cannot_override_denial(monkeypatch):
    monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    service=Mock();service.validate.return_value=admin(role='operator')
    with TestClient(test_app(service,domain.AdminPermission.BLOCK_CUSTOMER)) as http:
        response=http.get('/protected?role=owner&permissions=block_customer',headers={
            'Cookie':f'{COOKIE}={TOKEN}','X-Role':'owner','X-Permissions':'*'})
    assert response.status_code==403


def test_records_have_role_not_permission_snapshots():
    document=admin_document();loaded=AdminRecord.from_document(document)
    assert 'permissions' not in document
    with pytest.raises(InvalidAdminRecordError):AdminRecord.from_document(document|{'permissions':['*']})
    assert loaded.role=='owner'


def test_existing_operator_session_uses_current_policy_without_record_changes(sessions,monkeypatch):
    storage,service=sessions
    storage.data['admins/synthetic-admin']['role']='operator'
    app=FastAPI();app.include_router(create_admin_auth_router(session_service=service,
        security_config=AdminRequestSecurityConfig(('https://admin.example.test',))))
    with monkeypatch.context() as previous:
        matrix=dict(domain._ROLE_PERMISSIONS);matrix[domain.AdminRole.OPERATOR]=frozenset(domain.AdminPermission(p) for p in PREVIOUS)
        previous.setattr(domain,'_ROLE_PERMISSIONS',MappingProxyType(matrix))
        issued=service.create(admin(role='operator'));token=issued.token.get_secret_value()
        headers={'Origin':'https://admin.example.test','Cookie':f'{COOKIE}={token}'}
        with TestClient(app) as http:
            before=http.get('/admin/auth/session',headers=headers)
        assert set(before.json()['permissions'])==PREVIOUS
    documents=copy.deepcopy(storage.data)
    with TestClient(app) as http:after=http.get('/admin/auth/session',headers=headers)
    assert after.status_code==200 and set(after.json()['permissions'])==EXPECTED
    assert storage.data==documents
    assert service.validate(token).role=='operator'
    session_docs=[d for path,d in storage.data.items() if path.startswith('admin_sessions/')]
    assert len(session_docs)==1 and 'permissions' not in session_docs[0] and 'role' not in session_docs[0]
    AdminSessionRecord.from_document(session_docs[0])
