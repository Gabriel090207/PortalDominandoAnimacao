"""Explicit synthetic policies/secrets; no Firebase or HTTP integration."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable
from google.cloud.firestore_v1.transaction import transactional as sdk_transactional
from pydantic import ValidationError

from commerce_fake import Client, Transaction
from test_admin_domain import START
from test_admin_session_transaction_failures import ScriptedSDKTransaction
from app.domain.admin_admission import AdminAdmissionPolicy, BucketPolicy
from app.persistence.admin_admission_repository import AdminAdmissionRepository, AdminAdmissionUnavailable
from app.services.admin_admission_service import AdminAdmissionService, derive_bucket_identifiers

SECRET = "synthetic-admission-only-key-32-bytes"
ORIGIN = "192.0.2.123"
EMAIL = "owner@example.com"


def policy(origin_capacity=3, pair_capacity=2):
    return AdminAdmissionPolicy(
        origin=BucketPolicy(capacity=origin_capacity, refill_tokens=1, refill_period_seconds=10),
        origin_identity=BucketPolicy(capacity=pair_capacity, refill_tokens=1, refill_period_seconds=20))


@pytest.fixture
def admission(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Production Firebase forbidden")
    monkeypatch.setattr("firebase_admin.initialize_app", forbidden)
    monkeypatch.setattr("app.services.firebase_service.get_firestore_client", forbidden)
    client = Client()
    client.transaction = lambda: Transaction(client)
    lock = Lock()
    def transactional(callback):
        def run(transaction, *args):
            with lock:
                value = callback(transaction, *args)
                transaction.commit()
                return value
        return run
    monkeypatch.setattr("app.persistence.admin_admission_repository.firestore.transactional", transactional)
    now = [START]
    def build(rule=None):
        return AdminAdmissionService(AdminAdmissionRepository(client), policy=rule or policy(),
            admission_hmac_secret=SECRET, clock=lambda: now[0])
    return client, now, build


def test_first_admission_consumes_and_hides_identity(admission, capsys, caplog):
    client, _, build = admission
    assert build().admit(ORIGIN, " OWNER@EXAMPLE.COM ").outcome == "allowed"
    assert len(client.data) == 2
    assert all(path.startswith("auth_throttles/") for path in client.data)
    by_scope = {doc['scope']: doc for doc in client.data.values()}
    assert by_scope['origin']['credits'] == 20_000_000
    assert by_scope['origin_identity']['credits'] == 20_000_000
    serialized = str(client.data)
    for sensitive in (ORIGIN, EMAIL, SECRET, 'password', 'token_digest'):
        assert sensitive not in serialized
    output = capsys.readouterr()
    assert output.out == output.err == caplog.text == ""


def test_pair_denial_does_not_consume_origin_or_extend_expiry(admission):
    client, _, build = admission
    service = build()
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    before = copy.deepcopy(client.data)
    decision = service.admit(ORIGIN, EMAIL)
    assert decision.outcome == "limited" and decision.retry_after_seconds == 20
    assert client.data == before
    assert service.admit(ORIGIN, "other@example.com").outcome == "allowed"


def test_origin_denial_does_not_create_pair(admission):
    client, _, build = admission
    service = build(policy(1, 3))
    service.admit(ORIGIN, EMAIL)
    before = copy.deepcopy(client.data)
    assert service.admit(ORIGIN, "other@example.com").outcome == "limited"
    assert client.data == before


def test_gradual_refill_and_logical_expiry_without_deletion(admission):
    client, now, build = admission
    service = build(policy(1, 1))
    service.admit(ORIGIN, EMAIL)
    before = copy.deepcopy(client.data)
    now[0] += timedelta(seconds=10)
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"  # Pair has half token.
    assert client.data == before
    now[0] += timedelta(seconds=10)
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    now[0] += timedelta(seconds=200)
    assert len(client.data) == 2  # No physical TTL deletion involved.
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"


def test_origin_and_pair_independence(admission):
    _, _, build = admission
    service = build(policy(3, 1))
    service.admit(ORIGIN, EMAIL)
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"
    assert service.admit("192.0.2.124", EMAIL).outcome == "allowed"
    assert service.admit(ORIGIN, "other@example.com").outcome == "allowed"


def test_fractional_tokens_survive_successful_consumption(admission):
    client, now, build = admission
    service = build(policy(3, 2))
    service.admit(ORIGIN, EMAIL)
    now[0] += timedelta(seconds=10)
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    pair = next(doc for doc in client.data.values() if doc["scope"] == "origin_identity")
    assert pair["credits"] == 10_000_000  # Half token remains; not rounded away.
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"
    now[0] += timedelta(seconds=10)
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"


def test_backward_clock_does_not_mint_tokens(admission):
    client, now, build = admission
    service = build(policy(1, 1))
    service.admit(ORIGIN, EMAIL)
    before = copy.deepcopy(client.data)
    now[0] -= timedelta(days=1)
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"
    assert client.data == before


def test_multiple_instances_share_atomic_budget(admission):
    client, _, build = admission
    services = [build(policy(3, 3)), build(policy(3, 3))]
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda i: services[i%2].admit(ORIGIN, EMAIL).outcome, range(8)))
    assert outcomes.count("allowed") == 3 and outcomes.count("limited") == 5
    assert len(client.data) == 2 and all(doc['credits'] == 0 for doc in client.data.values())


@pytest.mark.parametrize("value", [0, -1, True, "1", 1.0, None])
@pytest.mark.parametrize("field", ["capacity", "refill_tokens", "refill_period_seconds"])
def test_invalid_bucket_configuration(field, value):
    with pytest.raises(ValidationError):
        BucketPolicy(**(dict(capacity=2, refill_tokens=1, refill_period_seconds=10) | {field:value}))


def test_overflow_and_missing_policy_rejected():
    with pytest.raises(ValidationError): BucketPolicy(capacity=2**63-1, refill_tokens=1, refill_period_seconds=1)
    with pytest.raises(ValidationError): AdminAdmissionPolicy()


@pytest.mark.parametrize("secret", [None, "", " ", "short", "\ud800"*32, 1])
def test_invalid_secret_is_sanitized_without_access(secret):
    repo = Mock()
    with pytest.raises(AdminAdmissionUnavailable) as caught:
        AdminAdmissionService(repo, policy=policy(), admission_hmac_secret=secret, clock=lambda: START)
    assert str(caught.value) == "Administrative admission unavailable."
    repo.admit.assert_not_called()


def test_identifiers_are_stable_separated_and_versioned():
    first = derive_bucket_identifiers(ORIGIN, EMAIL, admission_hmac_secret=SECRET)
    other_email = derive_bucket_identifiers(ORIGIN, "other@example.com", admission_hmac_secret=SECRET)
    versioned = derive_bucket_identifiers(ORIGIN, EMAIL, admission_hmac_secret=SECRET, key_version=2)
    assert first[0] == other_email[0] and first[1] != other_email[1]
    assert first[0] != first[1] and set(first).isdisjoint(versioned)
    assert first == derive_bucket_identifiers(ORIGIN, EMAIL, admission_hmac_secret=SECRET)
    assert set(first).isdisjoint(derive_bucket_identifiers(ORIGIN, EMAIL, admission_hmac_secret=SECRET+"other"))
    for value in (True, 0, "1"):
        with pytest.raises(ValueError):
            derive_bucket_identifiers(ORIGIN, EMAIL, admission_hmac_secret=SECRET, key_version=value)


@pytest.mark.parametrize("kind", ["network", "clock", "policy_drift", "corrupt"])
def test_failure_is_not_permission_and_is_sanitized(admission, monkeypatch, kind, capsys, caplog):
    client, now, build = admission
    service = build()
    service.admit(ORIGIN, EMAIL)
    if kind == "network":
        monkeypatch.setattr(client, "transaction", Mock(side_effect=ServiceUnavailable(SECRET+EMAIL+ORIGIN)))
    elif kind == "clock": now[0] = START.replace(tzinfo=None)
    elif kind == "policy_drift": service = build(policy(4, 2))
    else: next(iter(client.data.values()))["credits"] = True
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminAdmissionUnavailable) as caught: service.admit(ORIGIN, EMAIL)
    assert client.data == before
    output = capsys.readouterr()
    public = str(caught.value)+repr(caught.value)+output.out+output.err+caplog.text
    assert all(value not in public for value in (SECRET, EMAIL, ORIGIN))


def test_sdk_retry_does_not_double_consume(admission, monkeypatch):
    client, _, build = admission
    transaction = ScriptedSDKTransaction(client, [Aborted("Synthetic contention")])
    factory = Mock(return_value=transaction)
    monkeypatch.setattr(client, "transaction", factory)
    monkeypatch.setattr("app.persistence.admin_admission_repository.firestore.transactional", sdk_transactional)
    assert build().admit(ORIGIN, EMAIL).outcome == "allowed"
    assert transaction.commits == 2
    factory.assert_called_once_with()
    assert sorted(doc["credits"] for doc in client.data.values()) == [20_000_000, 20_000_000]


@pytest.mark.parametrize("actions", [[RuntimeError("synthetic failure")],
    [Aborted("Synthetic contention")]*5, ["commit_then_lose_response"]])
def test_commit_failure_or_uncertainty_never_returns_permission(admission, monkeypatch, actions):
    client, _, build = admission
    tx = ScriptedSDKTransaction(client, actions)
    factory = Mock(return_value=tx)
    monkeypatch.setattr(client, "transaction", factory)
    monkeypatch.setattr("app.persistence.admin_admission_repository.firestore.transactional", sdk_transactional)
    with pytest.raises(AdminAdmissionUnavailable): build().admit(ORIGIN, EMAIL)
    factory.assert_called_once_with()  # Never repeat an uncertain commit externally.
    if actions == ["commit_then_lose_response"]:
        assert len(client.data) == 2  # Both committed, but caller got no permission.
    else:
        assert client.data == {}


@pytest.mark.parametrize("changes", [dict(policy=None), dict(clock=None), dict(key_version=0)])
def test_invalid_service_configuration_never_touches_storage(changes):
    repo = Mock()
    config = dict(policy=policy(), admission_hmac_secret=SECRET, clock=lambda: START)
    with pytest.raises(AdminAdmissionUnavailable): AdminAdmissionService(repo, **(config | changes))
    assert repo.mock_calls == []


@pytest.mark.parametrize("origin,email", [("", EMAIL), (ORIGIN+"\n", EMAIL), (ORIGIN, "invalid")])
def test_invalid_admission_input_never_touches_storage(origin, email):
    repo = Mock()
    service = AdminAdmissionService(repo, policy=policy(), admission_hmac_secret=SECRET, clock=lambda: START)
    with pytest.raises(AdminAdmissionUnavailable): service.admit(origin, email)
    assert repo.mock_calls == []


def test_admission_does_not_modify_admin_user_or_commercial_state(admission):
    client, _, build = admission
    collections = ("admins", "users", "admin_sessions", "subscriptions", "purchases", "entitlements", "kirvano_events")
    for name in collections:
        client.data[name+"/synthetic"] = {"sentinel": name, "status": "unchanged"}
    before = copy.deepcopy(client.data)
    service = build(policy(1, 1))
    assert service.admit(ORIGIN, EMAIL).outcome == "allowed"
    assert service.admit(ORIGIN, EMAIL).outcome == "limited"
    assert {key:value for key,value in client.data.items() if not key.startswith("auth_throttles/")} == before
