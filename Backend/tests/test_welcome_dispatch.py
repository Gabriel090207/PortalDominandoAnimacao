"""Synthetic transport only, buffered-memory transactions, no Firebase access."""
import copy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock
import httpx
import pytest
from pydantic import SecretStr
from commerce_fake import Client, Transaction, Ref
from test_kirvano_commerce_transaction import receive, docs
from test_kirvano_commercial import payload
from app.config.purchase_welcome import PurchaseWelcomeConfig, load_purchase_welcome_config
from app.services.purchase_welcome_email import WelcomeEmailContact, WelcomeEmailConfigurationError
from app.services.purchase_welcome_dispatch import PurchaseWelcomeDispatchService, WelcomeDispatchUnavailable
from app.services.resend_email_provider import ResendEmailProvider
from app.domain.welcome_dispatch import WelcomeDispatchRecord, WelcomeProviderResult, resend_idempotency_key
from app.persistence.welcome_emails_repository import WelcomeEmailsRepository, WelcomeEmailStorageError

PROVIDER_ID='01234567-89ab-4cde-8123-0123456789ab'
NOW=datetime(2026,10,27,tzinfo=timezone.utc)


def configuration():
    return PurchaseWelcomeConfig(True,SecretStr('re_synthetic_test_secret'),
        'mail@example.com',WelcomeEmailContact('https://wa.me/15555550123'))


@pytest.fixture
def setup(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('Real Firebase forbidden')
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr(Ref,'id',property(lambda ref:ref.path.rsplit('/',1)[1]),raising=False)
    client=Client();receive(client,payload())
    client.transaction=lambda:Transaction(client)
    def transactional(function):
        def run(tx,*args):
            result=function(tx,*args);tx.commit();return result
        return run
    monkeypatch.setattr('app.persistence.welcome_emails_repository.firestore.transactional',transactional)
    identifier=next(iter(docs(client,'transactional_emails'))).split('/')[1]
    repository=WelcomeEmailsRepository(client)
    return client,identifier,repository


def make_service(setup,handler):
    client,identifier,repository=setup
    config=configuration()
    provider=ResendEmailProvider(config,transport=httpx.MockTransport(handler))
    return PurchaseWelcomeDispatchService(repository,provider,config,clock=lambda:NOW)


def record(setup):
    client,identifier,_=setup
    return WelcomeDispatchRecord.model_validate(client.data['transactional_emails/'+identifier])


def test_reserve_payload_acceptance_no_repeat_and_manual_activation(setup,caplog):
    requests=[]
    def handler(request):
        assert record(setup).status=='in_progress'  # Reservation committed before HTTP.
        requests.append(request)
        return httpx.Response(200,json={'id':PROVIDER_ID})
    service=make_service(setup,handler)
    client,identifier,repository=setup
    commerce=copy.deepcopy({k:v for k,v in client.data.items() if not k.startswith('transactional_emails/')})
    assert service.dispatch(identifier)=='accepted'
    assert service.dispatch(identifier)=='not_dispatched' and len(requests)==1
    message=json.loads(requests[0].content)
    assert set(message)=={'from','to','subject','html','text'}
    assert message['from']=='mail@example.com' and message['to']==['buyer@example.com']
    assert 'liberado manualmente' in message['text'] and 'https://wa.me/15555550123?' in message['html']
    assert requests[0].url==httpx.URL('https://api.resend.com/emails') and requests[0].method=='POST'
    assert requests[0].headers['Authorization']=='Bearer re_synthetic_test_secret'
    assert requests[0].headers['Idempotency-Key']==resend_idempotency_key(identifier)
    saved=record(setup)
    assert saved.status=='accepted' and saved.provider_id==PROVIDER_ID
    assert saved.request.payload()==message and saved.request.digest()==saved.request_digest
    assert commerce=={k:v for k,v in client.data.items() if not k.startswith('transactional_emails/')}
    assert next(iter(docs(client,'users').values()))['activation_status']=='pending'
    assert 're_synthetic' not in caplog.text and 'buyer@example.com' not in caplog.text


@pytest.mark.parametrize('status,body,reason',[
    (200,{'id':PROVIDER_ID},'accepted'),(200,{},'invalid_response'),(200,{'id':'bad'},'invalid_response'),
    (200,[],'invalid_response'),(400,{'name':'validation_error'},'rejected'),
    (401,{'name':'validation_error'},'authentication'),(403,{'name':'invalid_permission'},'authentication'),
    (422,{'name':'validation_error'},'rejected'),(429,{'name':'daily_quota_exceeded'},'quota'),
    (409,{'name':'concurrent_idempotent_requests'},'concurrent_request'),
    (409,{'name':'invalid_idempotent_request'},'idempotency_conflict'),
    (500,{'name':'application_error'},'unknown_response'),(503,{'name':'service_unavailable'},'unknown_response'),
    (302,{'location':'https://evil.example'},'unknown_response'),
])
def test_outcomes_no_blind_retry(setup,status,body,reason):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,json=body)
    service=make_service(setup,handler);_,identifier,_=setup
    outcome=service.dispatch(identifier)
    assert record(setup).reason==reason
    assert outcome==('accepted' if reason=='accepted' else 'requires_review')
    assert service.dispatch(identifier)=='not_dispatched' and len(calls)==1


@pytest.mark.parametrize('error,reason',[(httpx.ReadTimeout,'timeout'),(httpx.ConnectTimeout,'timeout'),
    (httpx.ConnectError,'network'),(httpx.ReadError,'network'),(RuntimeError,'internal_failure')])
def test_network_is_uncertain_not_unsent(setup,error,reason,caplog):
    calls=[]
    def handler(request):calls.append(request);raise error('synthetic-private-key-and-email')
    service=make_service(setup,handler);_,identifier,_=setup
    assert service.dispatch(identifier)=='requires_review' and record(setup).reason==reason
    service.clock=lambda:NOW+timedelta(days=2)
    assert service.dispatch(identifier)=='not_dispatched' and len(calls)==1
    assert 'synthetic-private' not in caplog.text


@pytest.mark.parametrize('content',[b'not JSON',b'{"id":"x","id":"y"}',b'{"id":NaN}',b'x'*65537])
def test_invalid_raw_response_review(setup,content):
    service=make_service(setup,lambda request:httpx.Response(200,content=content))
    assert service.dispatch(setup[1])=='requires_review' and record(setup).reason=='invalid_response'


def test_failure_during_reservation_never_calls_http(setup,monkeypatch):
    handler=Mock()
    service=make_service(setup,handler)
    monkeypatch.setattr(service.repository,'reserve',Mock(side_effect=RuntimeError('private')))
    with pytest.raises(WelcomeDispatchUnavailable) as caught:service.dispatch(setup[1])
    handler.assert_not_called()
    assert 'private' not in str(caught.value) and record(setup).status=='pending'


def test_render_failure_before_send_does_not_reserve(setup,monkeypatch):
    handler=Mock();service=make_service(setup,handler)
    monkeypatch.setattr(service,'_request',Mock(side_effect=RuntimeError('private')))
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(setup[1])
    handler.assert_not_called();assert record(setup).status=='pending'


def test_accepted_but_storage_failure_never_retries(setup,monkeypatch):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json={'id':PROVIDER_ID})
    service=make_service(setup,handler)
    monkeypatch.setattr(service.repository,'finish',Mock(side_effect=RuntimeError('private')))
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(setup[1])
    assert record(setup).status=='in_progress'
    service.clock=lambda:NOW+timedelta(days=2)
    assert service.dispatch(setup[1])=='not_dispatched' and len(calls)==1


def test_confirmed_commit_with_lost_reservation_ack_no_http(setup,monkeypatch):
    service=make_service(setup,Mock());original=service.repository.reserve
    def lost(*args,**kw):original(*args,**kw);raise RuntimeError('uncertain acknowledgement')
    monkeypatch.setattr(service.repository,'reserve',lost)
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(setup[1])
    assert record(setup).status=='in_progress'
    service.provider._client._transport.handler.assert_not_called()


def test_interrupted_review_no_new_claim_and_late_result_cannot_overwrite(setup):
    service=make_service(setup,Mock());_,identifier,repo=setup
    reserved=repo.reserve(identifier,attempt_id='a'*64,now=NOW,build_request=service._request)
    assert not repo.review_interrupted(identifier,now=NOW+timedelta(minutes=1))
    assert repo.review_interrupted(identifier,now=NOW+timedelta(days=2))
    assert record(setup).reason=='interrupted'
    assert not repo.finish(identifier,attempt_id=reserved.attempt_id,
        result=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID),now=NOW+timedelta(days=2))
    assert record(setup).status=='requires_review' and service.dispatch(identifier)=='not_dispatched'


def test_claim_exclusive_and_attempt_fencing(setup):
    service=make_service(setup,Mock());_,identifier,repo=setup
    first=repo.reserve(identifier,attempt_id='a'*64,now=NOW,build_request=service._request)
    assert first and repo.reserve(identifier,attempt_id='b'*64,now=NOW,build_request=service._request) is None
    assert not repo.finish(identifier,attempt_id='b'*64,result=WelcomeProviderResult(reason='rejected'),now=NOW)
    assert record(setup).attempt_id=='a'*64 and record(setup).status=='in_progress'


def test_old_pending_can_send_for_first_time(setup):
    service=make_service(setup,lambda request:httpx.Response(200,json={'id':PROVIDER_ID}))
    service.clock=lambda:NOW+timedelta(days=90)
    assert service.dispatch(setup[1])=='accepted'


@pytest.mark.parametrize('field,value',[('recipient','other@example.com'),('user_id','other-user'),
    ('purchase_id','0'*64),('origin_event_id','0'*64)])
def test_corrupt_binding_no_http(setup,field,value):
    client,identifier,_=setup;client.data['transactional_emails/'+identifier][field]=value
    handler=Mock();service=make_service(setup,handler)
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(identifier)
    handler.assert_not_called()


def env():
    return {'PURCHASE_WELCOME_SEND_ENABLED':'true','RESEND_API_KEY':'re_synthetic_test_secret',
        'PURCHASE_WELCOME_FROM':'mail@example.com','PURCHASE_WELCOME_WHATSAPP_URL':'https://wa.me/15555550123'}


def test_disabled_config_does_not_read_file(tmp_path):
    path=tmp_path/'.env';path.write_text('PURCHASE_WELCOME_SEND_ENABLED=true\n')
    assert load_purchase_welcome_config(environ={},env_file=path) is None
    assert load_purchase_welcome_config(environ={'PURCHASE_WELCOME_SEND_ENABLED':'false'},env_file=path) is None


@pytest.mark.parametrize('field',['RESEND_API_KEY','PURCHASE_WELCOME_FROM','PURCHASE_WELCOME_WHATSAPP_URL'])
def test_incomplete_configuration_sanitized(field):
    values=env();values.pop(field)
    with pytest.raises(WelcomeEmailConfigurationError) as caught:load_purchase_welcome_config(environ=values,env_file=None)
    assert str(caught.value)=='Purchase welcome email configuration unavailable.'


@pytest.mark.parametrize('field,value',[('PURCHASE_WELCOME_SEND_ENABLED','yes'),('RESEND_API_KEY',''),
    ('RESEND_API_KEY','re_injected\r\nsecret'),('PURCHASE_WELCOME_FROM','bad'),
    ('PURCHASE_WELCOME_FROM','Name <mail@example.com>'),('PURCHASE_WELCOME_WHATSAPP_URL','https://evil.example')])
def test_invalid_config(field,value):
    values=env();values[field]=value
    with pytest.raises(WelcomeEmailConfigurationError):load_purchase_welcome_config(environ=values,env_file=None)


def test_dotenv_read_only_and_no_invalid_process_fallback(tmp_path):
    path=tmp_path/'.env';values=env();path.write_text('\n'.join(k+'='+v for k,v in values.items()))
    process={'PURCHASE_WELCOME_SEND_ENABLED':'true'}
    config=load_purchase_welcome_config(environ=process,env_file=path)
    assert config.sender=='mail@example.com' and process=={'PURCHASE_WELCOME_SEND_ENABLED':'true'}
    process['RESEND_API_KEY']=''
    with pytest.raises(WelcomeEmailConfigurationError):load_purchase_welcome_config(environ=process,env_file=path)


@pytest.mark.parametrize('value',['','x'*257,'purchase-welcome/private',None])
def test_idempotency_key_invalid_no_request(setup,value):
    handler=Mock();provider=ResendEmailProvider(configuration(),transport=httpx.MockTransport(handler))
    request=make_service(setup,handler)._request(record(setup).pending_intent())
    from app.services.purchase_welcome_email import RenderedWelcomeEmail
    message=RenderedWelcomeEmail(request.recipient,request.subject,request.html,request.text)
    with pytest.raises(ValueError):provider.send(message,sender=request.sender,idempotency_key=value)
    handler.assert_not_called()


def test_result_commit_ack_lost_preserves_accepted_id(setup,monkeypatch):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json={'id':PROVIDER_ID})
    service=make_service(setup,handler);original=service.repository.finish
    def lost(*args,**kw):original(*args,**kw);raise RuntimeError('private lost acknowledgement')
    monkeypatch.setattr(service.repository,'finish',lost)
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(setup[1])
    assert record(setup).status=='accepted' and record(setup).provider_id==PROVIDER_ID
    assert service.dispatch(setup[1])=='not_dispatched' and len(calls)==1


def test_snapshot_survives_configuration_change_after_claim(setup,monkeypatch):
    calls=[]
    def handler(request):calls.append(json.loads(request.content));return httpx.Response(200,json={'id':PROVIDER_ID})
    service=make_service(setup,handler);original=service.repository.reserve
    def reserve(*args,**kw):
        saved=original(*args,**kw)
        service.config=PurchaseWelcomeConfig(True,SecretStr('re_different_synthetic_key'),
            'another@example.com',WelcomeEmailContact('https://wa.me/15555550124'))
        monkeypatch.setattr('app.services.purchase_welcome_dispatch.render_purchase_welcome',
            Mock(side_effect=AssertionError('Never rerender a reserved request')))
        return saved
    monkeypatch.setattr(service.repository,'reserve',reserve)
    assert service.dispatch(setup[1])=='accepted'
    assert calls[0]['from']=='mail@example.com' and '15555550123' in calls[0]['html']
    assert calls[0]==record(setup).request.payload()


def test_snapshot_tamper_fails_closed(setup):
    service=make_service(setup,Mock());_,identifier,repo=setup
    repo.reserve(identifier,attempt_id='a'*64,now=NOW,build_request=service._request)
    setup[0].data['transactional_emails/'+identifier]['request']['text']='tampered'
    with pytest.raises(WelcomeDispatchUnavailable):service.dispatch(identifier)
    service.provider._client._transport.handler.assert_not_called()


def test_no_default_transport_or_disabled_composition(setup):
    with pytest.raises(WelcomeEmailConfigurationError):ResendEmailProvider(configuration(),transport=None)
    with pytest.raises(WelcomeEmailConfigurationError):PurchaseWelcomeDispatchService(setup[2],Mock(),None)
