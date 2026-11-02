"""Firestore transactions + intercepted HTTP; imported fixture forbids global wipe."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
import copy
import httpx
import pytest
from google.cloud import firestore
from emulator_support import create_test_client
from test_purchase_welcome_integration import emulator_client
from test_welcome_dispatch import configuration, PROVIDER_ID
from app.persistence.kirvano_commerce_repository import commercial_transaction
from app.domain.welcome_email import welcome_intent_id
from app.domain.welcome_dispatch import WelcomeDispatchRecord, WelcomeProviderResult
from app.persistence.welcome_emails_repository import WelcomeEmailsRepository
from app.services.purchase_welcome_dispatch import create_purchase_welcome_dispatch, WelcomeDispatchUnavailable

pytestmark=pytest.mark.firestore_emulator


def prepare_intent(fixture):
    client,prepare,owned=fixture;args=prepare()
    firestore.transactional(commercial_transaction)(client.transaction(),client,*args)
    identifier=welcome_intent_id(args[1].candidate.purchase_id)
    return identifier,client.collection('transactional_emails').document(identifier),args


def test_two_process_equivalents_single_request_and_result(emulator_client):
    client,_,owned=emulator_client;identifier,ref,args=prepare_intent(emulator_client)
    before={r.path:(r.get().to_dict(),r.get().update_time) for r in owned if r.path!=ref.path}
    calls=[];lock=Lock();barrier=Barrier(2)
    def handler(request):
        assert ref.get(timeout=5).to_dict()['status']=='in_progress'
        with lock:calls.append(request)
        return httpx.Response(200,json={'id':PROVIDER_ID})
    second_client=create_test_client()
    services=[create_purchase_welcome_dispatch(firestore_client=connection,config=configuration(),
        transport=httpx.MockTransport(handler)) for connection in (client,second_client)]
    def dispatch(service):
        barrier.wait(timeout=5)
        try:return service.dispatch(identifier)
        except WelcomeDispatchUnavailable:return 'unavailable'  # A failed claim never permits HTTP.
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(dispatch,services))
        assert results.count('accepted')==1 and set(results)<={'accepted','not_dispatched','unavailable'}
        assert len(calls)==1
        saved=WelcomeDispatchRecord.model_validate(ref.get().to_dict())
        assert saved.status=='accepted' and saved.provider_id==PROVIDER_ID
        assert services[1].dispatch(identifier)=='not_dispatched'
        assert before=={r.path:(r.get().to_dict(),r.get().update_time) for r in owned if r.path!=ref.path}
        assert client.collection('users').document(args[3]).get().to_dict()['activation_status']=='pending'
    finally:
        for service in services:service.provider.close()
        second_client.close()


def test_actual_acceptance_then_result_storage_failure_blocks_new_instance(emulator_client,monkeypatch):
    client,_,_=emulator_client;identifier,ref,_=prepare_intent(emulator_client);calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json={'id':PROVIDER_ID})
    first=create_purchase_welcome_dispatch(firestore_client=client,config=configuration(),transport=httpx.MockTransport(handler))
    second=create_purchase_welcome_dispatch(firestore_client=client,config=configuration(),transport=httpx.MockTransport(handler))
    def fail(*a,**k):raise RuntimeError('synthetic lost result')
    monkeypatch.setattr(first.repository,'finish',fail)
    try:
        with pytest.raises(WelcomeDispatchUnavailable):first.dispatch(identifier)
        assert ref.get().to_dict()['status']=='in_progress'
        second.clock=lambda:datetime.now(timezone.utc)+timedelta(days=2)
        assert second.dispatch(identifier)=='not_dispatched' and len(calls)==1
    finally:first.provider.close();second.provider.close()


def test_stale_review_and_attempt_fencing_preserve_snapshot(emulator_client):
    client,_,_=emulator_client;identifier,ref,_=prepare_intent(emulator_client)
    service=create_purchase_welcome_dispatch(firestore_client=client,config=configuration(),
        transport=httpx.MockTransport(lambda r:pytest.fail('No HTTP allowed')))
    now=datetime.now(timezone.utc)
    try:
        reserved=service.repository.reserve(identifier,attempt_id='a'*64,now=now,build_request=service._request)
        original=copy.deepcopy(ref.get().to_dict()['request'])
        other=WelcomeEmailsRepository(client)
        assert other.reserve(identifier,attempt_id='b'*64,now=now,build_request=service._request) is None
        result=WelcomeProviderResult(reason='accepted',provider_id=PROVIDER_ID)
        assert not other.finish(identifier,attempt_id='b'*64,result=result,now=now)
        assert other.review_interrupted(identifier,now=now+timedelta(days=2))
        assert not other.finish(identifier,attempt_id=reserved.attempt_id,result=result,now=now+timedelta(days=2))
        saved=ref.get().to_dict()
        assert saved['status']=='requires_review' and saved['reason']=='interrupted' and saved['request']==original
        assert service.dispatch(identifier)=='not_dispatched'
    finally:service.provider.close()
