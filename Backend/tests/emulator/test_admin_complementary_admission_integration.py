"""Four-bucket transactions in demo emulator; cleanup EXACT owned HMAC IDs only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock, Barrier
from uuid import uuid4

import pytest
from google.api_core.exceptions import Aborted

from emulator_support import configured_emulator, create_test_client
from test_admin_domain import START
from test_admin_complementary_admission import policy
from app.persistence.admin_admission_repository import AdminAdmissionRepository, AdminAdmissionUnavailable
from app.services.admin_admission_service import AdminAdmissionService

pytestmark = pytest.mark.firestore_emulator


@pytest.fixture(autouse=True)
def emulator_client(monkeypatch):
    # Override the legacy autouse project-wide deletion fixture entirely.
    configured_emulator()
    def forbidden(*a, **k): raise AssertionError('Production or global deletion forbidden')
    monkeypatch.setattr('firebase_admin.initialize_app', forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client', forbidden)
    monkeypatch.setattr('emulator_support.clear_test_emulator', forbidden)
    clients = [create_test_client(), create_test_client()]
    owned, lock = set(), Lock()
    secret = 'synthetic-step83-' + uuid4().hex  # Separate namespace incl aggregate.
    now = [START]
    class Repository(AdminAdmissionRepository):
        def admit(self, identifiers, rule, instant, **options):
            with lock: owned.update(identifiers)
            return super().admit(identifiers, rule, instant, **options)
    def build(index=0, rule=None):
        return AdminAdmissionService(Repository(clients[index]), policy=rule or policy(),
            admission_hmac_secret=secret, clock=lambda: now[0])
    def documents():
        return {key: snap.to_dict() for key in list(owned)
                if (snap := clients[0].collection('auth_throttles').document(key).get(timeout=5)).exists}
    try:
        yield clients, now, build, documents
    finally:
        try:
            for key in owned:
                clients[0].collection('auth_throttles').document(key).delete(timeout=5)
        finally:
            for client in clients: client.close()


def test_four_atomic_documents_shared_identity_and_recovery(emulator_client):
    clients, now, build, documents = emulator_client
    services = [build(), build(1)]
    for i in range(5):
        assert services[i%2].admit_attempt(f'192.0.2.{i+1}', ' OWNER@EXAMPLE.COM ').outcome == 'allowed'
    before = documents()
    assert services[1].admit_attempt('198.51.100.1', 'owner@example.com').outcome == 'limited'
    assert documents() == before
    now[0] += timedelta(seconds=60)
    assert services[1].admit_attempt('198.51.100.1', 'owner@example.com').outcome == 'allowed'
    stored = documents()
    # New origin/pair plus both independent scopes committed at same instant.
    latest = max(d['updated_at'] for d in stored.values())
    latest_ids = [key for key, doc in stored.items() if doc['updated_at'] == latest]
    assert len(latest_ids) == 4
    assert len({clients[0].collection('auth_throttles').document(key).get().update_time for key in latest_ids}) == 1
    assert 'owner@example.com' not in str(stored)


def test_concurrent_instances_share_aggregate_without_oversubscription(emulator_client):
    _, _, build, documents = emulator_client
    services = [build(rule=policy(aggregate=3)), build(1, policy(aggregate=3))]
    barrier = Barrier(6)
    def run(i):
        barrier.wait(timeout=10)
        try:
            return services[i%2].admit_attempt(f'192.0.2.{i+1}', f'user{i}@example.com').outcome
        except AdminAdmissionUnavailable as error:
            nested = error.__context__
            cause = nested.__context__ if isinstance(nested, AdminAdmissionUnavailable) else None
            assert isinstance(cause, Aborted) or (type(cause) is ValueError and isinstance(cause.__cause__, Aborted))
            return 'unavailable'
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, range(6)))
    allowed = results.count('allowed')
    assert allowed <= 3
    assert set(results) <= {'allowed', 'limited', 'unavailable'}
    for i in range(3-allowed):
        assert services[0].admit_attempt(f'198.51.100.{i+1}', f'remaining{i}@example.com').outcome == 'allowed'
    assert services[1].admit_attempt('203.0.113.1', 'victim@example.com').outcome == 'limited'
    aggregate = [d for d in documents().values() if d['scope'] == 'aggregate']
    assert len(aggregate) == 1 and aggregate[0]['credits'] == 0
    assert len(documents()) == 10  # 3 origins, 3 pairs, 3 identities, singleton.


@pytest.mark.parametrize('failure', ['before_commit', 'aborted', 'uncertain'])
def test_transaction_failure_and_uncertain_commit(emulator_client, monkeypatch, failure):
    _, _, build, documents = emulator_client
    service = build()
    if failure == 'uncertain':
        # Execute genuine server commit, then lose acknowledgement to caller.
        from google.cloud.firestore_v1.transaction import Transaction
        original = Transaction._commit
        def lost_ack(tx):
            original(tx)
            raise RuntimeError('synthetic-private-ack')
        monkeypatch.setattr(Transaction, '_commit', lost_ack)
    else:
        original = service.repository._admit
        def fail(*args):
            original(*args)
            if failure == 'aborted': raise Aborted('synthetic-private-contention')
            raise RuntimeError('synthetic-private-before')
        monkeypatch.setattr(service.repository, '_admit', fail)
    with pytest.raises(AdminAdmissionUnavailable) as caught:
        service.admit_attempt('192.0.2.1', 'owner@example.com')
    assert 'synthetic-private' not in str(caught.value)
    assert len(documents()) == (4 if failure == 'uncertain' else 0)
