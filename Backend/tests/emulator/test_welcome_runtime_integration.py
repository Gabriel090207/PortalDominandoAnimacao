"""Real public/Admin factories, lifecycle, demo Firestore, injected fake provider."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from test_welcome_trigger_integration import scenario
from test_purchase_welcome_integration import emulator_client
from test_welcome_dispatch import configuration, PROVIDER_ID
from test_kirvano_commercial import payload
from app.main import create_app
from app.admin_server import create_app as create_admin_app
from app.domain.welcome_dispatch import WelcomeProviderResult
from app.services.purchase_welcome_runtime import WelcomeRuntimeInstallation
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy
from app.persistence.admin_customers_repository import AdminCustomersRepository

pytestmark=pytest.mark.firestore_emulator


@pytest.fixture
def managed(scenario):
    _,old,args,ref,_,persist,cutoff=scenario
    client=old.dispatcher.repository.client
    client.project='demo-dominando-animacao-test';client._database='(default)';client._emulator_host='127.0.0.1:8080'
    providers=[]
    def factory(config):
        fake=Mock();fake.send.return_value=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
        providers.append(fake)
        return fake
    install=WelcomeRuntimeInstallation(True,configuration(),WelcomeTriggerPolicy(cutoff,True,2),
        client,client.project,factory,True)
    return install,providers,args,ref,persist


def test_factory_webhook_after_commit_and_duplicate(managed):
    install,providers,args,ref,_=managed
    app=create_app(welcome_installation=replace(install,policy=replace(install.policy,recovery_enabled=False)))
    with TestClient(app) as http:
        assert len(providers)==1
        def send(message,**kwargs):
            assert ref.get().to_dict()['status']=='in_progress'
            return WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
        providers[0].send.side_effect=send
        assert http.get('/health').status_code==200
        headers={'security-token':'synthetic-step95-token'}
        assert http.post('/webhooks/kirvano',headers=headers,json=payload()).status_code==200
        assert http.post('/webhooks/kirvano',headers=headers,json=payload()).status_code==200
        assert ref.get().to_dict()['status']=='accepted'
        providers[0].send.assert_called_once()
        customer=AdminCustomersRepository(install.firestore_client).find_by_email(args[1].candidate.email_normalized)
        assert customer.customer_id==args[3] and customer.activation_status=='pending'
    providers[0].close.assert_called_once()


def test_admin_disabled_shares_public_runtime_and_recovers_once(managed):
    install,providers,_,ref,persist=managed;persist(None)
    public=create_app(welcome_installation=install)
    entry=create_admin_app(environ={},env_file=None,public_app=public)
    assert entry.public_app is public
    with TestClient(entry) as http:
        assert http.get('/health').status_code==200 and http.get('/admin/auth/session').status_code==503
    assert len(providers)==1 and ref.get().to_dict()['status']=='accepted'
    providers[0].send.assert_called_once()
    assert not hasattr(public.state,'purchase_welcome_trigger')
    # Simulate next process lifecycle: same durable state, new provider, no resend.
    with TestClient(entry):pass
    assert len(providers)==2
    providers[1].send.assert_not_called()


@pytest.mark.parametrize('state',['in_progress','requires_review','accepted','historical'])
def test_restart_never_reopens_protected_or_historical(managed,state):
    install,providers,_,ref,persist=managed;persist(None)
    from app.persistence.welcome_emails_repository import WelcomeEmailsRepository
    if state=='historical':ref.update({'created_at':install.policy.not_before-timedelta(days=1)})
    else:
        from app.services.purchase_welcome_dispatch import PurchaseWelcomeDispatchService
        dispatcher=PurchaseWelcomeDispatchService(WelcomeEmailsRepository(install.firestore_client),Mock(),install.config)
        now=datetime.now(timezone.utc)
        reserved=dispatcher.repository.reserve(ref.id,attempt_id='a'*64,now=now,build_request=dispatcher._request)
        if state!='in_progress':
            result=WelcomeProviderResult(reason='timeout') if state=='requires_review' else WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
            dispatcher.repository.finish(ref.id,attempt_id=reserved.attempt_id,result=result,now=now)
    before=ref.get().to_dict()
    app=create_app(welcome_installation=install)
    with TestClient(app):pass
    with TestClient(app):pass
    assert ref.get().to_dict()==before and len(providers)==2
    for fake in providers:fake.send.assert_not_called();fake.close.assert_called_once()


@pytest.mark.parametrize('reason',['network','timeout'])
def test_fake_failure_does_not_change_commerce_or_resend_on_restart(managed,reason):
    install,providers,args,ref,_=managed
    def factory(config):
        fake=Mock();fake.send.return_value=WelcomeProviderResult(reason=reason);providers.append(fake);return fake
    install=replace(install,provider_factory=factory,policy=replace(install.policy,recovery_enabled=False))
    app=create_app(welcome_installation=install)
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',headers={'security-token':'synthetic-step95-token'},json=payload()).status_code==200
        assert ref.get().to_dict()['status']=='requires_review'
        client=install.firestore_client
        assert client.collection('purchases').document(args[1].candidate.purchase_id).get().to_dict()['status']=='active'
        assert client.collection('subscriptions').document(args[1].candidate.subscription_id).get().to_dict()['status']=='active'
        assert client.collection('users').document(args[3]).get().to_dict()['activation_status']=='pending'
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',headers={'security-token':'synthetic-step95-token'},json=payload()).status_code==200
    providers[0].send.assert_called_once();providers[1].send.assert_not_called()


@pytest.mark.parametrize('mode',['absent','disabled','incomplete','wrong_project'])
def test_public_factory_without_usable_installation_preserves_pending(managed,mode):
    install,providers,_,ref,_=managed
    if mode=='absent':selected=None
    elif mode=='disabled':selected=replace(install,enabled=False)
    elif mode=='incomplete':selected=replace(install,config=None)
    else:selected=replace(install,expected_project_id='another-project')
    with TestClient(create_app(welcome_installation=selected)) as http:
        assert http.post('/webhooks/kirvano',headers={'security-token':'synthetic-step95-token'},json=payload()).status_code==200
        assert http.get('/health').status_code==200
    assert ref.get().to_dict()['status']=='pending' and providers==[]
