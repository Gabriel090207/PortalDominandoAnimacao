"""Approved configuration exercised through the existing admission contracts."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError

from test_admin_admission import admission, ORIGIN, EMAIL, policy
from app.domain.admin_admission import AdminAdmissionPolicy
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY as INITIAL
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable


def test_approved_configuration_is_validated_and_immutable():
    assert INITIAL.model_dump() == {
        'origin': dict(capacity=10, refill_tokens=1, refill_period_seconds=30),
        'origin_identity': dict(capacity=5, refill_tokens=1, refill_period_seconds=60)}
    assert AdminAdmissionPolicy.model_validate(INITIAL.model_dump()) == INITIAL
    with pytest.raises(ValidationError): INITIAL.origin.capacity = 20
    with pytest.raises(ValidationError): INITIAL.origin = INITIAL.origin_identity


@pytest.mark.parametrize('scope', ['origin', 'origin_identity'])
@pytest.mark.parametrize('field', ['capacity', 'refill_tokens', 'refill_period_seconds'])
@pytest.mark.parametrize('invalid', [0, -1, None, True, '1', 1.5])
def test_invalid_configuration(scope, field, invalid):
    document = INITIAL.model_dump()
    document[scope][field] = invalid
    with pytest.raises(ValidationError): AdminAdmissionPolicy.model_validate(document)


def exhaust_origin(service):
    for index in range(10):
        assert service.admit(ORIGIN, f'admin{index}@example.com').outcome == 'allowed'


def test_ten_shared_origin_admissions_and_atomic_eleventh_denial(admission):
    client, _, build = admission
    service = build(INITIAL)
    exhaust_origin(service)
    before = copy.deepcopy(client.data)
    assert service.admit(ORIGIN, 'another@example.com').outcome == 'limited'
    assert client.data == before
    assert len(client.data) == 11  # One shared origin plus ten identities.


def test_five_pair_admissions_and_independent_origins(admission):
    client, _, build = admission
    service = build(INITIAL)
    for _ in range(5): assert service.admit(ORIGIN, EMAIL).outcome == 'allowed'
    before = copy.deepcopy(client.data)
    assert service.admit(ORIGIN, EMAIL).outcome == 'limited'
    assert client.data == before
    assert service.admit('192.0.2.124', EMAIL).outcome == 'allowed'
    assert service.admit(ORIGIN, 'second@example.com').outcome == 'allowed'


@pytest.mark.parametrize('scope,seconds', [('origin', 30), ('origin_identity', 60)])
def test_refill_boundary_and_gradual_recovery(admission, scope, seconds):
    client, now, build = admission
    service = build(INITIAL)
    if scope == 'origin': exhaust_origin(service)
    else:
        for _ in range(5): service.admit(ORIGIN, EMAIL)
    email = 'new@example.com' if scope == 'origin' else EMAIL
    now[0] += timedelta(seconds=seconds, microseconds=-1)
    before = copy.deepcopy(client.data)
    assert service.admit(ORIGIN, email).outcome == 'limited'
    assert client.data == before
    now[0] += timedelta(microseconds=1)
    assert service.admit(ORIGIN, email).outcome == 'allowed'
    assert service.admit(ORIGIN, email).outcome == 'limited'
    now[0] += timedelta(seconds=seconds*2)
    assert service.admit(ORIGIN, email).outcome == 'allowed'
    assert service.admit(ORIGIN, email).outcome == 'allowed'
    assert service.admit(ORIGIN, email).outcome == 'limited'


def test_long_idle_refill_is_capped(admission):
    client, now, build = admission
    service = build(INITIAL)
    service.admit(ORIGIN, EMAIL)
    now[0] += timedelta(days=10)
    assert service.admit(ORIGIN, EMAIL).outcome == 'allowed'
    docs = {doc['scope']: doc for doc in client.data.values()}
    assert docs['origin']['credits'] == 9*INITIAL.origin.unit
    assert docs['origin_identity']['credits'] == 4*INITIAL.origin_identity.unit


def test_concurrent_instances_share_approved_origin_budget(admission):
    _, _, build = admission
    services = [build(INITIAL), build(INITIAL)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: services[i % 2].admit(
            ORIGIN, f'admin{i}@example.com').outcome, range(20)))
    assert results.count('allowed') == results.count('limited') == 10


def test_invalid_emails_keep_shared_identity_bucket(admission):
    _, _, build = admission
    service = build(INITIAL)
    for i in range(5): assert service.admit_attempt(ORIGIN, f'invalid-{i}').outcome == 'allowed'
    assert service.admit_attempt(ORIGIN, None).outcome == 'limited'
    assert service.admit_attempt(ORIGIN, EMAIL).outcome == 'allowed'


@pytest.mark.parametrize('expired', [False, True])
def test_old_persisted_policy_fails_closed_without_mutations(admission, expired):
    client, now, build = admission
    build(policy()).admit(ORIGIN, EMAIL)
    if expired: now[0] += timedelta(days=1)
    before = copy.deepcopy(client.data)
    with pytest.raises(AdminAdmissionUnavailable): build(INITIAL).admit(ORIGIN, EMAIL)
    assert client.data == before
