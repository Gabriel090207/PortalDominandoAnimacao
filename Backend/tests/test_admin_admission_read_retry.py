"""Real SDK runner + scripted transport; strict pre-write retry boundary."""
import copy
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted,PermissionDenied,ServiceUnavailable
from google.cloud.firestore_v1.transaction import transactional as sdk_transactional

from commerce_fake import Ref
from test_admin_admission import admission
from test_admin_complementary_admission import policy
from test_admin_session_transaction_failures import ScriptedSDKTransaction
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from app.services.admin_login_service import AdminLoginService,AdminLoginLimited


@pytest.fixture
def harness(admission,monkeypatch):
    storage,now,build=admission
    service=build(policy(aggregate=20))
    service.clock=Mock(return_value=now[0])
    transactions=[]
    def factory():
        tx=ScriptedSDKTransaction(storage)
        transactions.append(tx)
        return tx
    monkeypatch.setattr(storage,'transaction',factory)
    monkeypatch.setattr('app.persistence.admin_admission_repository.firestore.transactional',sdk_transactional)
    return storage,service,transactions


@pytest.mark.parametrize('position',[1,4])
@pytest.mark.parametrize('persistent',[False,True])
def test_read_aborted_recovers_once_or_stops(harness,monkeypatch,position,persistent,capsys,caplog):
    storage,service,transactions=harness
    reads={};original=Ref.get
    def read(ref,transaction):
        index=transactions.index(transaction)
        reads[index]=reads.get(index,0)+1
        if reads[index]==position and (index==0 or persistent):
            raise Aborted('synthetic-private-read')
        return original(ref,transaction)
    monkeypatch.setattr(Ref,'get',read)
    auth=Mock();sessions=Mock();auth.authenticate.side_effect=lambda *args:sessions.create()
    login=AdminLoginService(service,auth)
    if persistent:
        with pytest.raises(AdminAdmissionUnavailable) as caught:
            login.authenticate('192.0.2.1','admin@example.com','synthetic password')
        assert str(caught.value)=='Administrative admission unavailable.'
        auth.authenticate.assert_not_called();sessions.create.assert_not_called()
        assert storage.data=={}
    else:
        login.authenticate('192.0.2.1','admin@example.com','synthetic password')
        assert auth.authenticate.call_count==sessions.create.call_count==1
        assert len(storage.data)==4
        for doc in storage.data.values():
            rule=doc['policy'];unit=rule['refill_period_seconds']*1_000_000
            assert doc['credits']==(rule['capacity']-1)*unit
        assert reads[1]==4
    assert len(transactions)==2 and transactions[0] is not transactions[1]
    assert transactions[0].commits==0 and transactions[0].rollbacks==1
    assert all(tx.begins==1 for tx in transactions)
    service.clock.assert_called_once_with()
    output=capsys.readouterr()
    assert 'synthetic-private-read' not in output.out+output.err+caplog.text


@pytest.mark.parametrize('error',[PermissionDenied('synthetic-private'),ServiceUnavailable('synthetic-private'),RuntimeError('synthetic-private')])
def test_other_read_failures_never_retry(harness,monkeypatch,error):
    storage,service,transactions=harness
    monkeypatch.setattr(Ref,'get',Mock(side_effect=error))
    with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','admin@example.com')
    assert len(transactions)==1 and transactions[0].commits==0 and storage.data=={}


def test_invalid_identity_does_not_get_extra_read_cycle(harness,monkeypatch):
    storage,service,transactions=harness
    monkeypatch.setattr(Ref,'get',Mock(side_effect=Aborted('synthetic')))
    with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','invalid')
    assert len(transactions)==1 and storage.data=={}


@pytest.mark.parametrize('actions',[[Aborted('synthetic')],[Aborted('synthetic')]*5,
    ['commit_then_lose_response'],[RuntimeError('synthetic')]])
def test_commit_retry_or_uncertainty_stays_in_original_cycle(harness,monkeypatch,actions):
    storage,service,transactions=harness
    tx=ScriptedSDKTransaction(storage,actions)
    factory=Mock(return_value=tx)
    monkeypatch.setattr(storage,'transaction',factory)
    if len(actions)==1 and isinstance(actions[0],Aborted):
        assert service.admit_attempt('192.0.2.1','admin@example.com').outcome=='allowed'
        assert tx.commits==2
    else:
        with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','admin@example.com')
        assert len(storage.data)==(4 if actions==['commit_then_lose_response'] else 0)
    factory.assert_called_once_with()


def test_read_abort_after_previous_commit_attempt_never_restarts_cycle(harness,monkeypatch):
    storage,service,transactions=harness
    tx=ScriptedSDKTransaction(storage,[Aborted('synthetic commit')])
    factory=Mock(return_value=tx)
    monkeypatch.setattr(storage,'transaction',factory)
    original=Ref.get
    def read(ref,transaction):
        if transaction.commits: raise Aborted('synthetic read after attempted commit')
        return original(ref,transaction)
    monkeypatch.setattr(Ref,'get',read)
    with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','admin@example.com')
    factory.assert_called_once_with()
    assert tx.begins==2 and tx.commits==1 and storage.data=={}


def test_aborted_while_buffering_never_gets_outer_retry(harness,monkeypatch):
    storage,service,transactions=harness
    original=ScriptedSDKTransaction.create
    def write(tx,*args):
        original(tx,*args)
        raise Aborted('synthetic buffered-write failure')
    monkeypatch.setattr(ScriptedSDKTransaction,'create',write)
    with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','admin@example.com')
    assert len(transactions)==1 and transactions[0].commits==0 and storage.data=={}


def test_rollback_failure_does_not_get_outer_retry(harness,monkeypatch):
    storage,service,transactions=harness
    monkeypatch.setattr(Ref,'get',Mock(side_effect=Aborted('synthetic read')))
    monkeypatch.setattr(ScriptedSDKTransaction,'_rollback',Mock(side_effect=ServiceUnavailable('synthetic rollback')))
    with pytest.raises(AdminAdmissionUnavailable): service.admit_attempt('192.0.2.1','admin@example.com')
    assert len(transactions)==1 and storage.data=={}


def test_exhausted_buckets_and_config_errors_do_not_retry(harness):
    storage,service,transactions=harness
    login=AdminLoginService(service,Mock())
    for _ in range(5):login.authenticate('192.0.2.1','admin@example.com','synthetic')
    before=copy.deepcopy(storage.data)
    with pytest.raises(AdminLoginLimited):login.authenticate('192.0.2.1','admin@example.com','synthetic')
    assert len(transactions)==6 and storage.data==before
    assert login.auth_service.authenticate.call_count==5
    with pytest.raises(AdminAdmissionUnavailable):service.repository.admit(('bad',),service.policy,service.clock())
    assert len(transactions)==6
