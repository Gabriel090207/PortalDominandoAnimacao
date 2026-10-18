"""Bounded exact lookup and isolated HTTP security, synthetic data only."""
from types import SimpleNamespace
from unittest.mock import Mock
from threading import get_ident
import pytest
from fastapi.testclient import TestClient
from app.domain.admin_customers import InvalidCustomerLookup, AmbiguousCustomerLookup
from app.persistence.admin_customers_repository import AdminCustomersRepository, AdminCustomersUnavailable
from app.services.admin_customers_service import AdminCustomersService
from test_admin_customers import app_for, headers, document
from test_admin_domain import admin
from test_admin_sessions import sessions
PATH='/admin/customers/lookup'

def request_headers():
    return dict(headers())|{'X-Admin-Request':'1','Content-Type':'application/json'}

def repository(rows):
    client=Mock();q=client.collection.return_value
    q.where.return_value=q;q.select.return_value=q;q.limit.return_value=q
    q.stream.return_value=[SimpleNamespace(id='customer-a',to_dict=lambda row=row:row) for row in rows]
    return AdminCustomersRepository(client),client,q

@pytest.mark.parametrize('email',['customer@example.com',' CUSTOMER@EXAMPLE.COM '])
def test_exact_normalized_bounded_query(email):
    repo,client,q=repository([document()]);result=repo.find_by_email(email)
    assert result.customer_id=='customer-a' and result.email=='customer@example.com'
    client.collection.assert_called_once_with('users')
    f=q.where.call_args.kwargs['filter'];assert (f.field_path,f.op_string,f.value)==('email_normalized','==','customer@example.com')
    q.limit.assert_called_once_with(2);q.stream.assert_called_once_with(timeout=10)
    assert len(q.select.call_args.args[0])==6
    assert 'synthetic-private' not in result.model_dump_json()
    for method in ('create','set','update','delete','document','offset'):getattr(q,method).assert_not_called()

@pytest.mark.parametrize('email',[None,'','not-email','x@y',[],True])
def test_bad_email_no_firestore(email):
    repo,client,_=repository([])
    with pytest.raises(InvalidCustomerLookup):repo.find_by_email(email)
    client.collection.assert_not_called()

def test_missing_and_ambiguous():
    repo,_,_=repository([]);assert repo.find_by_email('customer@example.com') is None
    repo,_,_=repository([document(),document()])
    with pytest.raises(AmbiguousCustomerLookup):repo.find_by_email('customer@example.com')

@pytest.mark.parametrize('kind',['foreign','corrupt','network'])
def test_sanitized_repository_failure(kind):
    row=document()
    if kind=='foreign':row['email_normalized']='other@example.com'
    if kind=='corrupt':row['schema_version']=False
    repo,_,q=repository([row])
    if kind=='network':q.stream.side_effect=RuntimeError('synthetic-private')
    with pytest.raises(AdminCustomersUnavailable) as caught:repo.find_by_email('customer@example.com')
    assert 'synthetic-private' not in str(caught.value)

@pytest.mark.parametrize('role',['owner','operator'])
def test_authorized_projection_threadpool(role):
    main=get_ident();repo,_,q=repository([document()])
    q.stream.side_effect=lambda **kwargs: (assert_thread(main) or [SimpleNamespace(id='customer-a',to_dict=document)])
    session=Mock();session.validate.return_value=admin(role=role)
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:
        r=http.post(PATH,headers=request_headers(),json={'email':' CUSTOMER@EXAMPLE.COM '})
    assert r.status_code==200 and set(r.json())=={'customer_id','email','account_status','activation_status','created_at'}
    assert r.headers['cache-control']=='no-store' and 'set-cookie' not in r.headers
    assert 'synthetic-private' not in r.text

def assert_thread(main):
    assert get_ident()!=main

@pytest.mark.parametrize('kind,status',[('missing',404),('duplicate',409),('failure',503)])
def test_http_outcomes(kind,status):
    repo,_,q=repository([] if kind=='missing' else [document(),document()])
    if kind=='failure':q.stream.side_effect=RuntimeError('synthetic-private')
    session=Mock();session.validate.return_value=admin()
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:r=http.post(PATH,headers=request_headers(),json={'email':'customer@example.com'})
    assert r.status_code==status and r.headers['cache-control']=='no-store'
    assert 'customer@example.com' not in r.text and 'synthetic-private' not in r.text

@pytest.mark.parametrize('body',['{}','[]','null','{"email":3}','{"email":"x","extra":1}',
    '{"email":"x","email":"y"}','{"email":NaN}','{bad','{"email":"invalid"}'])
def test_invalid_body(body):
    repo,client,_=repository([]);session=Mock();session.validate.return_value=admin()
    with TestClient(app_for(session,AdminCustomersService(repo))) as http:r=http.post(PATH,headers=request_headers(),content=body)
    assert r.status_code==400 and r.headers['cache-control']=='no-store'
    client.collection.assert_not_called()

@pytest.mark.parametrize('kind,status',[('origin',403),('csrf_missing',403),('csrf_bad',403),('content',415),('query',400),('large',413),('permission',403)])
def test_protocol_rejection_before_lookup(monkeypatch,kind,status):
    h=request_headers();path=PATH;body='{"email":"customer@example.com"}'
    if kind=='origin':h['Origin']='https://evil.test'
    if kind=='csrf_missing':del h['X-Admin-Request']
    if kind=='csrf_bad':h['X-Admin-Request']='0'
    if kind=='content':h['Content-Type']='text/plain'
    if kind=='query':path+='?email=synthetic'
    if kind=='large':body=' '*4097
    if kind=='permission':monkeypatch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
    session=Mock();session.validate.return_value=admin();service=Mock()
    with TestClient(app_for(session,service)) as http:r=http.post(path,headers=h,content=body)
    assert r.status_code==status and r.headers['cache-control']=='no-store'
    service.lookup_customer.assert_not_called()

@pytest.mark.parametrize('kind',['absent','invalid','disabled','revoked'])
def test_session_rejected(sessions,kind):
    storage,service=sessions;token=service.create(admin()).token.get_secret_value()
    if kind=='disabled':storage.data['admins/synthetic-admin']['status']='disabled'
    if kind=='invalid':token='bad'
    if kind=='revoked':service.revoke(token)
    h=dict(headers(token))|{'X-Admin-Request':'1'}
    if kind=='absent':h.pop('Cookie')
    customers=Mock()
    with TestClient(app_for(service,customers)) as http:r=http.post(PATH,headers=h,json={'email':'customer@example.com'})
    assert r.status_code==401 and r.headers['cache-control']=='no-store'
    customers.lookup_customer.assert_not_called()

def test_unpublished():
    from app.main import app
    with TestClient(app) as http:assert http.post(PATH,json={'email':'customer@example.com'}).status_code==404
