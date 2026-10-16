"""Real installed SDK retry runner, scripted commits, no RPC or Firebase.

Only transport/transaction primitives are simulated. Production repository and
service callbacks run unchanged. Only revocation has bounded outer retries.
"""
import copy
from unittest.mock import Mock
import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable, PermissionDenied
from google.cloud.firestore_v1.transaction import transactional as sdk_transactional

from commerce_fake import Transaction
from test_admin_domain import admin, START
from test_admin_sessions import sessions, token_of  # Reuse isolated fixture.
from app.persistence.admin_sessions_repository import AdminSessionStorageError
from app.persistence import admin_sessions_repository as repository_module
from app.services.admin_session_service import AdminSessionServiceError


class ScriptedSDKTransaction(Transaction):
    _read_only = False
    _max_attempts = 5

    def __init__(self, client, actions=(), before_callback=None):
        super().__init__(client)
        self.actions = iter(actions)
        self.before_callback = before_callback
        self.commits = self.begins = self.rollbacks = 0
        self._id = None

    def _clean_up(self):
        self.writes = []
        self._id = None

    def _begin(self, retry_id=None):
        self.begins += 1
        self._id = b"synthetic-transaction"
        if self.before_callback is not None:
            raise self.before_callback

    def _commit(self):
        self.commits += 1
        action = next(self.actions, None)
        if isinstance(action, Exception):
            raise action  # No server commit occurred in this scripted case.
        super().commit()
        if action == "commit_then_lose_response":
            raise ServiceUnavailable("synthetic private commit response")
        self._clean_up()

    def _rollback(self):
        self.rollbacks += 1
        # Cannot undo an already committed server-side change.
        self._clean_up()


@pytest.fixture
def harness(sessions, monkeypatch):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    original = copy.deepcopy(client.data)
    constructed = []
    monkeypatch.setattr(repository_module, "_wait_before_revocation_retry", Mock())

    def configure(actions=(), before_callback=None, plans=None):
        sequence = iter(plans) if plans is not None else None
        def factory():
            selected_actions, selected_before = next(sequence) if sequence is not None else (actions, before_callback)
            tx = ScriptedSDKTransaction(client, selected_actions, selected_before)
            constructed.append(tx)
            return tx
        monkeypatch.setattr(client, "transaction", factory)
        monkeypatch.setattr("app.persistence.admin_sessions_repository.firestore.transactional", sdk_transactional)
    return client, service, token, original, constructed, configure


def assert_safe(error, token, original, capsys, caplog):
    output = capsys.readouterr()
    public = str(error) + repr(error) + output.out + output.err + caplog.text
    sensitive = [token, "SYNTHETIC_PRIVATE", "synthetic private commit response", str(original)]
    sensitive += [document["password_hash"] for path, document in original.items() if path.startswith("admins/")]
    assert all(secret not in public for secret in sensitive)
    assert error.__cause__ is None and error.__suppress_context__


@pytest.mark.parametrize("layer", ["repository", "service"])
def test_aborted_before_callback_is_failure_not_logout(harness, layer, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    configure(before_callback=Aborted("SYNTHETIC_PRIVATE " + token))
    expected = AdminSessionStorageError if layer == "repository" else AdminSessionServiceError
    with pytest.raises(expected) as caught:
        if layer == "repository":
            from app.services.admin_session_service import _digest
            service.repository.revoke(_digest(token), now=START, reason="logout")
        else:
            service.revoke(token, now=START)
    assert len(transactions) == 3
    assert all(tx.begins == 1 and tx.commits == 0 for tx in transactions)
    assert repository_module._wait_before_revocation_retry.call_count == 2
    assert client.data == original
    assert_safe(caught.value, token, original, capsys, caplog)


def test_aborted_commit_is_recovered_by_sdk_not_outer_retry(harness):
    client, service, token, _, transactions, configure = harness
    configure([Aborted("Synthetic conflict")])
    assert service.revoke(token, now=START, reason="manual_revocation") is True
    assert len(transactions) == 1
    assert transactions[0].commits == transactions[0].begins == 2
    assert transactions[0].rollbacks == 0
    configure()
    session = service.get_session(token)
    assert session.revoked_at == START and session.revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None


@pytest.mark.parametrize("layer", ["repository", "service"])
def test_five_aborted_commits_exhaust_sdk_and_preserve_active_session(harness, layer, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    conflict = Aborted("SYNTHETIC_PRIVATE " + token)
    configure([conflict]*5)
    expected = AdminSessionStorageError if layer == "repository" else AdminSessionServiceError
    with pytest.raises(expected) as caught:
        if layer == "repository":
            from app.services.admin_session_service import _digest
            service.repository.revoke(_digest(token), now=START, reason="logout")
        else:
            service.revoke(token, now=START)
    assert len(transactions) == 3 and len({id(tx) for tx in transactions}) == 3
    assert all(tx.begins == tx.commits == 5 and tx.rollbacks == 1 for tx in transactions)
    assert repository_module._wait_before_revocation_retry.call_count == 2
    # Inspect types only: suppressed contexts must never be emitted to operators.
    storage_error = caught.value if layer == "repository" else caught.value.__context__
    exhausted = storage_error.__context__
    assert type(exhausted) is ValueError
    assert exhausted.__cause__ is conflict
    assert client.data == original
    assert_safe(caught.value, token, original, capsys, caplog)
    configure()
    assert service.validate(token, now=START) == admin()  # Failure != logout.
    assert service.get_session(token).revoked_at is None


def test_callback_failure_after_buffering_does_not_partially_revoke(harness, monkeypatch, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    configure()
    original_callback = service.repository._revoke
    def fail(transaction, *args):
        original_callback(transaction, *args)
        assert len(transaction.writes) == 1
        raise RuntimeError("SYNTHETIC_PRIVATE " + token + str(original))
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "_revoke", fail)
        with pytest.raises(AdminSessionServiceError) as caught:
            service.revoke(token, now=START)
    assert transactions[0].commits == 0 and transactions[0].rollbacks == 1
    assert client.data == original
    assert_safe(caught.value, token, original, capsys, caplog)


@pytest.mark.parametrize("committed", [False, True])
def test_unavailable_response_is_not_logout_confirmation(harness, committed, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    configure(["commit_then_lose_response" if committed else ServiceUnavailable("SYNTHETIC_PRIVATE " + token)])
    with pytest.raises(AdminSessionServiceError) as caught:
        service.revoke(token, now=START, reason="manual_revocation")
    assert len(transactions) == 1 and transactions[0].commits == 1
    repository_module._wait_before_revocation_retry.assert_not_called()
    assert_safe(caught.value, token, original, capsys, caplog)
    configure()
    session = service.get_session(token)
    if committed:
        assert session.revoked_at == START and session.revocation_reason == "manual_revocation"
        assert service.validate(token, now=START) is None
        assert service.revoke(token, now=START, reason="logout") is False
        assert service.get_session(token) == session
    else:
        assert client.data == original and session.revoked_at is None
        assert service.validate(token, now=START) == admin()


def test_failed_attempt_on_already_revoked_session_preserves_provenance(harness, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    configure()
    assert service.revoke(token, now=START, reason="manual_revocation")
    revoked = copy.deepcopy(client.data)
    configure([Aborted("SYNTHETIC_PRIVATE " + token)]*5)
    # Even a read-only/no-write callback in a read-write transaction has a commit.
    with pytest.raises(AdminSessionServiceError) as caught:
        service.revoke(token, now=START, reason="credentials_changed")
    assert client.data == revoked
    assert_safe(caught.value, token, original, capsys, caplog)
    configure()
    assert service.get_session(token).revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None


@pytest.mark.parametrize("kind", ["aborted", "sdk_exhaustion"])
def test_outer_contention_retry_uses_new_transaction_and_fixed_inputs(harness, kind):
    _, service, token, _, transactions, configure = harness
    conflict = Aborted("Synthetic contention")
    first = ([], conflict) if kind == "aborted" else ([conflict]*5, None)
    configure(plans=[first, ([], None)])
    def wait_after_rollback(retry_number):
        assert retry_number == 0 and len(transactions) == 1
        assert transactions[0].rollbacks == 1
        assert transactions[0]._id is None and transactions[0].writes == []
    repository_module._wait_before_revocation_retry.side_effect = wait_after_rollback
    assert service.revoke(token, now=START, reason="manual_revocation") is True
    assert len(transactions) == 2 and transactions[0] is not transactions[1]
    assert transactions[0].commits == (0 if kind == "aborted" else 5)
    assert transactions[1].commits == 1
    repository_module._wait_before_revocation_retry.assert_called_once_with(0)
    configure()
    session = service.get_session(token)
    assert session.revoked_at == START and session.revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None


def test_revocation_without_conflict_needs_one_execution_and_no_wait(harness):
    client, service, token, _, transactions, configure = harness
    configure()
    assert service.revoke(token, now=START) is True
    assert len(transactions) == 1 and transactions[0].commits == 1
    repository_module._wait_before_revocation_retry.assert_not_called()
    before = copy.deepcopy(client.data)
    assert service.revoke(token, now=START, reason="manual_revocation") is False
    assert len(transactions) == 2 and client.data == before
    repository_module._wait_before_revocation_retry.assert_not_called()


@pytest.mark.parametrize("failure", [ValueError("SYNTHETIC_PRIVATE"),
    PermissionDenied("SYNTHETIC_PRIVATE"), RuntimeError("SYNTHETIC_PRIVATE"),
    ServiceUnavailable("SYNTHETIC_PRIVATE")])
def test_noncontention_commit_error_never_retries(harness, failure, capsys, caplog):
    client, service, token, original, transactions, configure = harness
    configure([failure])
    with pytest.raises(AdminSessionServiceError) as caught:
        service.revoke(token, now=START)
    assert len(transactions) == 1 and transactions[0].commits == 1
    repository_module._wait_before_revocation_retry.assert_not_called()
    assert client.data == original
    assert_safe(caught.value, token, original, capsys, caplog)


def test_retry_sees_other_completed_revocation_and_preserves_it(harness, monkeypatch):
    client, service, token, _, transactions, configure = harness
    configure(plans=[([Aborted("Synthetic")]*5, None), ([], None)])
    # Another caller commits between the exhausted transaction and the retry.
    def concurrent_winner(retry_number):
        path = next(path for path in client.data if path.startswith("admin_sessions/"))
        client.data[path].update(revoked_at=START, revocation_reason="manual_revocation")
    monkeypatch.setattr(repository_module, "_wait_before_revocation_retry", concurrent_winner)
    assert service.revoke(token, now=START, reason="logout") is False
    assert len(transactions) == 2
    configure()
    session = service.get_session(token)
    assert session.revoked_at == START and session.revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None


def test_revocation_classifier_requires_explicit_sdk_cause():
    conflict = Aborted("Synthetic")
    assert repository_module._is_revocation_contention(conflict)
    explicit = ValueError("Unrelated message")
    explicit.__cause__ = conflict
    assert repository_module._is_revocation_contention(explicit)
    contextual = ValueError("Failed to commit transaction in 5 attempts.")
    contextual.__context__ = conflict
    assert not repository_module._is_revocation_contention(contextual)
    wrapper = RuntimeError("Wrapped")
    wrapper.__cause__ = conflict
    assert not repository_module._is_revocation_contention(wrapper)
    assert not repository_module._is_revocation_contention(ValueError("Failed to commit transaction in 5 attempts."))


@pytest.mark.parametrize("retry_number,base", [(0, 0.05), (1, 0.1), (10, 0.1)])
def test_revocation_backoff_is_bounded(monkeypatch, retry_number, base):
    for fraction in (0, 1):
        jitter = Mock(return_value=base*fraction)
        sleep = Mock()
        monkeypatch.setattr(repository_module.random, "uniform", jitter)
        monkeypatch.setattr(repository_module.time, "sleep", sleep)
        repository_module._wait_before_revocation_retry(retry_number)
        jitter.assert_called_once_with(0.0, base)
        sleep.assert_called_once_with(min(base+base*fraction, 0.2))


def test_create_and_lookup_do_not_gain_outer_retries(sessions, monkeypatch):
    client, service = sessions
    token = token_of(service.create(admin(), now=START))
    transaction_factory = Mock(side_effect=Aborted("Synthetic"))
    monkeypatch.setattr(client, "transaction", transaction_factory)
    wait = Mock()
    monkeypatch.setattr(repository_module, "_wait_before_revocation_retry", wait)
    with pytest.raises(AdminSessionServiceError):
        service.create(admin(), now=START)
    assert transaction_factory.call_count == 1
    transaction_factory.reset_mock()
    with pytest.raises(AdminSessionServiceError):
        service.validate(token, now=START)
    assert transaction_factory.call_count == 1
    wait.assert_not_called()
