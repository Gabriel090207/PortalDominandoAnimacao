"""Real transactions/ASGI with test audience and payment cutoff; provider FAKE."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from test_kirvano_personalized_welcome_integration import flow
from test_purchase_welcome_integration import emulator_client
from app.domain.welcome_audience import WelcomeAudience
from app.domain.welcome_dispatch import WelcomeProviderResult
from app.services.kirvano_event_service import normalize_event
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy
from app.main import create_app

pytestmark=pytest.mark.firestore_emulator
HEADERS={'security-token':'synthetic-personalized-token'}


def select(flow, *, other=False, general=False):
    old,client,data,ref,fake,_,result,owned=flow
    installation=old.state.purchase_welcome_installation
    recipient=('other-'+uuid4().hex+'@example.com') if other else data['customer']['email']
    config=replace(installation.config,audience=WelcomeAudience('all') if general else WelcomeAudience('test',SecretStr(recipient)))
    return create_app(welcome_installation=replace(installation,config=config))


def track_variant(flow):
    _,client,data,_,_,_,_,owned=flow
    event=normalize_event(data)
    owned.append(client.collection('kirvano_events').document(event.logical_id).collection('variants').document(event.fingerprint))


@pytest.mark.parametrize('general',[False,True])
@pytest.mark.parametrize('frequency',['MONTHLY','ANNUALLY'])
@pytest.mark.parametrize('new_offer',[False,True])
def test_authorized_buyer_one_attempt_on_confirmed_offer(flow,new_offer,frequency,general):
    _,client,data,ref,fake,_,result,_=flow
    if new_offer:
        data['products'][0]['offer_id']='synthetic-test-audience-offer';data['total_price']='R$ 1,00';track_variant(flow)
    data['plan']['charge_frequency']=frequency
    if frequency=='ANNUALLY':
        from zoneinfo import ZoneInfo
        end=result.candidate.valid_from+timedelta(days=365)
        data['plan']['next_charge_date']=end.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%Y-%m-%d %H:%M:%S')
    track_variant(flow)
    with TestClient(select(flow, general=general)) as http:
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert ref.get().to_dict()['status']=='accepted'
        sub=client.collection('subscriptions').document(result.candidate.subscription_id).get().to_dict()
        assert sub['interval']==('monthly' if frequency=='MONTHLY' else 'yearly')
        fake.send.assert_called_once()
        assert 'Olá, Gabriel Oliveira!' in fake.send.call_args.args[0].html
        assert client.collection('users').document(ref.get().to_dict()['user_id']).get().to_dict()['activation_status']=='pending'


def test_other_buyer_commerce_persists_but_every_dispatch_path_denies(flow):
    _,client,data,ref,fake,_,result,_=flow;app=select(flow,other=True)
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert client.collection('purchases').document(result.candidate.purchase_id).get().exists
        snapshot=ref.get();assert snapshot.to_dict()['status']=='pending'
        runtime=app.state.purchase_welcome_trigger
        runtime.after_event(normalize_event(data).logical_id)
        assert runtime.dispatcher.dispatch(ref.id)=='not_dispatched'
        runtime.policy=WelcomeTriggerPolicy(runtime.policy.not_before,True,1)
        runtime.recover_pending()
        assert runtime.dispatcher.repository.reserve(ref.id,attempt_id='a'*64,
            now=datetime.now(timezone.utc),build_request=runtime.dispatcher._request) is None
        assert ref.get().update_time==snapshot.update_time
        fake.send.assert_not_called()


@pytest.mark.parametrize('general',[False,True])
def test_old_payment_reprocessed_now_never_passes_using_new_intent_timestamp(flow,general):
    _,client,data,ref,fake,_,result,_=flow
    paid=result.candidate.valid_from-timedelta(days=1)
    from zoneinfo import ZoneInfo
    data['payment']['finished_at']=paid.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%Y-%m-%d %H:%M:%S')
    track_variant(flow);app=select(flow,general=general)
    cutoff=app.state.purchase_welcome_installation.policy.not_before
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert ref.get().to_dict()['created_at']>=cutoff
        assert ref.get().to_dict()['status']=='pending'
        purchase=client.collection('purchases').document(result.candidate.purchase_id).get().to_dict()
        assert purchase['created_at']>=cutoff and purchase['valid_from']<cutoff
        dispatcher=app.state.purchase_welcome_trigger.dispatcher
        assert dispatcher.dispatch(ref.id,not_before=datetime(2000,1,1,tzinfo=timezone.utc))=='not_dispatched'
        fake.send.assert_not_called()


@pytest.mark.parametrize('general',[False,True])
def test_wrong_product_never_generates_intent(flow,general):
    _,_,data,ref,fake,_,_,_=flow
    data['products'][0]['id']='synthetic-different-product';track_variant(flow)
    with TestClient(select(flow,general=general)) as http:assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
    assert not ref.get().exists;fake.send.assert_not_called()


@pytest.mark.parametrize('general',[False,True])
def test_timeout_does_not_revert_commerce_or_allow_second_attempt(flow,general):
    _,client,data,ref,fake,_,result,_=flow
    fake.send.return_value=WelcomeProviderResult(reason='timeout')
    with TestClient(select(flow,general=general)) as http:
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
        assert ref.get().to_dict()['status']=='requires_review'
        assert client.collection('purchases').document(result.candidate.purchase_id).get().to_dict()['status']=='active'
        assert client.collection('subscriptions').document(result.candidate.subscription_id).get().to_dict()['status']=='active'
        fake.send.assert_called_once()


@pytest.mark.parametrize('frequency',['QUARTERLY','SEMIANNUALLY','unknown'])
def test_general_mode_does_not_accept_unknown_frequency(flow,frequency):
    _,_,data,ref,fake,_,_,_=flow
    data['plan']['charge_frequency']=frequency;track_variant(flow)
    with TestClient(select(flow,general=True)) as http:
        assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
    assert not ref.get().exists
    fake.send.assert_not_called()


def test_general_mode_two_distinct_buyers_share_runtime_without_recipient_filter(flow,emulator_client):
    import copy
    _,prepare,owned=emulator_client
    _,client,first,first_ref,fake,_,_,_=flow
    _,result,identity,_=prepare()
    second=copy.deepcopy(first)
    second['sale_id']=result.candidate.sale_id
    second['customer']['email']=result.candidate.email_normalized
    second['products'][0]['offer_id']='synthetic-second-offer'
    from app.domain.welcome_email import welcome_intent_id
    second_ref=client.collection('transactional_emails').document(welcome_intent_id(result.candidate.purchase_id))
    owned.append(second_ref)
    changed=normalize_event(second)
    owned.append(client.collection('kirvano_events').document(changed.logical_id).collection('variants').document(changed.fingerprint))
    try:
        with TestClient(select(flow,general=True)) as http:
            for data in (first,second,first,second):
                assert http.post('/webhooks/kirvano',json=data,headers=HEADERS).status_code==200
            assert first_ref.get().to_dict()['status']==second_ref.get().to_dict()['status']=='accepted'
            assert fake.send.call_count==2
            assert {call.args[0].recipient for call in fake.send.call_args_list}=={first['customer']['email'],second['customer']['email']}
    finally:
        bound=client.collection('email_identities').document(identity.identity_id).get(timeout=5)
        if bound.exists:
            user=client.collection('users').document(bound.to_dict()['user_id'])
            assert user.get().to_dict()['email_normalized']==second['customer']['email']
            owned.append(user)
