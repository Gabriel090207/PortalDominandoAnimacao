"""Synthetic direct reads/HTTP composition only, no Firebase initialization."""
from types import SimpleNamespace
from unittest.mock import Mock
from threading import get_ident

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from app.domain.admin_customers import InvalidCustomerIdentifier, customer_identifier
from app.persistence.admin_customers_repository import AdminCustomersRepository, AdminCustomersUnavailable
from app.services.admin_customers_service import AdminCustomersService
from test_admin_customers import app_for, headers, document
from test_admin_domain import admin
from test_admin_sessions import sessions


def repository(exists=True,identifier='customer-a'):
    client=Mock()
    client.collection.return_value.document.return_value.get.return_value=SimpleNamespace(exists=exists,id=identifier,to_dict=document)
    return AdminCustomersRepository(client),client


def test_direct_projected_read_only():
    repo,client=repository()
    result=repo.get_by_id('customer-a')
    assert result.customer_id=='customer-a' and result.email=='customer@example.com'
    assert set(result.model_dump())=={'customer_id','email','account_status','activation_status','created_at'}
    assert 'synthetic-private' not in result.model_dump_json()
    client.collection.assert_called_once_with('users')
    collection=client.collection.return_value
    collection.document.assert_called_once_with('customer-a')
    collection.document.return_value.get.assert_called_once_with(field_paths=(
        'schema_version','email_normalized','email_normalization_version','account_status','activation_status','created_at'),timeout=10)
    collection.stream.assert_not_called();collection.where.assert_not_called();collection.select.assert_not_called()
    for action in ('set','update','create','delete'):
        getattr(collection.document.return_value,action).assert_not_called()


def test_missing_document():
    repo,_=repository(False)
    assert repo.get_by_id('customer-a') is None


@pytest.mark.parametrize('identifier',[None,'','.','..','users/other','a/b','__reserved__','x\x00','a\n','a\x7f','a\x85','x'*1501,'\ud800'])
def test_bad_identifier_before_reference(identifier):
    repo,client=repository()
    with pytest.raises(InvalidCustomerIdentifier) as caught:repo.get_by_id(identifier)
    assert str(caught.value)=='Invalid customer identifier.'
    client.collection.assert_not_called()


@pytest.mark.parametrize('identifier',['customer-a','79f9a7a6-1234-4321-9876-123456789abc','cliente-ação','a.b'])
def test_valid_ids_preserved(identifier):
    assert customer_identifier(identifier)==identifier


@pytest.mark.parametrize('kind',['network','binding','corrupt'])
def test_read_failure_sanitized(kind):
    repo,client=repository(identifier='different' if kind=='binding' else 'customer-a')
    ref=client.collection.return_value.document.return_value
    if kind=='network':ref.get.side_effect=ServiceUnavailable('synthetic-private')
    elif kind=='corrupt':ref.get.return_value.to_dict=lambda:document()|{'account_status':'synthetic-private'}
    with pytest.raises(AdminCustomersUnavailable) as caught:repo.get_by_id('customer-a')
    assert 'synthetic-private' not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize('role',['owner','operator'])
def test_authorized_http_projection(role):
    repo,client=repository()
    session=Mock();session.validate.return_value=admin(role=role)
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:
        response=http.get('/admin/customers/customer-a',headers=headers())
    assert response.status_code==200 and response.json()['customer_id']=='customer-a'
    assert set(response.json())=={'customer_id','email','account_status','activation_status','created_at'}
    assert response.headers['cache-control']=='no-store'
    assert 'set-cookie' not in response.headers
    assert 'synthetic-private' not in response.text


def test_http_missing_not_found():
    repo,_=repository(False)
    session=Mock();session.validate.return_value=admin()
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:
        response=http.get('/admin/customers/customer-a',headers=headers())
    assert response.status_code==404 and response.json()=={'detail':'Customer not found.'}
    assert response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('kind',['absent','invalid','revoked','disabled'])
def test_session_rejection_before_customer_read(sessions,kind):
    storage,session=sessions
    issued=session.create(admin())
    token=issued.token.get_secret_value()
    if kind=='invalid':token='bad'
    elif kind=='revoked':session.revoke(token)
    elif kind=='disabled':storage.data['admins/synthetic-admin']['status']='disabled'
    customer=Mock()
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers/customer-a',headers=[('Origin','https://admin.example.test')] if kind=='absent' else headers(token))
    assert response.status_code==401 and response.headers['cache-control']=='no-store'
    customer.get_customer.assert_not_called()


def test_permission_denied(monkeypatch):
    session=Mock();session.validate.return_value=admin()
    customer=Mock()
    monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *a:False)
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers/customer-a',headers=headers())
    assert response.status_code==403
    customer.get_customer.assert_not_called()


def test_bad_origin():
    session,customer=Mock(),Mock()
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers/customer-a',headers={'Origin':'https://evil.test'})
    assert response.status_code==403
    assert session.mock_calls==customer.mock_calls==[]


@pytest.mark.parametrize('path',['/admin/customers/__reserved__','/admin/customers/a%00b','/admin/customers/customer-a?token=synthetic'])
def test_invalid_http_id_or_query(path):
    repo,client=repository()
    session=Mock();session.validate.return_value=admin()
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:
        response=http.get(path,headers=headers())
    assert response.status_code==400 and response.headers['cache-control']=='no-store'
    client.collection.assert_not_called()


def test_arbitrary_path_cannot_reach_other_collection():
    session=Mock();session.validate.return_value=admin()
    customer=Mock()
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers/users%2Fprivate',headers=headers())
    assert response.status_code==404
    customer.get_customer.assert_not_called()


def test_infrastructure_failure_sanitized(caplog,capsys):
    session=Mock();session.validate.return_value=admin()
    customer=Mock();customer.get_customer.side_effect=ServiceUnavailable('synthetic-private')
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers/customer-a',headers=headers())
    assert response.status_code==503 and response.headers['cache-control']=='no-store'
    output=capsys.readouterr()
    assert 'synthetic-private' not in response.text+output.out+output.err+caplog.text


def test_direct_read_off_event_loop():
    session=Mock();session.validate.return_value=admin()
    repo,_=repository();customer=AdminCustomersService(repo)
    threads={};original=customer.get_customer
    def get(identifier):threads['read']=get_ident();return original(identifier)
    customer.get_customer=get
    app=app_for(session,customer)
    @app.middleware('http')
    async def record(request,call_next):threads['loop']=get_ident();return await call_next(request)
    with TestClient(app) as http:assert http.get('/admin/customers/customer-a',headers=headers()).status_code==200
    assert threads['read']!=threads['loop']


def test_main_remains_unchanged(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-webhook')
    with TestClient(app) as http:
        assert http.get('/admin/customers/customer-a',headers=headers()).status_code==404
        assert http.get('/health').status_code==200
        assert http.post('/webhooks/kirvano',json={}).status_code==401
