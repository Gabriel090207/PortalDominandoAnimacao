"""Coordinator tests: injected storage, policies and synthetic credentials only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.transaction import transactional as sdk_transactional

from test_admin_admission import admission, policy, ORIGIN, EMAIL, SECRET
from test_admin_auth import setup_auth, encoded, PASSWORD
from test_admin_domain import admin
from test_admin_session_transaction_failures import ScriptedSDKTransaction
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from app.services import admin_auth_service as auth
from app.services import admin_password_service as passwords
from app.services.admin_login_service import AdminLoginService, AdminLoginLimited


@pytest.mark.parametrize('role', ['owner', 'operator'])
def test_success_after_commit_without_reset(admission, setup_auth, encoded, role):
    client, _, build = admission
    authentication, repo, sessions, _ = setup_auth
    repo.find_by_email.return_value = AdminRecord(**admin(role=role).model_dump(), password_hash=encoded)
    def create(administrator):
        assert len(client.data) == 2
        assert administrator.role == role
        return 'synthetic-session'
    sessions.create.side_effect = create
    login = AdminLoginService(build(policy(1, 1)), authentication)
    assert login.authenticate(ORIGIN, ' ADMIN@EXAMPLE.COM ', PASSWORD) == 'synthetic-session'
    repo.find_by_email.assert_called_once_with('admin@example.com')
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminLoginLimited) as caught:
        login.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
    assert caught.value.retry_after_seconds == 20
    assert client.data == before
    assert sessions.create.call_count == repo.find_by_email.call_count == 1


@pytest.mark.parametrize('kind', ['wrong', 'missing', 'disabled', 'invalid'])
def test_credentials_fail_after_consumption(admission, setup_auth, encoded, kind):
    client, _, build = admission
    authentication, repo, sessions, _ = setup_auth
    email, password = EMAIL, PASSWORD
    if kind == 'wrong': password = 'incorrect synthetic password'
    elif kind == 'missing': repo.find_by_email.return_value = None
    elif kind == 'disabled':
        repo.find_by_email.return_value = AdminRecord(**admin(status='disabled').model_dump(), password_hash=encoded)
    else: email = 'invalid'
    with pytest.raises(auth.InvalidAdminCredentials):
        AdminLoginService(build(policy(1, 1)), authentication).authenticate(ORIGIN, email, password)
    assert len(client.data) == 2 and all(doc['credits'] == 0 for doc in client.data.values())
    sessions.create.assert_not_called()
    if kind == 'invalid': repo.find_by_email.assert_not_called()


def test_invalid_emails_share_budget_and_denial_never_runs_argon(admission, setup_auth, monkeypatch):
    client, _, build = admission
    authentication, repo, sessions, _ = setup_auth
    login = AdminLoginService(build(policy(2, 1)), authentication)
    with pytest.raises(auth.InvalidAdminCredentials): login.authenticate(ORIGIN, 'bad-one', PASSWORD)
    before = copy.deepcopy(client.data)
    verify = Mock(side_effect=AssertionError('verification forbidden'))
    monkeypatch.setattr(auth, 'verify_admin_password', verify)
    for email in ('bad-two', None, [], ''):
        with pytest.raises(AdminLoginLimited): login.authenticate(ORIGIN, email, PASSWORD)
    assert client.data == before
    verify.assert_not_called()
    repo.find_by_email.assert_not_called()
    sessions.create.assert_not_called()
    monkeypatch.setattr(auth, 'verify_admin_password', Mock(return_value=True))
    login.authenticate(ORIGIN, EMAIL, PASSWORD)
    with pytest.raises(AdminLoginLimited): login.authenticate(ORIGIN, 'another@example.com', PASSWORD)
    assert len(client.data) == 3
    assert all(value not in str(client.data) for value in ('bad-one', 'bad-two', EMAIL, ORIGIN, SECRET))


@pytest.mark.parametrize('origin', [None, '', '  ', ORIGIN+'\n'])
def test_bad_origin_never_authenticates(admission, setup_auth, monkeypatch, origin):
    client, _, build = admission
    authentication, repo, sessions, _ = setup_auth
    verify = Mock()
    monkeypatch.setattr(auth, 'verify_admin_password', verify)
    with pytest.raises(AdminAdmissionUnavailable):
        AdminLoginService(build(), authentication).authenticate(origin, EMAIL, PASSWORD)
    assert client.data == {}
    repo.find_by_email.assert_not_called()
    sessions.create.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize('failure', ['lookup', 'argon', 'saturation', 'session'])
def test_internal_failure_consumes_and_stays_distinct(admission, setup_auth, monkeypatch, failure, caplog, capsys):
    client, _, build = admission
    authentication, repo, sessions, record = setup_auth
    private = PASSWORD + record.password_hash.get_secret_value() + 'synthetic-token'
    if failure == 'lookup': repo.find_by_email.side_effect = RuntimeError(private)
    elif failure == 'argon': monkeypatch.setattr(auth, 'verify_admin_password', Mock(side_effect=RuntimeError(private)))
    elif failure == 'session': sessions.create.side_effect = RuntimeError(private)
    else: assert passwords._verification_slots.acquire(blocking=False)
    try:
        with pytest.raises(auth.AdminAuthenticationUnavailable) as caught:
            AdminLoginService(build(policy(1, 1)), authentication).authenticate(ORIGIN, EMAIL, PASSWORD)
    finally:
        if failure == 'saturation': passwords._verification_slots.release()
    assert len(client.data) == 2 and all(doc['credits'] == 0 for doc in client.data.values())
    if failure != 'session': sessions.create.assert_not_called()
    output = capsys.readouterr()
    public = str(caught.value)+repr(caught.value)+output.out+output.err+caplog.text
    assert all(value not in public for value in (PASSWORD, record.password_hash.get_secret_value(), 'synthetic-token'))
    assert caught.value.__cause__ is None


@pytest.mark.parametrize('actions', [[RuntimeError('synthetic secret')], [Aborted('contention')]*5,
                                   ['commit_then_lose_response']])
def test_uncertain_or_failed_admission_never_authenticates(admission, monkeypatch, actions):
    client, _, build = admission
    tx = ScriptedSDKTransaction(client, actions)
    factory = Mock(return_value=tx)
    monkeypatch.setattr(client, 'transaction', factory)
    monkeypatch.setattr('app.persistence.admin_admission_repository.firestore.transactional', sdk_transactional)
    authentication = Mock()
    with pytest.raises(AdminAdmissionUnavailable):
        AdminLoginService(build(), authentication).authenticate(ORIGIN, EMAIL, PASSWORD)
    authentication.authenticate.assert_not_called()
    factory.assert_called_once_with()
    assert len(client.data) == (2 if actions == ['commit_then_lose_response'] else 0)


def test_concurrent_coordinators_share_budget(admission):
    client, _, build = admission
    authentication = Mock()  # Admission capacity, independent of Argon2 fairness.
    services = [AdminLoginService(build(policy(3, 3)), authentication) for _ in range(2)]
    def attempt(index):
        try:
            services[index % 2].authenticate(ORIGIN, EMAIL, PASSWORD)
            return 'allowed'
        except AdminLoginLimited: return 'limited'
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count('allowed') == 3 and results.count('limited') == 5
    assert authentication.authenticate.call_count == 3
    assert all(doc['credits'] == 0 for doc in client.data.values())


def test_unexpected_admission_result_fails_closed():
    admission_service, authentication = Mock(), Mock()
    admission_service.admit_attempt.return_value = None
    with pytest.raises(AdminAdmissionUnavailable):
        AdminLoginService(admission_service, authentication).authenticate(ORIGIN, EMAIL, PASSWORD)
    authentication.authenticate.assert_not_called()


def test_lookup_and_argon_only_after_committed_admission(admission, setup_auth, monkeypatch):
    client, _, build = admission
    authentication, repo, sessions, record = setup_auth
    events = []
    def lookup(email):
        assert len(client.data) == 2
        events.append('lookup')
        return record
    def verify(password, encoded_hash):
        assert len(client.data) == 2
        events.append('verify')
        return True
    repo.find_by_email.side_effect = lookup
    monkeypatch.setattr(auth, 'verify_admin_password', verify)
    sessions.create.side_effect = lambda administrator: events.append('session')
    AdminLoginService(build(), authentication).authenticate(ORIGIN, EMAIL, PASSWORD)
    assert events == ['lookup', 'verify', 'session']


def test_attempt_preserves_existing_valid_identity_bucket_ids(admission):
    client, _, build = admission
    service = build(policy(2, 2))
    service.admit(ORIGIN, EMAIL)
    identifiers = set(client.data)
    service.admit_attempt(ORIGIN, ' OWNER@EXAMPLE.COM ')
    assert set(client.data) == identifiers
    assert all(doc['credits'] == 0 for doc in client.data.values())


def test_unexpected_dependency_error_is_sanitized_without_retry(capsys, caplog):
    admission_service, authentication = Mock(), Mock()
    private = PASSWORD + SECRET + EMAIL + ORIGIN + 'synthetic-token'
    admission_service.admit_attempt.side_effect = RuntimeError(private)
    with pytest.raises(AdminAdmissionUnavailable) as caught:
        AdminLoginService(admission_service, authentication).authenticate(ORIGIN, EMAIL, PASSWORD)
    admission_service.admit_attempt.assert_called_once_with(ORIGIN, EMAIL)
    authentication.authenticate.assert_not_called()
    output = capsys.readouterr()
    public = str(caught.value)+repr(caught.value)+output.out+output.err+caplog.text
    assert all(value not in public for value in (PASSWORD, SECRET, EMAIL, ORIGIN, 'synthetic-token'))
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
