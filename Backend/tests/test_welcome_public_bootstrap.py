"""Process-only public bootstrap; all providers/Firestore clients are synthetic."""
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from app.main import create_app
from app.config.purchase_welcome import load_purchase_welcome_config
from app.domain.welcome_audience import WelcomeAudience
from app.domain.welcome_dispatch import WelcomeProviderResult
from app.services.purchase_welcome_bootstrap import prepare_public_welcome
from app.services.purchase_welcome_dispatch import PurchaseWelcomeDispatchService
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError
from app.services.purchase_welcome_trigger import PurchaseWelcomeTrigger, WelcomeTriggerPolicy
from app.persistence.welcome_emails_repository import WelcomeEmailsRepository
from test_welcome_dispatch import setup, env, PROVIDER_ID, configuration
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import receive, prepared

CUT=datetime(2026,10,1,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_live_construction(monkeypatch):
    forbidden=Mock(side_effect=AssertionError('Real clients forbidden'))
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr('app.services.purchase_welcome_bootstrap._provider',forbidden)


def settings():
    return {**env(),'FIREBASE_PROJECT_ID':'synthetic-runtime-project','PURCHASE_WELCOME_RECOVERY_ENABLED':'false',
        'PURCHASE_WELCOME_NOT_BEFORE':'2026-10-01T00:00:00Z'}


@pytest.mark.parametrize('values',[{}, {'PURCHASE_WELCOME_SEND_ENABLED':'false'},
    {'PURCHASE_WELCOME_SEND_ENABLED':'false','RESEND_API_KEY':'re_synthetic_ignored'}])
def test_disabled_no_firestore_or_provider(values):
    app=create_app();client=Mock();provider=Mock()
    assert not prepare_public_welcome(app,environ=values,client_factory=client,provider_factory=provider)
    client.assert_not_called();provider.assert_not_called()


@pytest.mark.parametrize('missing',['RESEND_API_KEY','PURCHASE_WELCOME_FROM','PURCHASE_WELCOME_WHATSAPP_URL',
    'PURCHASE_WELCOME_NOT_BEFORE','PURCHASE_WELCOME_AUDIENCE_MODE','PURCHASE_WELCOME_TEST_AUTHORIZED',
    'PURCHASE_WELCOME_TEST_RECIPIENT','FIREBASE_PROJECT_ID'])
def test_incomplete_fails_closed_without_constructing_clients(missing):
    values=settings();values.pop(missing);app=create_app();client=Mock();provider=Mock()
    assert not prepare_public_welcome(app,environ=values,client_factory=client,provider_factory=provider)
    assert app.state.purchase_welcome_runtime_status=='unavailable'
    client.assert_not_called();provider.assert_not_called()


@pytest.mark.parametrize('name,value',[('PURCHASE_WELCOME_AUDIENCE_MODE','unknown'),
    ('PURCHASE_WELCOME_TEST_AUTHORIZED','false'),('PURCHASE_WELCOME_TEST_RECIPIENT','bad'),
    ('PURCHASE_WELCOME_NOT_BEFORE','2026-10-01T00:00:00'),('PURCHASE_WELCOME_RECOVERY_ENABLED','true'),
    ('FIREBASE_PROJECT_ID','demo-unsafe-project'),('FIRESTORE_EMULATOR_HOST','127.0.0.1:8080')])
def test_invalid_public_mode_is_unavailable(name,value):
    values=settings();values[name]=value;client=Mock()
    assert not prepare_public_welcome(create_app(),environ=values,client_factory=client,provider_factory=Mock())
    client.assert_not_called()


@pytest.fixture
def selected(setup,monkeypatch):
    client,identifier,_=setup
    from commerce_fake import Ref,Transaction
    original=Ref.get
    monkeypatch.setattr(Ref,'get',lambda ref,transaction=None,**kw:original(ref,transaction or Transaction(client)))
    client.project='synthetic-runtime-project';client._database='(default)';client._emulator_host=None
    for row in client.data.values():
        if 'created_at' in row:row['created_at']=datetime(2026,10,20,tzinfo=timezone.utc)
    fake=Mock();fake.send.return_value=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
    return client,identifier,fake


def test_direct_dispatch_and_raw_reservation_share_private_audience_guard(selected):
    client,identifier,fake=selected
    config=load_purchase_welcome_config(environ=settings(),env_file=None)
    service=PurchaseWelcomeDispatchService(WelcomeEmailsRepository(client),fake,config)
    client.data['transactional_emails/'+identifier]['recipient']='someone-else@example.com'
    assert service.dispatch(identifier)=='not_dispatched'
    assert service.repository.reserve(identifier,attempt_id='a'*64,now=datetime.now(timezone.utc),build_request=service._request) is None
    fake.send.assert_not_called()
    assert client.data['transactional_emails/'+identifier]['status']=='pending'


def test_missing_audience_or_cutoff_is_not_a_permissive_fallback(selected):
    client,identifier,fake=selected
    for config in (replace(configuration(),audience=WelcomeAudience()),replace(configuration(),not_before=None)):
        service=PurchaseWelcomeDispatchService(WelcomeEmailsRepository(client),fake,config)
        assert service.dispatch(identifier)=='not_dispatched'
    assert WelcomeEmailsRepository(client).reserve(identifier,attempt_id='a'*64,now=datetime.now(timezone.utc),build_request=Mock()) is None
    fake.send.assert_not_called()


def test_recovery_cannot_bypass_audience(selected):
    client,identifier,fake=selected
    service=PurchaseWelcomeDispatchService(WelcomeEmailsRepository(client),fake,load_purchase_welcome_config(environ=settings(),env_file=None))
    client.data['transactional_emails/'+identifier]['recipient']='someone-else@example.com'
    service.repository.pending_batch=Mock(return_value=[identifier])
    PurchaseWelcomeTrigger(service,WelcomeTriggerPolicy(CUT,True,1)).recover_pending()
    fake.send.assert_not_called()


@pytest.mark.parametrize('kind',['old_payment','old_purchase_commit','old_intent','future_payment'])
def test_all_relevant_purchase_times_are_checked_not_only_new_receipt(selected,kind):
    client,identifier,fake=selected;config=load_purchase_welcome_config(environ=settings(),env_file=None)
    service=PurchaseWelcomeDispatchService(WelcomeEmailsRepository(client),fake,config)
    purchase=next(v for k,v in client.data.items() if k.startswith('purchases/'))
    old=datetime(2026,9,30,tzinfo=timezone.utc)
    if kind=='old_payment':purchase['valid_from']=old
    elif kind=='old_purchase_commit':purchase['created_at']=old
    elif kind=='old_intent':client.data['transactional_emails/'+identifier]['created_at']=old
    else:
        purchase['valid_from']=datetime(2100,1,1,tzinfo=timezone.utc);purchase['valid_until']=datetime(2100,2,1,tzinfo=timezone.utc)
    assert service.dispatch(identifier,not_before=datetime(2020,1,1,tzinfo=timezone.utc))=='not_dispatched'
    fake.send.assert_not_called()


def test_authorized_target_once_and_restart_removes_environment_selection(selected,monkeypatch):
    client,identifier,fake=selected
    monkeypatch.setattr('os.environ',settings())
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',lambda:client)
    factory=Mock(return_value=fake);monkeypatch.setattr('app.services.purchase_welcome_bootstrap._provider',factory)
    app=create_app()
    with TestClient(app) as http:
        assert app.state.purchase_welcome_runtime_status=='installed'
        service=app.state.purchase_welcome_trigger.dispatcher
        assert service.dispatch(identifier)=='accepted'
        assert service.dispatch(identifier)=='not_dispatched'
        assert http.get('/health').status_code==200
    assert not hasattr(app.state,'purchase_welcome_installation')
    fake.send.assert_called_once()
    monkeypatch.setenv('PURCHASE_WELCOME_SEND_ENABLED','false')
    with TestClient(app):assert not hasattr(app.state,'purchase_welcome_trigger')
    factory.assert_called_once()


def test_bad_public_config_keeps_startup_and_health_working(monkeypatch):
    monkeypatch.setattr('os.environ',{'PURCHASE_WELCOME_SEND_ENABLED':'true'})
    with TestClient(create_app()) as http:assert http.get('/health').status_code==200


def test_real_webhook_background_path_uses_process_audience(selected,monkeypatch):
    client,_,fake=selected
    values=settings();values.update(KIRVANO_WEBHOOK_TOKEN='synthetic-test-token',KIRVANO_WEBHOOK_TIMEZONE='America/Sao_Paulo',EMAIL_IDENTITY_HMAC_SECRET='synthetic-secret')
    # Full fake commit timestamps are Jan 1: authorize that explicit boundary.
    values['PURCHASE_WELCOME_NOT_BEFORE']='2026-01-01T00:00:00Z'
    monkeypatch.setattr('os.environ',values)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',lambda:client)
    monkeypatch.setattr('app.persistence.kirvano_commerce_repository.get_firestore_client',lambda:client)
    monkeypatch.setattr('app.services.purchase_welcome_bootstrap._provider',lambda config:fake)
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**kw:None)
    data=payload();data['sale_id']='synthetic-public-bootstrap-sale';data['customer']['name']='Gabriel Oliveira'
    with TestClient(create_app()) as http:
        headers={'security-token':'synthetic-test-token'}
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
    fake.send.assert_called_once()
    assert 'Olá, Gabriel Oliveira!' in fake.send.call_args.args[0].html
    assert all(v['activation_status']=='pending' for k,v in client.data.items() if k.startswith('users/'))


@pytest.mark.parametrize('field,value',[('project','other-project'),('_database','named'),('_emulator_host','127.0.0.1:8080')])
def test_wrong_client_binding_never_constructs_provider(selected,field,value):
    client,_,fake=selected;setattr(client,field,value);factory=Mock(return_value=fake)
    assert not prepare_public_welcome(create_app(),environ=settings(),client_factory=lambda:client,provider_factory=factory)
    factory.assert_not_called()


def test_sdk_loading_emulator_flag_is_rechecked_before_installation(selected,monkeypatch):
    client,_,fake=selected;factory=Mock(return_value=fake)
    def get_client():
        monkeypatch.setenv('FIRESTORE_EMULATOR_HOST','127.0.0.1:8080')
        return client
    assert not prepare_public_welcome(create_app(),environ=settings(),client_factory=get_client,provider_factory=factory)
    factory.assert_not_called()


def test_general_mode_requires_no_test_credentials_and_stays_explicit(selected):
    client,identifier,fake=selected
    values=settings();values['PURCHASE_WELCOME_AUDIENCE_MODE']='all'
    values.pop('PURCHASE_WELCOME_TEST_RECIPIENT');values.pop('PURCHASE_WELCOME_TEST_AUTHORIZED')
    config=load_purchase_welcome_config(environ=values,env_file=None)
    assert config.audience.mode=='all' and config.audience.recipient is None
    assert config.audience.allows('first@example.com') and config.audience.allows('second@example.com')
    assert not config.audience.allows('invalid')
    assert prepare_public_welcome(create_app(),environ=values,client_factory=lambda:client,provider_factory=lambda _:fake)
    for missing in ('PURCHASE_WELCOME_NOT_BEFORE','PURCHASE_WELCOME_AUDIENCE_MODE'):
        broken={k:v for k,v in values.items() if k!=missing}
        with pytest.raises(WelcomeEmailConfigurationError,match='configuration'):
            load_purchase_welcome_config(environ=broken,env_file=None)
    values.pop('PURCHASE_WELCOME_SEND_ENABLED')
    assert load_purchase_welcome_config(environ=values,env_file=None) is None
