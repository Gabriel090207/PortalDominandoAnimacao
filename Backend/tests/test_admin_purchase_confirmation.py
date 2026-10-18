"""Synthetic evidence, authorization and manual-activation invariants."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.domain.admin_customers import InvalidCustomerIdentifier
from app.persistence.admin_customers_repository import AdminCustomersRepository, AdminCustomersUnavailable
from app.services.admin_customers_service import AdminCustomersService
from app.domain.models import UserAccessState, Entitlement
from app.services.access_service import can_access_portal
from test_admin_customers import app_for, headers
from test_admin_domain import admin
from test_admin_sessions import sessions
from test_kirvano_commerce_transaction import Client, receive, docs, payload
PATH='/admin/customers/customer-a/purchase-confirmation'

def purchase():
    c=Client();receive(c,payload());return next(iter(docs(c,'purchases').values()))

def repository(rows):
    client=Mock();query=client.collection.return_value
    query.where.return_value=query;query.select.return_value=query;query.limit.return_value=query
    query.stream.return_value=[SimpleNamespace(to_dict=lambda row=row:row) for row in rows]
    return AdminCustomersRepository(client),client,query

def test_bounded_exact_query():
    data=purchase();repo,client,q=repository([data])
    assert repo.has_approved_purchase(data['user_id']) is True
    client.collection.assert_called_once_with('purchases')
    filters=[call.kwargs['filter'] for call in q.where.call_args_list]
    assert [(f.field_path,f.op_string,f.value) for f in filters]==[('user_id','==',data['user_id']),('status','==','active')]
    q.limit.assert_called_once_with(1);q.stream.assert_called_once_with(timeout=10)
    for action in ('set','update','create','delete','document','offset'):getattr(q,action).assert_not_called()

def test_empty_is_not_approval():
    repo,_,_=repository([]);assert repo.has_approved_purchase('customer-a') is False

@pytest.mark.parametrize('kind',['foreign','pending','corrupt','network'])
def test_invalid_evidence_is_sanitized(kind):
    data=purchase();data['user_id']='customer-a'
    if kind=='foreign':data['user_id']='other'
    if kind=='pending':data['status']='pending'
    if kind=='corrupt':data['charge_number']=False
    repo,_,q=repository([data])
    if kind=='network':q.stream.side_effect=RuntimeError('synthetic-secret')
    with pytest.raises(AdminCustomersUnavailable) as error:repo.has_approved_purchase('customer-a')
    assert str(error.value)=='Administrative customer query unavailable.'

def test_bad_id_before_io():
    repo,client,_=repository([])
    with pytest.raises(InvalidCustomerIdentifier):repo.has_approved_purchase('a/b')
    client.collection.assert_not_called()

def test_missing_prevents_purchase_query():
    repo=Mock();repo.get_by_id.return_value=None
    assert AdminCustomersService(repo).purchase_confirmation('customer-a') is None
    repo.get_by_id.assert_called_once_with('customer-a');repo.has_approved_purchase.assert_not_called()

@pytest.mark.parametrize('approved',[True,False])
@pytest.mark.parametrize('role',['owner','operator'])
def test_authorized_response(role,approved):
    session=Mock();session.validate.return_value=admin(role=role)
    repo=Mock();repo.has_approved_purchase.return_value=approved
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:r=http.get(PATH,headers=headers())
    assert r.status_code==200 and r.json()=={'customer_id':'customer-a','approved_purchase_recorded':approved,
        'current_payment_validity':'not_verified','requires_kirvano_review':True}
    assert r.headers['cache-control']=='no-store' and 'set-cookie' not in r.headers
    repo.get_by_id.assert_called_once_with('customer-a');repo.has_approved_purchase.assert_called_once_with('customer-a')

@pytest.mark.parametrize('kind',['absent','invalid','revoked','disabled'])
def test_session_failure(sessions,kind):
    storage,service=sessions;issued=service.create(admin());token=issued.token.get_secret_value()
    if kind=='invalid':token='bad'
    if kind=='revoked':service.revoke(token)
    if kind=='disabled':storage.data['admins/synthetic-admin']['status']='disabled'
    customer=Mock()
    with TestClient(app_for(service,customer)) as http:r=http.get(PATH,headers={'Origin':'https://admin.example.test'} if kind=='absent' else headers(token))
    assert r.status_code==401 and r.headers['cache-control']=='no-store'
    customer.purchase_confirmation.assert_not_called()

@pytest.mark.parametrize('kind',['permission','origin'])
def test_forbidden(monkeypatch,kind):
    session=Mock();session.validate.return_value=admin();customer=Mock()
    if kind=='permission':monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    with TestClient(app_for(session,customer)) as http:r=http.get(PATH,headers=headers() if kind=='permission' else {'Origin':'https://evil.test'})
    assert r.status_code==403 and r.headers['cache-control']=='no-store'
    customer.purchase_confirmation.assert_not_called()

@pytest.mark.parametrize('kind,status',[('missing',404),('failure',503),('id',400),('params',400)])
def test_http_errors(kind,status):
    session=Mock();session.validate.return_value=admin();repo=Mock()
    if kind=='missing':repo.get_by_id.return_value=None
    if kind=='failure':repo.get_by_id.side_effect=RuntimeError('synthetic-secret')
    path=PATH.replace('customer-a','__bad__') if kind=='id' else PATH+'?limit=20' if kind=='params' else PATH
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:r=http.get(path,headers=headers())
    assert r.status_code==status and r.headers['cache-control']=='no-store' and 'synthetic-secret' not in r.text
    repo.has_approved_purchase.assert_not_called()

def test_approval_with_pending_activation_denies_portal():
    c=Client();receive(c,payload())
    key,user=next(iter(docs(c,'users').items()));right=next(iter(docs(c,'entitlements').values()))
    assert user['activation_status']=='pending'
    state=UserAccessState(account_status=user['account_status'],activation_status=user['activation_status'])
    entitlement=Entitlement(**{key:right[key] for key in ('user_id','resource_key','status','valid_from','valid_until')})
    assert entitlement.is_valid_at(right['valid_from'])
    assert not can_access_portal(key.split('/')[1],state,[entitlement],now=right['valid_from'])

def test_unpublished():
    from app.main import app
    with TestClient(app) as http:assert http.get(PATH).status_code==404
