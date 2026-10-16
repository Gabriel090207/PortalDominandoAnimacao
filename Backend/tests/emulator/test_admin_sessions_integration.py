"""Real session transactions, only with the existing guarded emulator fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable
from google.cloud.firestore_v1.transaction import Transaction

from test_admin_domain import admin, session, START
from test_admin_sessions import admin_document, token_of
from app.persistence.admin_records import AdminSessionRecord
from app.persistence.admin_sessions_repository import AdminSessionsRepository, SessionCollisionError
from app.services.admin_session_service import AdminSessionService, AdminSessionServiceError, _digest

pytestmark = pytest.mark.firestore_emulator


@pytest.fixture
def service(emulator_client):
    emulator_client.collection("admins").document("synthetic-admin").create(admin_document(), timeout=5)
    return AdminSessionService(AdminSessionsRepository(emulator_client))


def test_session_lifecycle(emulator_client, service):
    issued = service.create(admin(), now=START)
    token = token_of(issued)
    documents = list(emulator_client.collection("admin_sessions").stream(timeout=5))
    assert len(documents) == 1 and token not in documents[0].id
    assert token not in str(documents[0].to_dict())
    assert AdminSessionRecord.from_document(documents[0].to_dict()).to_session() == issued.session
    assert service.validate(token, now=START) == admin()
    assert service.validate(token, now=START+timedelta(hours=8)) is None
    assert service.revoke(token, now=START)
    assert not service.revoke(token, now=START)
    assert service.validate(token, now=START) is None


@pytest.mark.parametrize("change", [{"status":"disabled"}, {"auth_version":2}])
def test_admin_change_invalidates_and_prevents_stale_creation(emulator_client, service, change):
    token = token_of(service.create(admin(), now=START))
    emulator_client.collection("admins").document("synthetic-admin").update(change, timeout=5)
    assert service.validate(token, now=START) is None
    with pytest.raises(AdminSessionServiceError): service.create(admin(), now=START)
    assert len(list(emulator_client.collection("admin_sessions").stream(timeout=5))) == 1


def test_concurrent_session_creation_collision(emulator_client, service):
    # Test the precise repository collision contract, not any service failure.
    digest = _digest("3"*64)
    barrier = Barrier(2)
    def issue(_):
        barrier.wait(timeout=10)
        try:
            service.repository.create(digest, session())
            return "created"
        except SessionCollisionError:
            return "collision"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, range(2)))
    assert sorted(results) == ["collision", "created"]
    assert len(list(emulator_client.collection("admin_sessions").stream(timeout=5))) == 1
    assert service.get_session("3"*64) == session()


def test_concurrent_revocation_preserves_winner(emulator_client, service):
    token = token_of(service.create(admin(), now=START))
    barrier = Barrier(2)
    candidates = [(START+timedelta(seconds=1), "logout"),
                  (START+timedelta(seconds=2), "manual_revocation")]
    def revoke(index):
        barrier.wait(timeout=10)
        now, reason = candidates[index]
        try:
            return index, service.revoke(token, now=now, reason=reason)
        except AdminSessionServiceError as error:
            # Current production permits terminal contention failures. Accept
            # only the SDK's recognized shapes, never an arbitrary exception.
            storage = error.__context__
            original = storage.__context__ if storage is not None else None
            assert isinstance(original, Aborted) or (
                type(original) is ValueError and isinstance(original.__cause__, Aborted))
            assert str(error) == "Session revocation failed."
            return index, "contention_failure"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(revoke, range(2)))
    winners = [index for index, result in outcomes if result is True]
    assert len(winners) == 1
    assert all(result is True or result is False or result == "contention_failure" for _, result in outcomes)
    stored = service.get_session(token)
    assert (stored.revoked_at, stored.revocation_reason) == candidates[winners[0]]
    assert service.validate(token, now=START+timedelta(seconds=10)) is None
    assert service.revoke(token, now=START+timedelta(seconds=20), reason="credentials_changed") is False
    assert service.get_session(token) == stored


def test_abort_after_buffering_leaves_active_session(emulator_client, service, monkeypatch):
    token = token_of(service.create(admin(), now=START))
    before = service.get_session(token)
    original = service.repository._revoke
    def abort(transaction, *args):
        assert original(transaction, *args) is True
        raise Aborted("Synthetic abort before commit")
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "_revoke", abort)
        with pytest.raises(AdminSessionServiceError, match="Session revocation failed"):
            service.revoke(token, now=START, reason="manual_revocation")
    assert service.get_session(token) == before
    assert service.validate(token, now=START) == admin()


def test_revocation_retries_callback_aborted_with_fresh_transaction(emulator_client, service, monkeypatch):
    token = token_of(service.create(admin(), now=START))
    original = service.repository._revoke
    transactions = []
    def conflict_once(transaction, *args):
        transactions.append(transaction)
        result = original(transaction, *args)
        if len(transactions) == 1:
            raise Aborted("Synthetic conflict before commit")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "_revoke", conflict_once)
        assert service.revoke(token, now=START, reason="manual_revocation") is True
    assert len(transactions) == 2 and transactions[0] is not transactions[1]
    stored = service.get_session(token)
    assert stored.revoked_at == START and stored.revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None
    assert service.revoke(token, now=START, reason="logout") is False
    assert service.get_session(token) == stored


def test_successful_commit_with_lost_response_is_uncertain(emulator_client, service, monkeypatch, capsys, caplog):
    token = token_of(service.create(admin(), now=START))
    original = Transaction._commit
    calls = []
    def lost_response(transaction):
        original(transaction)  # Real emulator commit first.
        calls.append(True)
        raise ServiceUnavailable("SYNTHETIC_PRIVATE " + token)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction, "_commit", lost_response)
        with pytest.raises(AdminSessionServiceError) as caught:
            service.revoke(token, now=START, reason="manual_revocation")
    assert calls == [True]  # No outer application retry.
    assert str(caught.value) == "Session revocation failed."
    output = capsys.readouterr()
    assert token not in output.out + output.err + caplog.text + str(caught.value)
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    stored = service.get_session(token)
    assert stored.revoked_at == START and stored.revocation_reason == "manual_revocation"
    assert service.validate(token, now=START) is None
    assert service.revoke(token, now=START, reason="logout") is False
    assert service.get_session(token) == stored
