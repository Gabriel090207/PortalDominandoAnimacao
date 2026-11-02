"""Post-commit scheduling and bounded startup recovery, no live infrastructure."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import asyncio
import threading
import pytest
from fastapi import FastAPI, BackgroundTasks
from fastapi.testclient import TestClient
from test_welcome_dispatch import setup, configuration, record, make_service
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import prepared
from commerce_fake import Transaction
from app.domain.states import KirvanoEventState
from app.domain.kirvano_event import ReceiptResult
from app.services.purchase_welcome_trigger import (
    PurchaseWelcomeTrigger, WelcomeTriggerPolicy, schedule_purchase_welcome, purchase_welcome_lifespan,
    install_purchase_welcome_trigger,
)
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError

CUTOFF=datetime(2026,1,1,tzinfo=timezone.utc)


def runtime(dispatcher=None,**kwargs):
    return PurchaseWelcomeTrigger(dispatcher or Mock(),WelcomeTriggerPolicy(CUTOFF,**kwargs))


def receipt(outcome='new',state=KirvanoEventState.RECEIVED):return ReceiptResult('a'*64,state,outcome)


@pytest.mark.parametrize('event,outcome,state,scheduled',[
    ('SALE_APPROVED','new',KirvanoEventState.RECEIVED,True),
    ('SALE_APPROVED','retry',KirvanoEventState.RECEIVED,False),
    ('SALE_APPROVED','new',KirvanoEventState.REVIEW_REQUIRED,False),
    *[(e,'new',KirvanoEventState.RECEIVED,False) for e in ('SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED','SALE_REFUNDED','SALE_CHARGEBACK','UNKNOWN')],
])
def test_schedule_only_new_approved(event,outcome,state,scheduled):
    trigger=runtime();request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(purchase_welcome_trigger=trigger)))
    tasks=Mock();schedule_purchase_welcome(request,tasks,{'event':event},receipt(outcome,state))
    assert tasks.add_task.called is scheduled
    if scheduled:tasks.add_task.assert_called_once_with(trigger.after_event,'a'*64)


def test_missing_trigger_and_scheduling_failure_are_nonfatal():
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    tasks=Mock();schedule_purchase_welcome(request,tasks,payload(),receipt());tasks.add_task.assert_not_called()
    request.app.state.purchase_welcome_trigger=runtime()
    tasks.add_task.side_effect=RuntimeError('private')
    schedule_purchase_welcome(request,tasks,payload(),receipt())


def test_post_event_queries_and_dispatches_with_cutoff():
    trigger=runtime();trigger.dispatcher.repository.pending_for_event.return_value='a'*64
    trigger.after_event('b'*64)
    trigger.dispatcher.dispatch.assert_called_once_with('a'*64,not_before=CUTOFF)
    trigger.dispatcher.repository.pending_for_event.side_effect=RuntimeError('private')
    assert trigger.after_event('b'*64)=='unavailable'


def test_recovery_explicit_finite_and_continues_after_failure():
    trigger=runtime(recovery_enabled=True,batch_size=3)
    trigger.dispatcher.repository.pending_batch.return_value=['a'*64,'b'*64,'c'*64]
    trigger.dispatcher.dispatch.side_effect=['accepted',RuntimeError('private'),'not_dispatched']
    assert trigger.recover_pending()=={'processed':2,'unavailable':1}
    trigger.dispatcher.repository.pending_batch.assert_called_once_with(not_before=CUTOFF,limit=3)
    disabled=runtime();assert disabled.recover_pending()=={'processed':0,'unavailable':0}
    disabled.dispatcher.repository.pending_batch.assert_not_called()


def test_recovery_query_failure_sanitized():
    trigger=runtime(recovery_enabled=True);trigger.dispatcher.repository.pending_batch.side_effect=RuntimeError('private')
    assert trigger.recover_pending()=={'processed':0,'unavailable':1}
    trigger.dispatcher.dispatch.assert_not_called()


@pytest.mark.parametrize('kwargs',[{'not_before':None},{'not_before':datetime(2026,1,1)},
    {'not_before':CUTOFF,'batch_size':0},{'not_before':CUTOFF,'batch_size':21},
    {'not_before':CUTOFF,'batch_size':True},{'not_before':CUTOFF,'recovery_enabled':'true'}])
def test_policy_invalid(kwargs):
    with pytest.raises(WelcomeEmailConfigurationError):WelcomeTriggerPolicy(**kwargs)


def test_cutoff_enforced_inside_claim_even_for_direct_id(setup):
    service=make_service(setup,Mock());_,identifier,_=setup
    assert service.dispatch(identifier,not_before=CUTOFF+timedelta(seconds=1))=='not_dispatched'
    assert record(setup).status=='pending'
    service.provider._client._transport.handler.assert_not_called()


def test_startup_background_recovery_does_not_block_health():
    trigger=runtime(recovery_enabled=True);started=threading.Event();release=threading.Event()
    def recover():started.set();assert release.wait(timeout=5)
    trigger.recover_pending=recover
    app=FastAPI(lifespan=purchase_welcome_lifespan);app.state.purchase_welcome_trigger=trigger
    @app.get('/health')
    def health():return {'status':'ok'}
    with TestClient(app) as http:
        try:
            assert started.wait(timeout=5)
            assert http.get('/health').status_code==200
        finally:release.set()


def test_no_recovery_by_default():
    app=FastAPI(lifespan=purchase_welcome_lifespan);trigger=runtime()
    trigger.recover_pending=Mock();app.state.purchase_welcome_trigger=trigger
    with TestClient(app):pass
    trigger.recover_pending.assert_not_called()


def test_webhook_commit_before_schedule_and_transaction_failure(monkeypatch,setup):
    from app.api.kirvano import router
    from app.persistence.kirvano_commerce_repository import commercial_transaction
    app=FastAPI();app.include_router(router);trigger=runtime();app.state.purchase_welcome_trigger=trigger
    trigger.after_event=Mock()
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-token')
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    client,_,_=setup
    # Distinct sale from the fixture's first purchase.
    data=payload();data['sale_id']='another-trigger-sale'
    def persist(data):
        tx=Transaction(client);result=commercial_transaction(tx,client,*prepared(data),'trigger-user')
        tx.commit();return result
    monkeypatch.setattr('app.api.kirvano.register_event',persist)
    def check(event_id):
        assert client.data['kirvano_events/'+event_id]['business_status']=='applied'
    trigger.after_event.side_effect=check
    with TestClient(app) as http:
        headers={'security-token':'synthetic-token'}
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
        assert trigger.after_event.call_count==1
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==200
        assert trigger.after_event.call_count==1
        monkeypatch.setattr('app.api.kirvano.register_event',Mock(side_effect=RuntimeError('private')))
        assert http.post('/webhooks/kirvano',json=data,headers=headers).status_code==503
        assert trigger.after_event.call_count==1


def test_explicit_configuration_never_enables_without_cutoff():
    from app.services.purchase_welcome_trigger import configure_purchase_welcome_trigger
    from test_welcome_dispatch import env
    import httpx
    app=FastAPI();values=env()
    assert configure_purchase_welcome_trigger(app,firestore_client=Mock(),transport=None,environ={},env_file=None) is None
    with pytest.raises(WelcomeEmailConfigurationError):
        configure_purchase_welcome_trigger(app,firestore_client=Mock(),transport=None,environ=values,env_file=None)
    assert not hasattr(app.state,'purchase_welcome_trigger')
    values.update(PURCHASE_WELCOME_NOT_BEFORE='2026-10-27T00:00:00Z',PURCHASE_WELCOME_RECOVERY_ENABLED='true')
    trigger=configure_purchase_welcome_trigger(app,firestore_client=Mock(),transport=httpx.MockTransport(Mock()),environ=values)
    assert trigger.policy.recovery_enabled and trigger.policy.batch_size==5
    trigger.dispatcher.provider.close()


@pytest.mark.parametrize('field,value',[
    ('PURCHASE_WELCOME_NOT_BEFORE','2026-10-27T00:00:00'),
    ('PURCHASE_WELCOME_NOT_BEFORE','bad'),('PURCHASE_WELCOME_RECOVERY_ENABLED','yes'),
    ('PURCHASE_WELCOME_RECOVERY_BATCH_SIZE','21'),('PURCHASE_WELCOME_RECOVERY_BATCH_SIZE','0'),
])
def test_trigger_configuration_invalid(field,value):
    from app.services.purchase_welcome_trigger import configure_purchase_welcome_trigger
    from test_welcome_dispatch import env
    values=env();values['PURCHASE_WELCOME_NOT_BEFORE']='2026-10-27T00:00:00Z';values[field]=value
    with pytest.raises(WelcomeEmailConfigurationError):
        configure_purchase_welcome_trigger(FastAPI(),firestore_client=Mock(),transport=None,environ=values)
