"""Real admission transactions, only existing guarded local emulator clients."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta

import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable
from google.cloud.firestore_v1.transaction import Transaction

from emulator_support import create_test_client
from test_admin_domain import START
from test_admin_admission import policy, SECRET, ORIGIN, EMAIL
from app.persistence.admin_admission_repository import AdminAdmissionRepository, AdminAdmissionUnavailable
from app.services.admin_admission_service import AdminAdmissionService

pytestmark = pytest.mark.firestore_emulator


def build(client, clock=lambda: START, rule=None):
    return AdminAdmissionService(AdminAdmissionRepository(client), policy=rule or policy(),
        admission_hmac_secret=SECRET, clock=clock)


def documents(client):
    return {snapshot.id:snapshot.to_dict() for snapshot in client.collection("auth_throttles").stream(timeout=5)}


def test_admission_atomic_limit_and_logical_expiry(emulator_client):
    now = [START]
    service = build(emulator_client, clock=lambda: now[0], rule=policy(1, 1))
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    before = documents(emulator_client)
    assert len(before) == 2
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"
    assert documents(emulator_client) == before
    now[0] += timedelta(seconds=20)
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    snapshots = list(emulator_client.collection("auth_throttles").stream(timeout=5))
    assert snapshots[0].update_time == snapshots[1].update_time
    assert all(value not in str(documents(emulator_client)) for value in (EMAIL, ORIGIN, SECRET))
    assert {item.id for item in emulator_client.collections(timeout=5)} == {"auth_throttles"}


def test_multiple_clients_cannot_oversubscribe(emulator_client):
    second_client = create_test_client()  # Anonymous, loopback, fixed demo guards.
    try:
        services = [build(emulator_client, rule=policy(3, 3)), build(second_client, rule=policy(3, 3))]
        barrier = Barrier(8)
        def attempt(index):
            barrier.wait(timeout=10)
            try: return services[index%2].admit(ORIGIN, EMAIL).outcome
            except AdminAdmissionUnavailable as error:
                storage = error.__context__
                original = storage.__context__ if isinstance(storage, AdminAdmissionUnavailable) else None
                assert isinstance(original, Aborted) or (
                    type(original) is ValueError and isinstance(original.__cause__, Aborted))
                return "unavailable"
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        allowed = outcomes.count("allowed")
        # Contention may fail closed; the SDK does not promise every call succeeds.
        assert 0 <= allowed <= 3
        assert set(outcomes) <= {"allowed", "limited", "unavailable"}
        stored = documents(emulator_client)
        assert len(stored) == (2 if allowed else 0)
        for doc in stored.values():
            unit = doc["policy"]["refill_period_seconds"]*1_000_000
            assert doc["credits"] == (3-allowed)*unit
        # No fairness/liveness promise under contention. Once contention stops,
        # every unused admission must still be available exactly once.
        for _ in range(3-allowed):
            assert services[0].admit(ORIGIN, EMAIL).outcome == "allowed"
        assert services[1].admit(ORIGIN, EMAIL).outcome == "limited"
        assert len(documents(emulator_client)) == 2
        assert all(doc["credits"] == 0 for doc in documents(emulator_client).values())
        assert {item.id for item in emulator_client.collections(timeout=5)} == {"auth_throttles"}
    finally:
        second_client.close()


def test_failure_after_buffering_has_no_partial_consumption(emulator_client, monkeypatch):
    service = build(emulator_client)
    original = service.repository._admit
    def abort(transaction, *args):
        decision = original(transaction, *args)
        assert decision.outcome == "allowed"
        raise Aborted("Synthetic abort before commit")
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "_admit", abort)
        with pytest.raises(AdminAdmissionUnavailable): service.admit(ORIGIN, EMAIL)
    assert documents(emulator_client) == {}
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"


def test_lost_commit_confirmation_does_not_grant_admission(emulator_client, monkeypatch, capsys, caplog):
    service = build(emulator_client)
    original = Transaction._commit
    commits = []
    def lose_response(transaction):
        original(transaction)
        commits.append(True)
        raise ServiceUnavailable("SYNTHETIC_PRIVATE "+EMAIL+SECRET+ORIGIN)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction, "_commit", lose_response)
        with pytest.raises(AdminAdmissionUnavailable) as caught: service.admit(ORIGIN, EMAIL)
    assert commits == [True] and len(documents(emulator_client)) == 2
    assert str(caught.value) == "Administrative admission unavailable."
    output = capsys.readouterr()
    assert all(value not in output.out+output.err+caplog.text+str(caught.value)
               for value in (EMAIL, SECRET, ORIGIN, "SYNTHETIC_PRIVATE"))


def test_approved_policy_limits_refill_and_incompatible_storage(emulator_client):
    from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
    now = [START]
    service = build(emulator_client, clock=lambda: now[0], rule=INITIAL_ADMIN_ADMISSION_POLICY)
    for index in range(10):
        assert service.admit(ORIGIN, f'admin{index // 5}@example.com').outcome == 'allowed'
    before = documents(emulator_client)
    assert service.admit(ORIGIN, 'third@example.com').outcome == 'limited'
    assert service.admit(ORIGIN, 'admin0@example.com').outcome == 'limited'
    assert documents(emulator_client) == before
    now[0] += timedelta(seconds=30, microseconds=-1)
    assert service.admit(ORIGIN, 'third@example.com').outcome == 'limited'
    now[0] += timedelta(microseconds=1)
    assert service.admit(ORIGIN, 'third@example.com').outcome == 'allowed'
    assert service.admit(ORIGIN, 'admin0@example.com').outcome == 'limited'
    now[0] += timedelta(seconds=30)
    assert service.admit(ORIGIN, 'admin0@example.com').outcome == 'allowed'
    before = documents(emulator_client)
    incompatible = build(emulator_client, clock=lambda: now[0])
    with pytest.raises(AdminAdmissionUnavailable): incompatible.admit(ORIGIN, 'admin0@example.com')
    assert documents(emulator_client) == before
