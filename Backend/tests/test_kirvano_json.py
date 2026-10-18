"""Webhook-local JSON hardening; no credentials, SDK clients or production I/O."""
import json
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.kirvano import MAX_BODY_BYTES
from app.domain.kirvano_event import ReceiptResult
from app.domain.states import KirvanoEventState
from test_kirvano_commercial import payload


@pytest.fixture
def webhook(monkeypatch):
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-json-token')
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    service=Mock(return_value=ReceiptResult('a'*64,KirvanoEventState.REVIEW_REQUIRED,'review_required'))
    monkeypatch.setattr('app.api.kirvano.register_event',service)
    forbidden=Mock(side_effect=AssertionError('Firestore must not be reached'))
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    with TestClient(app,headers={'security-token':'synthetic-json-token','Content-Type':'application/json'}) as http:
        yield http,service,forbidden


@pytest.mark.parametrize('body',[
    '{"event":"SALE_APPROVED","event":"SUBSCRIPTION_RENEWED"}',
    '{"event":"SALE_APPROVED","event":"SALE_APPROVED"}',
    '{"customer":{"email":"synthetic-private@example.com","email":"other@example.com"}}',
    '{"payment":{"finished_at":"synthetic-private","finished_at":"other"}}',
    '{"products":[{"id":"one","id":"two"}]}',
    '{"extra":{"nested":{"items":[{"value":1,"value":2}]}}}',
    '{"":1,"":2}',
    r'{"event":"SALE_APPROVED","\u0065vent":"SUBSCRIPTION_RENEWED"}',
])
def test_duplicate_properties_rejected_before_service_or_firestore(webhook,body,caplog):
    http,service,firestore=webhook
    response=http.post('/webhooks/kirvano',content=body)
    assert response.status_code==400 and response.json()=={'detail':'Invalid JSON'}
    service.assert_not_called();firestore.assert_not_called()
    assert 'synthetic-private' not in response.text+caplog.text
    assert 'synthetic-json-token' not in response.text+caplog.text


@pytest.mark.parametrize('data',[
    {'customer':{'id':'abc'},'product':{'id':'xyz'}},
    {'values':[1,1,'same','same',None,None]},
    {'products':[{'id':'same'},{'id':'same'}]},
    {'event':'SALE_APPROVED','Event':'different-case'},
    {'a':1,'a ':2,'é':3,'e\u0301':4},
    payload(),
])
def test_valid_objects_are_preserved_without_normalizing_keys_or_values(webhook,data):
    http,service,firestore=webhook
    response=http.post('/webhooks/kirvano',content=json.dumps(data,ensure_ascii=False))
    assert response.status_code==200 and response.json()=={'received':True}
    service.assert_called_once_with(data);firestore.assert_not_called()


@pytest.mark.parametrize('body',['','{','{"x":1,}','NaN','Infinity','-Infinity','{"x":NaN}','[Infinity]'])
def test_malformed_empty_body_and_nonstandard_constants_still_rejected(webhook,body):
    http,service,firestore=webhook
    response=http.post('/webhooks/kirvano',content=body)
    assert response.status_code==400 and response.json()=={'detail':'Invalid JSON'}
    service.assert_not_called();firestore.assert_not_called()


@pytest.mark.parametrize('data',[{},[],[1,1],'text',None,42,True])
def test_existing_semantic_review_contract_is_not_changed_by_syntax_hardening(webhook,data):
    # Existing endpoint/tests accept valid non-object JSON for review. They are
    # ineligible commercially; this step must not silently change that contract.
    http,service,_=webhook
    response=http.post('/webhooks/kirvano',content=json.dumps(data))
    assert response.status_code==200
    service.assert_called_once_with(data)


@pytest.mark.parametrize('auth',['missing','incorrect','duplicate','empty_configuration'])
def test_authentication_still_precedes_json_validation(webhook,monkeypatch,auth):
    http,service,firestore=webhook
    headers={'Content-Type':'application/json'}
    if auth=='missing':http.headers.pop('security-token')
    if auth=='incorrect':headers['security-token']='synthetic-wrong-token'
    if auth=='duplicate':headers=[('Content-Type','application/json'),('security-token','synthetic-json-token'),('security-token','synthetic-json-token')]
    if auth=='empty_configuration':monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','   ')
    response=http.post('/webhooks/kirvano',content='{"x":1,"x":2}',headers=headers)
    assert response.status_code==401 and response.json()=={'detail':'Unauthorized'}
    service.assert_not_called();firestore.assert_not_called()


def test_size_and_content_type_checks_remain_before_parser(webhook):
    http,service,firestore=webhook
    assert http.post('/webhooks/kirvano',content='{"x":1,"x":2}',headers={'Content-Type':'text/plain'}).status_code==415
    assert http.post('/webhooks/kirvano',content=b' '*(MAX_BODY_BYTES+1)).status_code==413
    service.assert_not_called();firestore.assert_not_called()
    # A syntactically valid body at the boundary remains accepted, not off by one.
    body=b'{}'+b' '*(MAX_BODY_BYTES-2)
    assert http.post('/webhooks/kirvano',content=body).status_code==200
    service.assert_called_once_with({})
