"""Sizing experiments reuse exact-ID cleanup; NEVER clear the shared emulator."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock

import pytest
from google.cloud.firestore_v1.transaction import Transaction

from test_admin_complementary_admission import policy
from test_admin_complementary_admission_integration import emulator_client

pytestmark = pytest.mark.firestore_emulator


def test_two_administrators_simultaneously_share_aggregate(emulator_client, monkeypatch):
    _, _, build, documents = emulator_client
    services = [build(rule=policy(aggregate=20)), build(1, policy(aggregate=20))]
    barrier = Barrier(2)
    lock = Lock()
    begins = []
    original = Transaction._begin
    def begin(tx,*args,**kwargs):
        with lock: begins.append(1)
        return original(tx,*args,**kwargs)
    monkeypatch.setattr(Transaction,'_begin',begin)
    def run(i):
        barrier.wait(timeout=10)
        return services[i].admit_attempt('192.0.2.1',f'admin{i}@example.com').outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,range(2)))
    assert results == ['allowed','allowed']
    stored = documents()
    assert len(stored) == 6  # One shared origin, two pairs, two identities, one aggregate.
    assert next(d for d in stored.values() if d['scope']=='aggregate')['credits'] == 18*30_000_000
    print(f'two admins: allowed=2; SDK begins={len(begins)} (includes any automatic retries)')


@pytest.mark.parametrize('capacity,allowed', [(10,10),(20,16)])
def test_four_admin_burst_and_targeted_recovery(emulator_client, capacity, allowed):
    _, now, build, documents = emulator_client
    services = [build(rule=policy(aggregate=capacity)),build(1,policy(aggregate=capacity))]
    results = [services[i%2].admit_attempt(f'192.0.2.{i+1}',f'admin{i}@example.com').outcome
               for i in range(4) for _ in range(4)]
    assert results.count('allowed') == allowed
    assert results.count('limited') == 16-allowed
    before=documents()
    if capacity == 10:
        now[0] += timedelta(seconds=29)
        assert services[0].admit_attempt('198.51.100.1','legitimate@example.com').outcome == 'limited'
        assert documents() == before
        now[0] += timedelta(seconds=1)
        assert services[0].admit_attempt('198.51.100.1','legitimate@example.com').outcome == 'allowed'
    print(f'four-admin burst: aggregate={capacity}; allowed={allowed}; limited={16-allowed}')
