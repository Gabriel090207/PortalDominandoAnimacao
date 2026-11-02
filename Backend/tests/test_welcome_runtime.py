"""Lifecycle installation with synthetic config, injected provider, no Firebase IO."""
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.admin_server import create_app as admin_app
from app.services.purchase_welcome_runtime import WelcomeRuntimeInstallation, prepare_purchase_welcome_runtime
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy, purchase_welcome_lifespan
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError
from app.domain.welcome_dispatch import WelcomeProviderResult
from test_welcome_dispatch import configuration, setup, record, PROVIDER_ID
from test_kirvano_commerce_transaction import prepared
from test_kirvano_commercial import payload
from commerce_fake import Transaction

CUTOFF=datetime(2026,1,1,tzinfo=timezone.utc)


@pytest.fixture
def installation(setup):
    client,_,_=setup
    client.project='synthetic-runtime-project';client._database='(default)';client._emulator_host=None
    provider=Mock();provider.send.return_value=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
    factory=Mock(return_value=provider)
    return WelcomeRuntimeInstallation(True,configuration(),WelcomeTriggerPolicy(CUTOFF),client,
        'synthetic-runtime-project',factory),provider


@pytest.fixture(autouse=True)
def no_real_firebase(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Real Firebase forbidden')
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)


def test_environment_alone_does_not_install(monkeypatch):
    monkeypatch.setenv('PURCHASE_WELCOME_SEND_ENABLED','true')
    monkeypatch.setenv('RESEND_API_KEY','re_synthetic_not_used')
    monkeypatch.setattr('app.config.purchase_welcome.load_purchase_welcome_config',Mock(side_effect=AssertionError('No implicit env')))
    app=create_app()
    with TestClient(app) as http:
        assert http.get('/health').status_code==200
        assert not hasattr(app.state,'purchase_welcome_trigger')
    assert not any(getattr(r,'path','').startswith('/admin') for r in app.routes)


def test_disabled_without_dependencies():
    app=create_app(welcome_installation=WelcomeRuntimeInstallation())
    with TestClient(app) as http:
        assert http.get('/health').status_code==200
        assert app.state.purchase_welcome_runtime_status=='disabled'
        assert not hasattr(app.state,'purchase_welcome_trigger')


@pytest.mark.parametrize('changes',[
    {'config':None},{'policy':None},{'expected_project_id':'different-project'},
    {'expected_project_id':None},{'provider_factory':None},{'enabled':'true'},
    {'allow_emulator':'yes'},
])
def test_invalid_installation_preserves_public_without_provider(installation,changes):
    selected,provider=installation;selected=replace(selected,**changes)
    app=create_app(welcome_installation=selected)
    with TestClient(app) as http:
        assert http.get('/health').status_code==200
        assert app.state.purchase_welcome_runtime_status=='unavailable'
        assert not hasattr(app.state,'purchase_welcome_trigger')
    installation[0].provider_factory.assert_not_called();provider.send.assert_not_called()


@pytest.mark.parametrize('field,value',[('_database','named'),('_emulator_host','127.0.0.1:8080'),('project','another-project')])
def test_wrong_firestore_binding(installation,field,value):
    selected,provider=installation;setattr(selected.firestore_client,field,value)
    with TestClient(create_app(welcome_installation=selected)) as http:assert http.get('/health').status_code==200
    selected.provider_factory.assert_not_called()


def test_valid_installs_only_on_startup_closes_and_can_restart(installation):
    selected,provider=installation;app=create_app(welcome_installation=selected)
    selected.provider_factory.assert_not_called()
    assert app.state.purchase_welcome_runtime_status=='prepared'
    with TestClient(app):
        first=app.state.purchase_welcome_trigger
        assert app.state.purchase_welcome_runtime_status=='installed'
        selected.provider_factory.assert_called_once_with(selected.config)
        with pytest.raises(WelcomeEmailConfigurationError):prepare_purchase_welcome_runtime(app,selected)
    provider.close.assert_called_once_with()
    assert not hasattr(app.state,'purchase_welcome_trigger')
    with TestClient(app):assert app.state.purchase_welcome_trigger is not first
    assert selected.provider_factory.call_count==provider.close.call_count==2
    provider.send.assert_not_called()


def test_duplicate_preparation_rejected(installation):
    selected,_=installation;app=create_app(welcome_installation=selected)
    with pytest.raises(WelcomeEmailConfigurationError):prepare_purchase_welcome_runtime(app,selected)
    selected.provider_factory.assert_not_called()


def test_provider_creation_failure_sanitized(installation,caplog):
    selected,_=installation;selected.provider_factory.side_effect=RuntimeError('synthetic-private-secret')
    app=create_app(welcome_installation=selected)
    with TestClient(app) as http:
        response=http.get('/health')
        assert response.status_code==200 and app.state.purchase_welcome_runtime_status=='unavailable'
        assert 'synthetic-private-secret' not in response.text+caplog.text


def test_admin_wrapper_reuses_public_lifespan_once_without_admin_activation(installation):
    selected,_=installation;public=create_app(welcome_installation=selected)
    entry=admin_app(environ={},env_file=None,public_app=public)
    assert entry.public_app is public
    with TestClient(entry) as http:
        assert http.get('/health').status_code==200
        assert http.get('/admin/auth/session').status_code==503
        selected.provider_factory.assert_called_once()
    assert not any(getattr(r,'path','').startswith('/admin') for r in public.routes)


def test_admin_factory_accepts_explicit_installation(installation):
    selected,_=installation;entry=admin_app(environ={},env_file=None,welcome_installation=selected)
    with TestClient(entry) as http:
        assert http.get('/health').status_code==200 and http.get('/admin').status_code==503
        assert entry.public_app.state.purchase_welcome_runtime_status=='installed'
    selected.provider_factory.assert_called_once()


def test_admin_duplicate_installation_rejected(installation):
    selected,_=installation;public=create_app(welcome_installation=selected)
    with pytest.raises(WelcomeEmailConfigurationError):admin_app(environ={},env_file=None,public_app=public,welcome_installation=selected)


@pytest.mark.anyio
async def test_second_concurrent_lifespan_cannot_install(installation):
    selected,_=installation;app=create_app(welcome_installation=selected)
    async with purchase_welcome_lifespan(app):
        with pytest.raises(WelcomeEmailConfigurationError):
            async with purchase_welcome_lifespan(app):pass
        selected.provider_factory.assert_called_once()


def test_real_webhook_uses_installed_fake_only_after_commit(installation,setup,monkeypatch):
    selected,provider=installation;client,_,_=setup
    data=payload();data['sale_id']='step96-new-sale'
    def persist(data):
        from app.persistence.kirvano_commerce_repository import commercial_transaction
        tx=Transaction(client);result=commercial_transaction(tx,client,*prepared(data),'synthetic-runtime-user')
        tx.commit();return result
    def send(*args,**kwargs):
        assert any(d.get('status')=='in_progress' for k,d in client.data.items() if k.startswith('transactional_emails/'))
        return WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
    provider.send.side_effect=send
    # Commerce fake only supports transactional reads, so adapt the bounded event lookup.
    def pending(event_id,**kwargs):
        return next((k.split('/')[1] for k,d in client.data.items() if k.startswith('transactional_emails/') and d['origin_event_id']==event_id and d['status']=='pending'),None)
    monkeypatch.setattr('app.persistence.welcome_emails_repository.WelcomeEmailsRepository.pending_for_event',lambda self,*a,**kw:pending(*a,**kw))
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-runtime-token')
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setattr('app.api.kirvano.register_event',persist)
    with TestClient(create_app(welcome_installation=selected)) as http:
        headers={'security-token':'synthetic-runtime-token'}
        assert http.post('/webhooks/kirvano',headers=headers,json=data).status_code==200
        assert http.post('/webhooks/kirvano',headers=headers,json=data).status_code==200
        provider.send.assert_called_once()
        users=[v for k,v in client.data.items() if k.startswith('users/')]
        assert len(users)==1 and users[0]['activation_status']=='pending'


@pytest.mark.parametrize('allowed,host,installed',[
    (True,'127.0.0.1:8080',True),(False,'127.0.0.1:8080',False),
    (True,'remote.example:8080',False),(True,None,False),
])
def test_emulator_requires_explicit_demo_loopback_binding(installation,allowed,host,installed):
    selected,_=installation;client=selected.firestore_client
    client.project='demo-dominando-animacao-test';client._emulator_host=host
    selected=replace(selected,expected_project_id=client.project,allow_emulator=allowed)
    app=create_app(welcome_installation=selected)
    with TestClient(app):
        assert (app.state.purchase_welcome_runtime_status=='installed') is installed
    assert selected.provider_factory.called is installed


def test_manual_install_cannot_bypass_prepared_managed_installation(installation):
    from app.services.purchase_welcome_trigger import install_purchase_welcome_trigger
    selected,provider=installation;app=create_app(welcome_installation=selected)
    with pytest.raises(WelcomeEmailConfigurationError):
        install_purchase_welcome_trigger(app,firestore_client=selected.firestore_client,
            config=selected.config,policy=selected.policy,provider=provider)
    selected.provider_factory.assert_not_called()
    assert not hasattr(app.state,'purchase_welcome_trigger')
