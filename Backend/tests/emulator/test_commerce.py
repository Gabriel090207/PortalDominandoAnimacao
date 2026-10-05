"""Real SDK transactions, synthetic requests, only guarded local emulator."""
from concurrent.futures import ThreadPoolExecutor
import copy
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.persistence.kirvano_commerce_repository import commercial_transaction
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import prepared
from google.cloud import firestore
from uuid import uuid4

pytestmark = pytest.mark.firestore_emulator


@pytest.fixture
def http(emulator_client, monkeypatch):
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN', 'synthetic-webhook-token')
    monkeypatch.setenv('KIRVANO_WEBHOOK_TIMEZONE', 'America/Sao_Paulo')
    monkeypatch.setenv('EMAIL_IDENTITY_HMAC_SECRET', 'synthetic-hmac-secret')
    monkeypatch.setattr('app.api.kirvano.load_dotenv', lambda *a, **k: None)
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client', lambda: emulator_client)
    return TestClient(app, headers={'security-token':'synthetic-webhook-token'})


def count(client, name):
    return len(list(client.collection(name).stream(timeout=5)))


def test_first_atomic(http, emulator_client):
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    for name in ('users','email_identities','subscriptions','purchases','entitlements','kirvano_events'):
        assert count(emulator_client, name) == 1
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['business_status'] == 'applied'


def test_concurrent_same_email(http, emulator_client):
    first = payload(); second = copy.deepcopy(first); second['sale_id'] = 'another-synthetic-sale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda data: http.post('/webhooks/kirvano', json=data), (first, second)))
    diagnostics = {}
    for label, response in zip(('A', 'B'), responses):
        try:
            body = response.json()
        except ValueError:
            body = None
        # Render only fixed safe bodies, never arbitrary response content.
        safe_body = 'omitted'
        if body == {'received': True}:
            safe_body = {'received': True}
        elif body == {'detail': 'Service unavailable'}:
            safe_body = {'detail': 'Service unavailable'}
        diagnostics[label] = {'status_code': response.status_code, 'body': safe_body}
    statuses = tuple(response.status_code for response in responses)
    assert statuses == (200, 200), f'Sanitized request results: {diagnostics}'
    assert count(emulator_client, 'users') == count(emulator_client, 'email_identities') == 1
    assert count(emulator_client, 'purchases') == 2


def test_concurrent_identical(http, emulator_client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: http.post('/webhooks/kirvano', json=payload()), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert count(emulator_client, 'purchases') == count(emulator_client, 'entitlements') == 1
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['receipt_count'] == 2 and event['variant_count'] == 1


def test_concurrent_conflict(http, emulator_client):
    first = payload(); second = copy.deepcopy(first); second['total_price'] = '20'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda data: http.post('/webhooks/kirvano', json=data), (first, second)))
    assert all(response.status_code == 200 for response in responses)
    event = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert event['processing_status'] == 'conflict' and event['business_status'] == 'review_required'
    assert event['variant_count'] == 2 and event['receipt_count'] == 2
    assert count(emulator_client, 'purchases') == count(emulator_client, 'entitlements') == 1
    assert 'application' in event


def test_abort_has_no_partial_writes(emulator_client):
    @firestore.transactional
    def abort(transaction):
        commercial_transaction(transaction, emulator_client, *prepared(payload()), uuid4().hex)
        raise RuntimeError('Synthetic abort before commit')
    with pytest.raises(RuntimeError): abort(emulator_client.transaction())
    for name in ('users','email_identities','subscriptions','purchases','entitlements','kirvano_events'):
        assert count(emulator_client, name) == 0


def test_retry_after_commit(http, emulator_client):
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    before = next(emulator_client.collection('kirvano_events').stream()).to_dict()['application']
    assert http.post('/webhooks/kirvano', json=payload()).status_code == 200
    after = next(emulator_client.collection('kirvano_events').stream()).to_dict()
    assert before == after['application'] and after['receipt_count'] == 2
    for name in ('users','email_identities','subscriptions','purchases','entitlements'):
        assert count(emulator_client, name) == 1
