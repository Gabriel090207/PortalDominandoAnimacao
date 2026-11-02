"""Controlled comparisons, no production retry changes; only owned demo buckets."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.document import DocumentReference
from google.cloud.firestore_v1.transaction import Transaction

from app.services.admin_login_service import AdminLoginService,AdminLoginLimited
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from test_admin_complementary_admission import policy
from test_admin_complementary_admission_integration import emulator_client

pytestmark=pytest.mark.firestore_emulator


CASES=[(same_email,same_ip,parallel,0) for same_email in (True,False)
       for same_ip in (True,False) for parallel in (True,False)]
CASES += [(same_email,same_ip,True,19) for same_email in (True,False) for same_ip in (True,False)]


@pytest.mark.parametrize('same_email,same_ip,parallel,prefill',CASES)
def test_comparison_consistency_and_authentication_boundary(emulator_client,same_email,same_ip,parallel,prefill):
    _,_,build,documents=emulator_client
    services=[build(rule=policy(aggregate=20)),build(1,policy(aggregate=20))]
    for i in range(prefill):
        assert services[0].admit_attempt(f'203.0.113.{i+1}',f'prefill{i}@example.com').outcome=='allowed'
    sessions=Mock()
    authentication=Mock()
    authentication.authenticate.side_effect=lambda *args:sessions.create()
    logins=[AdminLoginService(service,authentication) for service in services]
    barrier=Barrier(2) if parallel else None
    errors=[]
    def run(i):
        if barrier:barrier.wait(timeout=10)
        ip='192.0.2.1' if same_ip else f'192.0.2.{i+1}'
        email='same@example.com' if same_email else f'admin{i}@example.com'
        try:
            logins[i].authenticate(ip,email,'synthetic comparison password')
            return 'allowed'
        except AdminLoginLimited:return 'limited'
        except AdminAdmissionUnavailable as error:
            # Do not silently treat every infrastructure error as contention.
            chain=[];seen=set();current=error
            while current is not None and id(current) not in seen:
                seen.add(id(current));chain.append(current)
                current=current.__cause__ or current.__context__
            errors.append(any(isinstance(item,Aborted) for item in chain))
            return 'unavailable'
    if parallel:
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(run,range(2)))
    else:outcomes=[run(0),run(1)]
    allowed=outcomes.count('allowed')
    assert allowed<=min(2,20-prefill)
    assert authentication.authenticate.call_count==sessions.create.call_count==allowed
    stored=documents()
    # Fixed START clock: sum of all debits in EACH scope must equal committed
    # admissions including prefills. No order assumption; no partial debits.
    for scope in ('origin','origin_identity','identity','aggregate'):
        rows=[doc for doc in stored.values() if doc['scope']==scope]
        debit=sum(doc['policy']['capacity']-doc['credits']/(doc['policy']['refill_period_seconds']*1_000_000)
                  for doc in rows)
        assert debit==prefill+allowed
        assert all(0<=doc['credits']<=doc['policy']['capacity']*doc['policy']['refill_period_seconds']*1_000_000 for doc in rows)
    assert all(errors), 'Unexpected admission failure: not identified as Aborted contention'
    if not parallel:assert allowed==min(2,20-prefill)
    print('COMPARISON',{'same_identity':same_email,'same_origin':same_ip,'parallel':parallel,
          'prefill':prefill,'allowed':allowed,'limited':outcomes.count('limited'),'unavailable':outcomes.count('unavailable')})


def test_each_sdk_cycle_stops_on_read_abort_with_one_directed_recovery(emulator_client,monkeypatch):
    _,_,build,documents=emulator_client
    service=build(rule=policy(aggregate=20))
    begins=[];reads=[]
    original_begin=Transaction._begin
    def begin(tx,*args,**kwargs):
        begins.append(tx)
        return original_begin(tx,*args,**kwargs)
    def fail_read(*args,**kwargs):
        reads.append(1)
        raise Aborted('Synthetic isolated bucket-read conflict')
    auth=Mock()
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_begin',begin)
        patch.setattr(DocumentReference,'get',fail_read)
        with pytest.raises(AdminAdmissionUnavailable) as error:
            AdminLoginService(service,auth).authenticate('192.0.2.1','synthetic@example.com','synthetic password')
    assert len(begins)==len(reads)==2  # Two fresh SDK cycles; neither retries the callback internally.
    assert begins[0] is not begins[1]
    auth.authenticate.assert_not_called()
    assert documents()=={}
    chain=[];current=error.value
    while current is not None:
        chain.append(current);current=current.__cause__ or current.__context__
    assert any(isinstance(item,Aborted) for item in chain)
