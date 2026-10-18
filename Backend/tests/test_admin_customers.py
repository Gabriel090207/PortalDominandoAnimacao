"""Bounded read mocks and HTTP app only. No production clients."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from app.api.admin_customers import create_admin_customers_router
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_customers import AdminCustomerPage, customer_pagination, encode_customer_cursor, InvalidCustomerPagination
from app.persistence.admin_customers_repository import AdminCustomersRepository, AdminCustomersUnavailable
from app.services.admin_customers_service import AdminCustomersService
from test_admin_domain import admin, START
from test_admin_sessions import sessions

ORIGIN='https://admin.example.test'
TOKEN='a'*64


def document():
    return dict(schema_version=1,email_normalization_version=1,email_normalized='customer@example.com',
        account_status='enabled',activation_status='pending',created_at=START,secret='synthetic-private')


def repository(documents):
    client=Mock()
    collection=client.collection.return_value
    query=collection.select.return_value.order_by.return_value
    query.start_after.return_value=query
    query.limit.return_value.stream.return_value=iter(documents)
    return AdminCustomersRepository(client),client,query


def snapshot(identifier): return SimpleNamespace(id=identifier,to_dict=document)


def test_bounded_projection_and_cursor():
    repo,client,query=repository([snapshot('a'),snapshot('b'),snapshot('c')])
    result=repo.list_page(limit=2)
    assert [item.customer_id for item in result.items]==['a','b']
    assert result.next_cursor==encode_customer_cursor('b')
    assert 'secret' not in result.model_dump_json()
    client.collection.assert_called_once_with('users')
    query.limit.assert_called_once_with(3)
    query.limit.return_value.stream.assert_called_once_with(timeout=10)
    collection=client.collection.return_value
    collection.select.return_value.order_by.assert_called_once_with('__name__')
    assert set(collection.select.call_args.args[0])=={'schema_version','email_normalized','email_normalization_version','account_status','activation_status','created_at'}


def test_next_page_uses_document_reference_without_lookup():
    repo,client,query=repository([snapshot('c')])
    result=repo.list_page(limit=2,cursor=encode_customer_cursor('b'))
    client.collection.return_value.document.assert_called_once_with('b')
    query.start_after.assert_called_once_with({'__name__':client.collection.return_value.document.return_value})
    client.collection.return_value.document.return_value.get.assert_not_called()
    assert result.next_cursor is None


def test_empty_page():
    repo,_,_=repository([])
    assert repo.list_page().model_dump()=={'items':[],'next_cursor':None}


@pytest.mark.parametrize('limit',[0,-1,51,True,None,'20'])
def test_invalid_limit_no_database(limit):
    repo,client,_=repository([])
    with pytest.raises(InvalidCustomerPagination):repo.list_page(limit=limit)
    client.collection.assert_not_called()


@pytest.mark.parametrize('cursor',['','bad=', '%%%%',encode_customer_cursor('safe')+'=', 'Li4','YS9i','a'*2001])
def test_invalid_cursor(cursor):
    with pytest.raises(InvalidCustomerPagination):customer_pagination(20,cursor)


def test_corrupt_doc_and_firestore_failure_are_sanitized():
    for corrupt in (False,True):
        repo,_,query=repository([SimpleNamespace(id='a',to_dict=lambda:document()|{'account_status':'synthetic-private'})])
        if not corrupt: query.limit.return_value.stream.side_effect=ServiceUnavailable('synthetic-private')
        with pytest.raises(AdminCustomersUnavailable) as caught:repo.list_page()
        assert 'synthetic-private' not in str(caught.value)


def app_for(session_service,customer_service):
    app=FastAPI()
    app.include_router(create_admin_customers_router(session_service=session_service,customers_service=customer_service,
        security_config=AdminRequestSecurityConfig((ORIGIN,))))
    return app


def headers(token=TOKEN):return [('Origin',ORIGIN),('Cookie','__Host-admin_session='+token)]


@pytest.mark.parametrize('role',['owner','operator'])
def test_authorized_roles(role):
    session,customer=Mock(),Mock()
    session.validate.return_value=admin(role=role)
    customer.list_customers.return_value=AdminCustomerPage(items=[],next_cursor=None)
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers',headers=headers())
    assert response.status_code==200 and response.json()=={'items':[],'next_cursor':None}
    assert response.headers['cache-control']=='no-store'
    customer.list_customers.assert_called_once_with(limit=20,cursor=None)


def test_permission_denied_uses_existing_matrix(monkeypatch):
    session,customer=Mock(),Mock()
    session.validate.return_value=admin(role='operator')
    # Both current roles have read_customers. Simulate policy denial without
    # inventing a third domain role or changing the real permission matrix.
    monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers',headers=headers())
    assert response.status_code==403
    customer.list_customers.assert_not_called()


@pytest.mark.parametrize('kind',['missing','invalid','revoked','disabled','absent'])
def test_session_failures(sessions,kind):
    storage,service=sessions
    issued=service.create(admin())
    token=issued.token.get_secret_value()
    if kind=='missing':token='0'*64
    elif kind=='invalid':token='bad'
    elif kind=='revoked':service.revoke(token)
    elif kind=='disabled':storage.data['admins/synthetic-admin']['status']='disabled'
    customer=Mock()
    with TestClient(app_for(service,customer)) as http:
        response=http.get('/admin/customers',headers=[('Origin',ORIGIN)] if kind=='absent' else headers(token))
    assert response.status_code==401
    assert response.headers['cache-control']=='no-store'
    customer.list_customers.assert_not_called()


@pytest.mark.parametrize('query',['limit=0','limit=51','limit=-1','limit=x','limit=20&limit=30','token=secret','cursor=bad='])
def test_bad_query(query):
    session=Mock();session.validate.return_value=admin()
    repo,client,_=repository([])
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:
        response=http.get('/admin/customers?'+query,headers=headers())
    assert response.status_code==400 and response.headers['cache-control']=='no-store'
    client.collection.assert_not_called()


def test_bad_origin_no_io():
    session,customer=Mock(),Mock()
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers',headers={'Origin':'https://evil.test'})
    assert response.status_code==403
    assert session.mock_calls==customer.mock_calls==[]


def test_storage_error_no_data_or_secret(caplog,capsys):
    session=Mock();session.validate.return_value=admin()
    customer=Mock();customer.list_customers.side_effect=ServiceUnavailable('synthetic-private'+TOKEN)
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers',headers=headers())
    assert response.status_code==503 and response.headers['cache-control']=='no-store'
    output=capsys.readouterr()
    assert all(v not in response.text+output.out+output.err+caplog.text for v in (TOKEN,'synthetic-private'))


def test_maximum_is_bounded():
    repo,_,query=repository([])
    repo.list_page(limit=50)
    query.limit.assert_called_once_with(51)


def test_session_storage_error_never_lists():
    session,customer=Mock(),Mock()
    session.validate.side_effect=ServiceUnavailable('synthetic-private')
    with TestClient(app_for(session,customer)) as http:
        response=http.get('/admin/customers',headers=headers())
    assert response.status_code==503
    assert response.headers['cache-control']=='no-store'
    customer.list_customers.assert_not_called()


def test_customer_query_off_event_loop():
    from threading import get_ident
    threads={}
    session,customer=Mock(),Mock()
    session.validate.return_value=admin()
    def listing(**kwargs):
        threads['query']=get_ident()
        return AdminCustomerPage(items=[],next_cursor=None)
    customer.list_customers.side_effect=listing
    app=app_for(session,customer)
    @app.middleware('http')
    async def record(request,call_next):
        threads['loop']=get_ident()
        return await call_next(request)
    with TestClient(app) as http:
        assert http.get('/admin/customers',headers=headers()).status_code==200
    assert threads['query']!=threads['loop']


def test_customer_route_not_public(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-webhook')
    with TestClient(app) as http:
        assert http.get('/admin/customers',headers=headers()).status_code==404
        assert http.get('/health').status_code==200
        assert http.post('/webhooks/kirvano',json={}).status_code==401
