"""Real webhook -> SDK transaction -> approved renderer -> fake provider.

UUID-owned commercial documents; outbox scoped away from manual Chrome fixtures.
Never loads private .env, calls providers, or invokes global emulator cleanup.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from test_purchase_welcome_integration import emulator_client
from test_kirvano_commercial import payload
from test_welcome_dispatch import configuration, PROVIDER_ID
from app.domain.welcome_email import welcome_intent_id
from app.domain.welcome_dispatch import WelcomeProviderResult
from app.services.kirvano_event_service import normalize_event
from app.services.purchase_welcome_runtime import WelcomeRuntimeInstallation
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy
from app.persistence.admin_customers_repository import AdminCustomersRepository
from app.main import create_app

pytestmark=pytest.mark.firestore_emulator


@pytest.fixture
def flow(emulator_client,monkeypatch):
    raw,prepare,owned=emulator_client
    event,result,identity,user_id=prepare()
    data=payload();data['sale_id']=result.candidate.sale_id
    zone=ZoneInfo('America/Sao_Paulo')
    data['payment']['finished_at']=result.candidate.valid_from.astimezone(zone).strftime('%Y-%m-%d %H:%M:%S')
    data['plan']['next_charge_date']=result.candidate.valid_until.astimezone(zone).strftime('%Y-%m-%d %H:%M:%S')
    data['customer']={'email':result.candidate.email_normalized,'name':'  Gabriel Oliveira  '}
    namespace=raw.collection('step9718_test_namespaces').document(uuid4().hex)
    class ScopedClient:
        project=raw.project
        _database=raw._database
        _emulator_host=raw._emulator_host
        def collection(self,name):return namespace.collection(name) if name=='transactional_emails' else raw.collection(name)
        def transaction(self):return raw.transaction()
    client=ScopedClient();ref=client.collection('transactional_emails').document(welcome_intent_id(result.candidate.purchase_id))
    owned.append(ref)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-personalized-token')
    monkeypatch.setenv('KIRVANO_WEBHOOK_TIMEZONE','America/Sao_Paulo')
    monkeypatch.setenv('EMAIL_IDENTITY_HMAC_SECRET','synthetic-secret')
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**kw:None)
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client',lambda:client)
    fake=Mock();fake.send.return_value=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
    install=WelcomeRuntimeInstallation(True,configuration(),
        WelcomeTriggerPolicy(datetime.now(timezone.utc)-timedelta(seconds=5),False,1),
        client,raw.project,lambda config:fake,True)
    app=create_app(welcome_installation=install)
    try:
        yield app,client,data,ref,fake,user_id,result,owned
    finally:
        # The real orchestrator allocates its own UUID. Discover and remove ONLY
        # the user bound to this fixture's UUID-specific email identity.
        bound=client.collection('email_identities').document(identity.identity_id).get(timeout=5)
        if bound.exists:
            actual=bound.to_dict()['user_id']
            user_ref=client.collection('users').document(actual)
            user=user_ref.get(timeout=5)
            assert user.exists and user.to_dict()['email_normalized']==data['customer']['email']
            owned.append(user_ref)


@pytest.mark.parametrize('offer',['principal','synthetic-monthly-one-real-offer'])
def test_approved_buyer_name_end_to_end_dedup_and_negative_events(flow,offer):
    app,client,data,ref,fake,user_id,result,owned=flow
    if offer!='principal':
        data['products'][0]['offer_id']=offer
        data['total_price']='R$ 1,00'
        changed=normalize_event(data)
        root=client.collection('kirvano_events').document(changed.logical_id)
        owned.append(root.collection('variants').document(changed.fingerprint))
    headers={'security-token':'synthetic-personalized-token'}
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=data,headers={'security-token':'invalid'}).status_code==401
        assert not ref.get(timeout=5).exists
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
        saved=ref.get(timeout=5).to_dict()
        assert saved['status']=='accepted' and saved['customer_name']=='Gabriel Oliveira'
        message=fake.send.call_args.args[0]
        assert 'Olá, Gabriel Oliveira!' in message.html and 'Olá, Gabriel Oliveira!' in message.text
        assert 'Cliente Exemplo' not in message.html
        assert configuration().contact.activation_url().replace('&','&amp;') in message.html
        user_id=saved['user_id']
        customer=AdminCustomersRepository(client).find_by_email(data['customer']['email'])
        assert customer.customer_id==user_id and customer.activation_status=='pending'
        assert client.collection('users').document(user_id).get().to_dict()['display_name']=='Gabriel Oliveira'
        purchase=client.collection('purchases').document(result.candidate.purchase_id).get().to_dict()
        assert purchase['user_id']==user_id and purchase['offer_id']==data['products'][0]['offer_id']
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
        assert ref.get().to_dict()==saved
        fake.send.assert_called_once()
        for kind,status in [('SUBSCRIPTION_CANCELED','CANCELED'),('SALE_REFUNDED','REFUNDED'),('SALE_CHARGEBACK','CHARGEBACK')]:
            negative={**data,'event':kind,'status':status}
            event=normalize_event(negative)
            root=client.collection('kirvano_events').document(event.logical_id)
            owned.extend([root.collection('variants').document(event.fingerprint),root])
            assert http.post('/webhooks/kirvano',json=negative,headers=headers).status_code==200
        fake.send.assert_called_once()
        assert client.collection('subscriptions').document(result.candidate.subscription_id).get().to_dict()['status']=='canceled'
        assert client.collection('purchases').document(result.candidate.purchase_id).get().to_dict()['status']=='active'
        assert client.collection('users').document(user_id).get().to_dict()['activation_status']=='pending'
        assert ref.get().to_dict()==saved


def test_other_product_preserves_review_and_never_sends(flow):
    app,client,data,ref,fake,_,_,owned=flow
    data['products'][0]['id']='synthetic-not-authorized-product'
    changed=normalize_event(data)
    root=client.collection('kirvano_events').document(changed.logical_id)
    owned.append(root.collection('variants').document(changed.fingerprint))
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=data,headers={'security-token':'synthetic-personalized-token'}).status_code==200
    assert root.get().to_dict()['business_status']=='review_required'
    assert not ref.get().exists
    fake.send.assert_not_called()
