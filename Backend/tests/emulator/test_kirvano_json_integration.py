"""Rejected syntax never reaches commerce or changes guarded demo Firestore."""
import copy
import json
from unittest.mock import Mock
import pytest
from test_commerce import http
from test_kirvano_commercial import payload
from test_admin_customers_integration import state
pytestmark=pytest.mark.firestore_emulator


@pytest.mark.parametrize('body',[
    '{"event":"SALE_APPROVED","event":"SUBSCRIPTION_RENEWED"}',
    '{"customer":{"email":"one@example.com","email":"two@example.com"}}',
    '{"products":[{"id":"one","id":"two"}]}',
])
def test_duplicate_rejection_does_not_change_existing_firestore(http,emulator_client,monkeypatch,body):
    assert http.post('/webhooks/kirvano',json=payload()).status_code==200
    before=state(emulator_client)
    service=Mock(side_effect=AssertionError('Rejected JSON must not reach commerce'))
    monkeypatch.setattr('app.api.kirvano.register_event',service)
    response=http.post('/webhooks/kirvano',content=body,headers={'Content-Type':'application/json'})
    assert response.status_code==400 and response.json()=={'detail':'Invalid JSON'}
    service.assert_not_called()
    assert state(emulator_client)==before


@pytest.mark.parametrize('event',['SALE_REFUNDED','SALE_CHARGEBACK','UNKNOWN'])
def test_valid_review_events_remain_recorded_and_idempotent_without_commercial_changes(http,emulator_client,event):
    sale=payload();assert http.post('/webhooks/kirvano',json=sale).status_code==200
    before=state(emulator_client)
    data=copy.deepcopy(sale);data['event']=event
    data['extra']={'customer':{'id':'same'},'product':{'id':'same'},'values':[1,1]}
    for _ in range(2):assert http.post('/webhooks/kirvano',content=json.dumps(data),headers={'Content-Type':'application/json'}).status_code==200
    after=state(emulator_client)
    for collection,value in before.items():
        if collection!='kirvano_events':assert after[collection]==value
    events=[row.to_dict() for row in emulator_client.collection('kirvano_events').stream(timeout=5)]
    reviews=[row for row in events if row['business_status']=='review_required']
    assert len(events)==2 and len(reviews)==1
    assert reviews[0]['receipt_count']==2 and reviews[0]['variant_count']==1
