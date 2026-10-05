import copy
from unittest.mock import patch
from uuid import uuid4
import pytest
from commerce_fake import Client,Transaction
from test_kirvano_commercial import payload
from app.domain.email_identity import derive_email_identity
from app.services.kirvano_commercial_service import classify_commercial_event
from app.services.kirvano_event_service import normalize_event
from app.persistence.kirvano_commerce_repository import commercial_transaction
from app.services.kirvano_commerce_service import receive_commercial_event

def prepared(data):
    result=classify_commercial_event(data,timezone_name='America/Sao_Paulo')
    identity=derive_email_identity(result.candidate.email_normalized,secret='synthetic-secret') if result.candidate else None
    return normalize_event(data),result,identity

def receive(c,data,commit=True):
    tx=Transaction(c);result=commercial_transaction(tx,c,*prepared(data),uuid4().hex)
    if commit:tx.commit()
    return result

def docs(c,name):return {k:v for k,v in c.data.items() if k.startswith(name+'/') and k.count('/')==1}
def root(c):return next(iter(docs(c,'kirvano_events').values()))

def test_first_retry_privacy():
    c=Client();receive(c,payload())
    for name in ['users','email_identities','subscriptions','purchases','entitlements']:assert len(docs(c,name))==1
    application=copy.deepcopy(root(c)['application']);effects=copy.deepcopy({k:v for k,v in c.data.items() if not k.startswith('kirvano_events/')})
    receive(c,payload())
    assert root(c)['receipt_count']==2 and root(c)['application']==application
    assert {k:v for k,v in c.data.items() if not k.startswith('kirvano_events/')}==effects
    inbox=str({k:v for k,v in c.data.items() if k.startswith('kirvano_events/')})
    assert 'buyer@example.com' not in inbox and 'synthetic-secret' not in inbox
    assert all('can_access' not in v for v in c.data.values())

def test_changed_email():
    c=Client();d=payload();receive(c,d);d['customer']['email']='other@example.com';receive(c,d)
    assert root(c)['variant_count']==1 and root(c)['business_status']=='review_required'
    assert len(docs(c,'users'))==1 and len(docs(c,'purchases'))==1

@pytest.mark.parametrize('field,value',[('activation_status','active'),('activation_status','pending'),('activation_status','suspended'),('account_status','blocked')])
def test_reassignment_preserves_user(field,value):
    c=Client();d=payload();receive(c,d);next(iter(docs(c,'users').values()))[field]=value
    d['sale_id']='another-sale';receive(c,d)
    assert len(docs(c,'users'))==1 and len(docs(c,'email_identities'))==1
    assert next(iter(docs(c,'users').values()))[field]==value
    for name in ['subscriptions','purchases','entitlements']:assert len(docs(c,name))==2

@pytest.mark.parametrize('collection',['users','purchases','subscriptions','entitlements'])
def test_missing_application_document_abort(collection):
    c=Client();receive(c,payload());del c.data[next(iter(docs(c,collection)))];before=copy.deepcopy(c.data)
    with pytest.raises(RuntimeError):receive(c,payload())
    assert c.data==before

@pytest.mark.parametrize('collection',['users','entitlements'])
def test_orphan_and_pair(collection):
    c=Client();receive(c,payload());root(c).pop('application');root(c)['business_status']='review_required'
    del c.data[next(iter(docs(c,collection)))];before=copy.deepcopy(c.data)
    with pytest.raises(RuntimeError):receive(c,payload())
    assert c.data==before

@pytest.mark.parametrize('collection,field,value',[('purchases','user_id','other-user'),('subscriptions','user_id','other-user'),('entitlements','purchase_id','other-purchase')])
def test_binding_review(collection,field,value):
    c=Client();receive(c,payload());next(iter(docs(c,collection).values()))[field]=value
    application=copy.deepcopy(root(c)['application']);receive(c,payload())
    assert root(c)['business_status']=='review_required' and root(c)['application']==application
    assert len(docs(c,'users'))==1

def test_conflict_preserves():
    c=Client();d=payload();receive(c,d);application=copy.deepcopy(root(c)['application'])
    d['total_price']='20';receive(c,d);receive(c,payload())
    assert root(c)['processing_status']=='conflict' and root(c)['business_status']=='review_required'
    assert root(c)['application']==application and len(docs(c,'entitlements'))==1

@pytest.mark.parametrize('collection,status',[('entitlements','revoked'),('subscriptions','canceled'),('purchases','refunded'),('purchases','chargeback')])
def test_no_restore(collection,status):
    c=Client();receive(c,payload());next(iter(docs(c,collection).values()))['status']=status;receive(c,payload())
    assert next(iter(docs(c,collection).values()))['status']==status

def test_abort_and_retry():
    c=Client();receive(c,payload(),False);assert c.data=={}
    receive(c,payload());receive(c,payload());assert root(c)['receipt_count']==2
    assert len(docs(c,'purchases'))==1

@pytest.mark.parametrize('event',['SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED','SALE_REFUNDED','SALE_CHARGEBACK','UNKNOWN'])
def test_unsupported(event):
    c=Client();d=payload();d['event']=event;receive(c,d)
    assert all(k.startswith('kirvano_events/') for k in c.data)
    assert root(c)['business_status']=='review_required'

@pytest.mark.parametrize('env',[{}, {'KIRVANO_WEBHOOK_TIMEZONE':'Invalid/Zone'}, {'KIRVANO_WEBHOOK_TIMEZONE':'America/Sao_Paulo'}])
def test_bad_config(env):
    with patch.dict('os.environ',env,clear=True),patch('app.persistence.kirvano_commerce_repository.get_firestore_client') as get:
        with pytest.raises(RuntimeError):receive_commercial_event(payload())
        get.assert_not_called()

@pytest.mark.parametrize('corruption',[('purchases','schema_version',True),('entitlements','valid_until',None),('users','activation_status','invalid')])
def test_corrupt_structure_aborts(corruption):
    c=Client();receive(c,payload());collection,field,value=corruption
    next(iter(docs(c,collection).values()))[field]=value;before=copy.deepcopy(c.data)
    with pytest.raises((RuntimeError,ValueError)):receive(c,payload())
    assert c.data==before


def test_existing_identity_wrong_email_review():
    c=Client();receive(c,payload());next(iter(docs(c,'users').values()))['email_normalized']='other@example.com'
    receive(c,payload());assert root(c)['business_reason_codes']==['email_binding_mismatch']


def test_historical_inbox_requires_fresh_full_receipt():
    from app.persistence.kirvano_events_repository import _record_transaction
    c=Client();event=normalize_event(payload());r=c.collection('kirvano_events').document(event.logical_id)
    tx=Transaction(c);_record_transaction(tx,r,r.collection('variants').document(event.fingerprint),event);tx.commit()
    assert 'application' not in root(c)
    receive(c,payload());assert root(c)['business_status']=='applied' and root(c)['receipt_count']==2


def test_new_charge_does_not_reactivate_canceled_subscription():
    c=Client();d=payload();receive(c,d);next(iter(docs(c,'subscriptions').values()))['status']='canceled'
    d['plan']['charge_number']=2;receive(c,d)
    assert len(docs(c,'purchases'))==1
    assert any(v['business_reason_codes']==['subscription_not_active'] for v in docs(c,'kirvano_events').values())


def test_http_orchestration_and_redaction():
    from fastapi.testclient import TestClient
    from app.main import app
    c=Client()
    def persist(event,result,identity,user_id):
        tx=Transaction(c);receipt=commercial_transaction(tx,c,event,result,identity,user_id);tx.commit();return receipt
    env={'KIRVANO_WEBHOOK_TOKEN':'synthetic-http-token','KIRVANO_WEBHOOK_TIMEZONE':'America/Sao_Paulo','EMAIL_IDENTITY_HMAC_SECRET':'synthetic-http-hmac'}
    with patch.dict('os.environ',env,clear=True),patch('app.api.kirvano.load_dotenv'),patch('app.persistence.kirvano_commerce_repository.record_commercial_event',side_effect=persist),patch('app.api.kirvano.logger.info') as logger:
        client=TestClient(app,headers={'security-token':env['KIRVANO_WEBHOOK_TOKEN']})
        assert client.post('/webhooks/kirvano',json=payload()).status_code==200
        assert root(c)['business_status']=='applied'
        assert 'buyer@example.com' not in str(logger.call_args)
        assert env['EMAIL_IDENTITY_HMAC_SECRET'] not in str(logger.call_args)
        del c.data[next(iter(docs(c,'users')))]
        response=client.post('/webhooks/kirvano',json=payload())
        assert response.status_code==503 and response.json()=={'detail':'Service unavailable'}
