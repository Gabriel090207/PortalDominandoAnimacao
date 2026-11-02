"""PASSO 84: controlled workloads, existing implementation, no new defaults."""
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.persistence.admin_records import AdminRecord
from test_admin_admission import admission
from test_admin_complementary_admission import policy, attempt
from test_admin_composition import compose, app_for, ORIGIN
from test_admin_sessions import sessions


@pytest.fixture
def login_workload(sessions):
    storage, _ = sessions
    original = storage.data['admins/synthetic-admin']
    records = {}
    for i, role in enumerate(('owner', 'operator', 'operator', 'operator')):
        document = copy.deepcopy(original)
        document.update(admin_id=f'synthetic-sizing-{i}', email_normalized=f'admin{i}@example.com', role=role)
        record = AdminRecord.from_document(document)
        storage.data['admins/'+record.admin_id] = document
        records[record.email_normalized] = record
    now = [datetime.now(timezone.utc)]
    def build(capacity):
        composition = compose(storage, policy=policy(aggregate=capacity), clock=lambda: now[0])
        composition.login_service.auth_service.repository.find_by_email = Mock(side_effect=records.get)
        return composition
    return storage, now, build


def post(http, index, correct=True):
    return http.post('/admin/auth/login', headers={'Origin':ORIGIN, 'X-Admin-Request':'1'},
        json={'email':f'admin{index}@example.com', 'password':
              'synthetic session admin password' if correct else 'incorrect synthetic password'})


@pytest.mark.parametrize('role_index', [0, 1])
def test_normal_owner_and_operator_login(login_workload, role_index):
    _, _, build = login_workload
    composition = build(10)
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        assert post(http, role_index).status_code == 200
        result = http.get('/admin/auth/session', headers={'Origin':ORIGIN})
        assert result.status_code == 200
        assert result.json()['role'] == ('owner' if role_index == 0 else 'operator')


@pytest.mark.parametrize('capacity', [10, 20])
def test_two_admins_same_ip_three_errors_then_success(login_workload, capacity):
    storage, _, build = login_workload
    composition = build(capacity)
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        for index in range(2):
            for _ in range(3): assert post(http, index, correct=False).status_code == 401
            assert post(http, index).status_code == 200
    assert len([p for p in storage.data if p.startswith('admin_sessions/')]) == 2
    aggregate = next(d for d in storage.data.values() if d.get('scope') == 'aggregate')
    assert aggregate['credits'] == (capacity-8)*30_000_000


@pytest.mark.parametrize('capacity,allowed,limited', [(10,10,6), (20,16,0)])
def test_four_admin_burst_from_distinct_origins(admission, capacity, allowed, limited):
    _, _, build = admission
    service = build(policy(aggregate=capacity))
    # Four attempts each (e.g. three errors + success). Admission itself does
    # not distinguish password outcomes. Real password flow tested above.
    results = [attempt(service, f'192.0.2.{i+1}', f'admin{i}@example.com')
               for i in range(4) for _ in range(4)]
    assert results.count('allowed') == allowed
    assert results.count('limited') == limited


def test_shared_nat_still_has_original_ten_attempt_budget(admission):
    _, _, build = admission
    service = build(policy(aggregate=20))
    results = [attempt(service, email=f'admin{i}@example.com') for i in range(4) for _ in range(4)]
    assert results.count('allowed') == 10
    assert results.count('limited') == 6


@pytest.mark.parametrize('capacity', [10,20])
def test_distributed_exhaustion_and_gradual_recovery(admission, capacity):
    storage, now, build = admission
    service = build(policy(aggregate=capacity))
    for i in range(capacity):
        assert attempt(service, f'192.0.2.{i+1}', f'attack{i}@example.com') == 'allowed'
    before = copy.deepcopy(storage.data)
    now[0] += timedelta(seconds=29, microseconds=999999)
    decision = service.admit_attempt('198.51.100.1','legitimate@example.com')
    assert decision.outcome == 'limited' and decision.retry_after_seconds == 1
    assert storage.data == before
    now[0] += timedelta(microseconds=1)
    assert attempt(service, '198.51.100.1','legitimate@example.com') == 'allowed'
    assert attempt(service, '198.51.100.2','other@example.com') == 'limited'
    now[0] += timedelta(seconds=30*capacity)
    results = [attempt(service,f'203.0.113.{i+1}',f'recovered{i}@example.com') for i in range(capacity+1)]
    assert results.count('allowed') == capacity and results[-1] == 'limited'


def test_ongoing_attacker_can_take_each_refilled_global_token(admission):
    _, now, build = admission
    service = build(policy(aggregate=20))
    for i in range(20):
        assert attempt(service,f'192.0.2.{i+1}',f'attack{i}@example.com') == 'allowed'
    for i in range(3):
        now[0] += timedelta(seconds=30)
        assert attempt(service,f'203.0.113.{i+1}',f'continuing{i}@example.com') == 'allowed'
        assert attempt(service,'198.51.100.99','legitimate@example.com') == 'limited'


def test_identity_attack_blocks_valid_password_without_new_session(login_workload):
    storage, _, build = login_workload
    composition = build(20)
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        for _ in range(5): assert post(http,0,correct=False).status_code == 401
        assert post(http,0).status_code == 429
        assert post(http,1).status_code == 200
    assert len([p for p in storage.data if p.startswith('admin_sessions/')]) == 1


def test_repository_read_write_counts_and_no_new_docs_on_denial(admission, monkeypatch):
    from commerce_fake import Ref, Transaction
    storage, _, build = admission
    reads, writes = [], []
    original_get, original_commit = Ref.get, Transaction.commit
    def get(ref, transaction):
        reads.append(ref.path)
        return original_get(ref,transaction)
    def commit(tx):
        writes.extend(tx.writes)
        return original_commit(tx)
    monkeypatch.setattr(Ref,'get',get)
    monkeypatch.setattr(Transaction,'commit',commit)
    service = build(policy(aggregate=1))
    assert attempt(service) == 'allowed'
    assert len(reads) == len(writes) == 4
    reads.clear(); writes.clear()
    before = copy.deepcopy(storage.data)
    assert attempt(service,'198.51.100.1','other@example.com') == 'limited'
    assert len(reads) == 4 and len(writes) == 0
    assert storage.data == before


def test_growth_and_no_automatic_physical_deletion(admission):
    storage, now, build = admission
    service = build(policy(aggregate=20))
    for i in range(20):
        assert attempt(service,f'192.0.2.{i+1}',f'admin{i}@example.com') == 'allowed'
    assert len(storage.data) == 61  # origin + pair + identity per admission, one aggregate
    before = copy.deepcopy(storage.data)
    now[0] += timedelta(days=1)
    assert storage.data == before  # Clock expiry alone deletes nothing.
    assert attempt(service,'198.51.100.1','new@example.com') == 'allowed'
    assert len(storage.data) == 64
