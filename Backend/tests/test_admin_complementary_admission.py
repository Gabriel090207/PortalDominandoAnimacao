"""Explicit synthetic complementary budgets; no production configuration."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted
from pydantic import ValidationError

from app.domain.admin_admission import ComplementaryAdminAdmissionPolicy, BucketPolicy
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from app.services.admin_login_service import AdminLoginService, AdminLoginLimited
from app.services.admin_auth_service import InvalidAdminCredentials
from test_admin_admission import admission
from test_admin_session_transaction_failures import ScriptedSDKTransaction
from google.cloud.firestore_v1.transaction import transactional as sdk_transactional


def policy(identity=5, aggregate=10):
    return ComplementaryAdminAdmissionPolicy(**INITIAL_ADMIN_ADMISSION_POLICY.model_dump(),
        identity=BucketPolicy(capacity=identity, refill_tokens=1, refill_period_seconds=60),
        aggregate=BucketPolicy(capacity=aggregate, refill_tokens=1, refill_period_seconds=30))


def attempt(service, origin='192.0.2.1', email='owner@example.com'):
    return service.admit_attempt(origin, email).outcome


def test_explicit_only_and_old_documents_unchanged(admission):
    storage, _, build = admission
    original = build(INITIAL_ADMIN_ADMISSION_POLICY)
    assert attempt(original) == 'allowed'
    before = copy.deepcopy(storage.data)
    complementary = build(policy())
    assert attempt(complementary) == 'allowed'
    assert len(storage.data) == 4
    for path, doc in before.items():
        assert storage.data[path]['scope'] == doc['scope']
        assert storage.data[path]['policy'] == doc['policy']
        assert storage.data[path]['credits'] == doc['credits'] - doc['policy']['refill_period_seconds']*1_000_000
    assert len(original.policy.bucket_rules) == 2


@pytest.mark.parametrize('variant', ['same', 'different', 'forged_cf', 'case'])
def test_identity_budget_independent_of_origin(admission, variant):
    storage, _, build = admission
    service = build(policy())
    for i in range(5):
        ip = '192.0.2.1' if variant == 'same' else f'192.0.2.{i+1}'
        if variant == 'forged_cf':
            from app.api.admin_origin import resolve_cf_connecting_ip
            ip = resolve_cf_connecting_ip([(b'cf-connecting-ip', ip.encode())])
        assert attempt(service, ip, ' OWNER@EXAMPLE.COM ' if variant == 'case' else 'owner@example.com') == 'allowed'
    before = copy.deepcopy(storage.data)
    assert attempt(service, '198.51.100.99') == 'limited'
    assert storage.data == before


def test_many_emails_and_origins_hit_aggregate_without_partial_writes(admission):
    storage, now, build = admission
    service = build(policy())
    for i in range(10):
        assert attempt(service, f'192.0.2.{i+1}', f'admin{i}@example.com') == 'allowed'
    before = copy.deepcopy(storage.data)
    assert attempt(service, '198.51.100.1', 'victim@example.com') == 'limited'
    assert storage.data == before  # No new identity/origin documents on denial.
    now[0] += timedelta(seconds=29)
    assert attempt(service, '198.51.100.1', 'victim@example.com') == 'limited'
    now[0] += timedelta(seconds=1)
    assert attempt(service, '198.51.100.1', 'victim@example.com') == 'allowed'
    assert attempt(service, '198.51.100.2', 'other@example.com') == 'limited'


def test_identity_targeted_denial_recovers_without_status_changes(admission):
    storage, now, build = admission
    service = build(policy())
    for i in range(5):
        assert attempt(service, f'192.0.2.{i+1}') == 'allowed'
    assert attempt(service, '198.51.100.1') == 'limited'  # Victim also blocked.
    assert attempt(service, '198.51.100.1', 'another@example.com') == 'allowed'
    now[0] += timedelta(seconds=59)
    assert attempt(service, '198.51.100.2') == 'limited'
    now[0] += timedelta(seconds=1)
    assert attempt(service, '198.51.100.2') == 'allowed'
    now[0] += timedelta(hours=1)
    for i in range(5):
        assert attempt(service, f'203.0.113.{i+1}') == 'allowed'
    assert attempt(service, '203.0.113.99') == 'limited'
    assert all(path.startswith('auth_throttles/') for path in storage.data)


def test_invalid_identities_share_bounded_independent_budget(admission):
    storage, _, build = admission
    service = build(policy(identity=2))
    assert attempt(service, email='bad-one') == 'allowed'
    assert attempt(service, '192.0.2.2', 'bad-two') == 'allowed'
    before = copy.deepcopy(storage.data)
    assert attempt(service, '192.0.2.3', 'bad-three') == 'limited'
    assert storage.data == before
    assert len([d for d in storage.data.values() if d['scope'] == 'identity']) == 1


def test_original_origin_budget_remains_required(admission):
    _, _, build = admission
    service = build(policy(aggregate=20))
    for i in range(10):
        assert attempt(service, email=f'admin{i}@example.com') == 'allowed'
    assert attempt(service, email='other@example.com') == 'limited'


def test_multiple_service_instances_and_concurrent_identities(admission):
    storage, _, build = admission
    services = [build(policy()), build(policy())]
    def run(i):
        return attempt(services[i%2], f'192.0.2.{i+1}', f'admin{i}@example.com')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(24)))
    assert results.count('allowed') == 10
    assert results.count('limited') == 14
    aggregate = [d for d in storage.data.values() if d['scope'] == 'aggregate']
    assert len(aggregate) == 1 and aggregate[0]['credits'] == 0


@pytest.mark.parametrize('kind', ['outage', 'before_commit', 'exhausted', 'uncertain'])
def test_failures_never_authenticate(admission, monkeypatch, kind):
    storage, _, build = admission
    service = build(policy())
    if kind == 'outage':
        monkeypatch.setattr(storage, 'transaction', Mock(side_effect=RuntimeError('synthetic-private')))
    elif kind == 'before_commit':
        original = service.repository._admit
        def fail(*args):
            original(*args)
            raise RuntimeError('synthetic-private')
        monkeypatch.setattr(service.repository, '_admit', fail)
    else:
        actions = [Aborted('synthetic-private')]*5 if kind == 'exhausted' else ['commit_then_lose_response']
        tx = ScriptedSDKTransaction(storage, actions)
        monkeypatch.setattr(storage, 'transaction', lambda: tx)
        monkeypatch.setattr('app.persistence.admin_admission_repository.firestore.transactional', sdk_transactional)
    authentication = Mock()
    with pytest.raises(AdminAdmissionUnavailable) as error:
        AdminLoginService(service, authentication).authenticate('192.0.2.1', 'owner@example.com', 'synthetic-password')
    authentication.authenticate.assert_not_called()
    assert 'synthetic-private' not in str(error.value)
    assert len(storage.data) == (4 if kind == 'uncertain' else 0)


def test_generic_credentials_and_limited_before_password(admission, caplog, capsys):
    storage, _, build = admission
    authentication = Mock()
    authentication.authenticate.side_effect = InvalidAdminCredentials()
    login = AdminLoginService(build(policy(identity=1)), authentication)
    with pytest.raises(InvalidAdminCredentials):
        login.authenticate('192.0.2.1', 'missing@example.com', 'synthetic-password')
    with pytest.raises(AdminLoginLimited):
        login.authenticate('192.0.2.2', ' MISSING@EXAMPLE.COM ', 'synthetic-password')
    assert authentication.authenticate.call_count == 1
    assert not any(p.startswith('admin_sessions/') for p in storage.data)
    out = capsys.readouterr()
    assert out.out == out.err == caplog.text == ''
    assert all(s not in str(storage.data) for s in ['missing@example.com', '192.0.2.1', 'synthetic-password'])


@pytest.mark.parametrize('field', ['identity', 'aggregate'])
@pytest.mark.parametrize('value', [None, {'capacity': 0, 'refill_tokens': 1, 'refill_period_seconds': 30},
    {'capacity': 5, 'refill_tokens': -1, 'refill_period_seconds': 30}])
def test_explicit_valid_configuration_required(field, value):
    settings = policy().model_dump()
    settings[field] = value
    with pytest.raises(ValidationError): ComplementaryAdminAdmissionPolicy(**settings)


def test_incompatible_persisted_policy_fails_closed(admission):
    storage, _, build = admission
    assert attempt(build(policy())) == 'allowed'
    before = copy.deepcopy(storage.data)
    with pytest.raises(AdminAdmissionUnavailable): attempt(build(policy(identity=6)))
    assert storage.data == before


def test_recoverable_sdk_conflict_consumes_exactly_once(admission, monkeypatch):
    storage, _, build = admission
    tx = ScriptedSDKTransaction(storage, [Aborted('synthetic-conflict'), None])
    monkeypatch.setattr(storage, 'transaction', lambda: tx)
    monkeypatch.setattr('app.persistence.admin_admission_repository.firestore.transactional', sdk_transactional)
    assert attempt(build(policy())) == 'allowed'
    assert tx.commits == 2
    assert len(storage.data) == 4
    for doc in storage.data.values():
        unit = doc['policy']['refill_period_seconds']*1_000_000
        assert doc['credits'] == (doc['policy']['capacity']-1)*unit


def test_partial_failure_preserves_preexisting_budgets(admission, monkeypatch):
    storage, _, build = admission
    service = build(policy())
    assert attempt(service) == 'allowed'
    before = copy.deepcopy(storage.data)
    original = service.repository._admit
    def fail(*args):
        original(*args)
        raise RuntimeError('synthetic-before-commit')
    monkeypatch.setattr(service.repository, '_admit', fail)
    with pytest.raises(AdminAdmissionUnavailable): attempt(service)
    assert storage.data == before


def test_complementary_composition_real_login_and_logout(sessions):
    from fastapi.testclient import TestClient
    from app.persistence.admin_records import AdminRecord
    from test_admin_composition import compose, app_for, ORIGIN
    storage, _ = sessions
    composition = compose(storage, policy=policy())
    assert isinstance(composition.admission_service.policy, ComplementaryAdminAdmissionPolicy)
    record = AdminRecord.from_document(storage.data['admins/synthetic-admin'])
    composition.login_service.auth_service.repository.find_by_email = Mock(return_value=record)
    h = {'Origin': ORIGIN, 'X-Admin-Request': '1'}
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        response = http.post('/admin/auth/login', headers=h,
            json={'email':'admin@example.com', 'password':'synthetic session admin password'})
        assert response.status_code == 200
        assert len([d for p,d in storage.data.items() if p.startswith('auth_throttles/')]) == 4
        assert http.get('/admin/auth/session', headers=h).status_code == 200
        assert http.post('/admin/auth/logout', headers=h).status_code == 200
        assert http.get('/admin/auth/session', headers=h).status_code == 401


from test_admin_sessions import sessions  # Existing isolated fixture, no real DB.


def test_concurrent_rotating_origins_do_not_oversubscribe_identity(admission):
    _, _, build = admission
    services = [build(policy()), build(policy())]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: attempt(services[i%2], f'192.0.2.{i+1}'), range(12)))
    assert results.count('allowed') == 5
    assert results.count('limited') == 7


def test_complementary_policy_still_requires_network_origin(admission):
    storage, _, build = admission
    with pytest.raises(AdminAdmissionUnavailable): attempt(build(policy()), origin='')
    assert storage.data == {}
