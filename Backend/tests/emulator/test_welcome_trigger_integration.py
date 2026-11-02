"""Real webhook/transactions/recovery + HTTP fake, namespace-scoped outbox queries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import Mock
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.cloud import firestore
from test_purchase_welcome_integration import emulator_client
from test_welcome_dispatch import configuration, PROVIDER_ID
from app.api.kirvano import router
from app.persistence.kirvano_commerce_repository import commercial_transaction
from app.domain.welcome_email import welcome_intent_id
from app.persistence.admin_customers_repository import AdminCustomersRepository
from app.services.purchase_welcome_trigger import install_purchase_welcome_trigger, WelcomeTriggerPolicy, purchase_welcome_lifespan

pytestmark=pytest.mark.firestore_emulator


@pytest.fixture
def scenario(emulator_client,monkeypatch):
    base,prepare,owned=emulator_client
    namespace=base.collection('step95_test_namespaces').document(uuid4().hex)
    class ScopedClient:
        def collection(self,name):
            # Recovery MUST NOT discover/dispatch manual Chrome fixtures.
            return namespace.collection(name) if name=='transactional_emails' else base.collection(name)
        def transaction(self):return base.transaction()
    client=ScopedClient();args=prepare();identifier=welcome_intent_id(args[1].candidate.purchase_id)
    ref=client.collection('transactional_emails').document(identifier);owned.append(ref)
    calls=[]
    def http(request):calls.append(request);return httpx.Response(200,json={'id':PROVIDER_ID})
    def persist(_):return firestore.transactional(commercial_transaction)(client.transaction(),client,*args)
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-step95-token')
    monkeypatch.setattr('app.api.kirvano.register_event',persist)
    app=FastAPI(lifespan=purchase_welcome_lifespan);app.include_router(router)
    @app.get('/health')
    def health():return {'status':'ok'}
    cutoff=datetime.now(timezone.utc)
    runtime=install_purchase_welcome_trigger(app,firestore_client=client,config=configuration(),
        policy=WelcomeTriggerPolicy(cutoff,True,2),transport=httpx.MockTransport(http))
    yield app,runtime,args,ref,calls,persist,cutoff
    runtime.dispatcher.provider.close()


def test_postcommit_webhook_dispatch_and_duplicate(scenario):
    app,runtime,args,ref,calls,_,_=scenario
    from test_kirvano_commercial import payload
    with TestClient(app) as http:
        headers={'security-token':'synthetic-step95-token'}
        assert http.post('/webhooks/kirvano',json=payload(),headers=headers).status_code==200
        assert ref.get().to_dict()['status']=='accepted' and len(calls)==1
        assert http.post('/webhooks/kirvano',json=payload(),headers=headers).status_code==200
        assert len(calls)==1 and http.get('/health').status_code==200
        user=AdminCustomersRepository(runtime.dispatcher.repository.client).find_by_email(args[1].candidate.email_normalized)
        assert user.customer_id==args[3] and user.activation_status=='pending'


def test_lost_background_task_recovered_on_startup(scenario,monkeypatch):
    app,runtime,args,ref,calls,persist,_=scenario
    persist(None) # Commit, then simulate process interruption before task execution.
    assert ref.get().to_dict()['status']=='pending' and calls==[]
    with TestClient(app):pass # finite startup recovery is awaited at lifespan exit
    assert ref.get().to_dict()['status']=='accepted' and len(calls)==1
    assert runtime.recover_pending()['processed']==0 and len(calls)==1


def test_schedule_failure_does_not_change_ack_then_recovery(scenario,monkeypatch):
    app,runtime,_,ref,calls,_,_=scenario
    # Disable startup recovery for this request so scheduling failure stays visible.
    runtime.policy=WelcomeTriggerPolicy(runtime.policy.not_before,False,2)
    def fail(*a,**k):raise RuntimeError('synthetic schedule failure')
    monkeypatch.setattr('starlette.background.BackgroundTasks.add_task',fail)
    from test_kirvano_commercial import payload
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=payload(),headers={'security-token':'synthetic-step95-token'}).status_code==200
    assert calls==[] and ref.get().to_dict()['status']=='pending'
    runtime.policy=WelcomeTriggerPolicy(runtime.policy.not_before,True,2)
    assert runtime.recover_pending()['processed']==1 and len(calls)==1


@pytest.mark.parametrize('state',['in_progress','accepted','requires_review','historical'])
def test_recovery_excludes_nonpending_and_historical(scenario,state):
    app,runtime,_,ref,calls,persist,cutoff=scenario;persist(None)
    if state=='historical':ref.update({'created_at':cutoff-timedelta(days=1)})
    else:
        repo=runtime.dispatcher.repository
        reserved=repo.reserve(ref.id,attempt_id='a'*64,now=datetime.now(timezone.utc),build_request=runtime.dispatcher._request)
        if state!='in_progress':
            from app.domain.welcome_dispatch import WelcomeProviderResult
            result=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID) if state=='accepted' else WelcomeProviderResult(reason='timeout')
            repo.finish(ref.id,attempt_id=reserved.attempt_id,result=result,now=datetime.now(timezone.utc))
    before=ref.get().to_dict()
    assert runtime.recover_pending()['processed']==0 and calls==[]
    assert ref.get().to_dict()==before


def test_recoveries_and_quick_trigger_race_single_send(scenario):
    _,runtime,args,ref,calls,persist,_=scenario;persist(None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(runtime.recover_pending),pool.submit(runtime.after_event,args[0].logical_id)]
        for job in jobs:job.result()
    assert ref.get().to_dict()['status']=='accepted' and len(calls)==1


@pytest.mark.parametrize('failure',['network','timeout'])
def test_provider_failure_not_retried(scenario,failure):
    _,runtime,args,ref,calls,persist,_=scenario;persist(None)
    def fail(request):
        calls.append(request)
        raise (httpx.ReadTimeout if failure=='timeout' else httpx.ConnectError)('private')
    runtime.dispatcher.provider._client._transport=httpx.MockTransport(fail)
    runtime.after_event(args[0].logical_id)
    assert ref.get().to_dict()['status']=='requires_review' and len(calls)==1
    runtime.recover_pending();runtime.after_event(args[0].logical_id)
    assert len(calls)==1


def test_recovery_batch_is_bounded_without_global_scan(scenario,emulator_client):
    _,runtime,_,_,calls,_,_=scenario
    _,prepare,owned=emulator_client;client=runtime.dispatcher.repository.client
    refs=[]
    for _ in range(3):
        args=prepare();identifier=welcome_intent_id(args[1].candidate.purchase_id)
        ref=client.collection('transactional_emails').document(identifier);owned.append(ref);refs.append(ref)
        firestore.transactional(commercial_transaction)(client.transaction(),client,*args)
    assert runtime.recover_pending()=={'processed':2,'unavailable':0}
    assert len(calls)==2 and sum(r.get().to_dict()['status']=='pending' for r in refs)==1
    assert runtime.recover_pending()=={'processed':1,'unavailable':0} and len(calls)==3


def test_without_installed_trigger_commerce_stays_pending(scenario):
    app,runtime,_,ref,calls,_,_=scenario
    del app.state.purchase_welcome_trigger
    from test_kirvano_commercial import payload
    with TestClient(app) as http:
        assert http.post('/webhooks/kirvano',json=payload(),headers={'security-token':'synthetic-step95-token'}).status_code==200
        assert http.get('/health').status_code==200
    assert calls==[] and ref.get().to_dict()['status']=='pending'
