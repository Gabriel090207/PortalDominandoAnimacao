"""Internal login coordination against the guarded, anonymous local emulator."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.cloud.firestore_v1.transaction import Transaction

from emulator_support import create_test_client
from test_admin_domain import START
from test_admin_admission import policy, SECRET, ORIGIN
from test_admin_auth_integration import seed, service, PASSWORD
from app.persistence.admin_admission_repository import AdminAdmissionRepository, AdminAdmissionUnavailable
from app.services.admin_admission_service import AdminAdmissionService
from app.services.admin_auth_service import InvalidAdminCredentials
from app.services.admin_login_service import AdminLoginService, AdminLoginLimited

pytestmark = pytest.mark.firestore_emulator


def build(client, auth, capacity=1):
    admission = AdminAdmissionService(AdminAdmissionRepository(client), policy=policy(capacity, capacity),
        admission_hmac_secret=SECRET, clock=lambda: START)
    return AdminLoginService(admission, auth)


def buckets(client):
    return {doc.id: doc.to_dict() for doc in client.collection('auth_throttles').stream(timeout=5)}


@pytest.mark.parametrize('role', ['owner', 'operator'])
def test_login_persists_session_and_keeps_budget(emulator_client, role):
    seed(emulator_client, role)
    auth, sessions = service(emulator_client)
    login = build(emulator_client, auth)
    issued = login.authenticate(ORIGIN, ' ADMIN@EXAMPLE.COM ', PASSWORD)
    assert sessions.validate(issued.token.get_secret_value()).role == role
    before = buckets(emulator_client)
    assert len(before) == 2 and all(doc['credits'] == 0 for doc in before.values())
    with pytest.raises(AdminLoginLimited): login.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
    assert buckets(emulator_client) == before
    assert len(list(emulator_client.collection('admin_sessions').stream(timeout=5))) == 1


def test_malformed_email_is_limited_without_session(emulator_client):
    auth, _ = service(emulator_client)
    login = build(emulator_client, auth)
    with pytest.raises(InvalidAdminCredentials): login.authenticate(ORIGIN, 'invalid-one', PASSWORD)
    before = buckets(emulator_client)
    with pytest.raises(AdminLoginLimited): login.authenticate(ORIGIN, 'invalid-two', PASSWORD)
    assert buckets(emulator_client) == before
    assert list(emulator_client.collection('admin_sessions').stream(timeout=5)) == []


def test_lost_admission_confirmation_never_calls_auth(emulator_client, monkeypatch):
    auth = Mock()
    login = build(emulator_client, auth)
    commit = Transaction._commit
    commits = []
    def lose_response(tx):
        commit(tx)
        commits.append(True)
        raise ServiceUnavailable('synthetic uncertain response')
    with monkeypatch.context() as patch:
        patch.setattr(Transaction, '_commit', lose_response)
        with pytest.raises(AdminAdmissionUnavailable): login.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
    assert commits == [True] and len(buckets(emulator_client)) == 2
    auth.authenticate.assert_not_called()
    assert list(emulator_client.collection('admin_sessions').stream(timeout=5)) == []


def test_multiple_instances_only_authenticate_committed_admissions(emulator_client):
    second = create_test_client()
    try:
        auth = Mock()
        services = [build(emulator_client, auth, 3), build(second, auth, 3)]
        barrier = Barrier(6)
        def attempt(index):
            barrier.wait(timeout=10)
            try:
                services[index % 2].authenticate(ORIGIN, 'admin@example.com', PASSWORD)
                return 'allowed'
            except AdminLoginLimited: return 'limited'
            except AdminAdmissionUnavailable: return 'unavailable'
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(attempt, range(6)))
        allowed = outcomes.count('allowed')
        assert 0 <= allowed <= 3
        assert auth.authenticate.call_count == allowed
        stored = buckets(emulator_client)
        assert len(stored) == (2 if allowed else 0)
        for doc in stored.values():
            assert doc['credits'] == (3-allowed)*doc['policy']['refill_period_seconds']*1_000_000
        for _ in range(3-allowed):
            services[0].authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        with pytest.raises(AdminLoginLimited): services[1].authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        assert auth.authenticate.call_count == 3
    finally:
        second.close()
