"""Reference configuration, demo loopback only; exact-owned-ID cleanup."""
import copy
from datetime import timedelta

import pytest

from app.config.admin_admission_policy import load_admin_admission_policy
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from test_admin_complementary_admission_integration import emulator_client

pytestmark = pytest.mark.firestore_emulator


def test_reference_transition_preserves_origin_budgets(emulator_client):
    _, now, build, documents = emulator_client
    old = build(rule=INITIAL_ADMIN_ADMISSION_POLICY)
    assert old.admit_attempt('192.0.2.1','admin@example.com').outcome == 'allowed'
    before = documents()
    reference = load_admin_admission_policy(selection='complementary-local-v1')
    services = [build(rule=reference),build(1,reference)]
    for _ in range(4):
        assert services[0].admit_attempt('192.0.2.1','admin@example.com').outcome == 'allowed'
    after = documents()
    assert set(before) <= set(after) and len(after) == 4
    # Previous pair debit is preserved: total five attempts, not five extra.
    assert services[1].admit_attempt('192.0.2.1','admin@example.com').outcome == 'limited'
    assert documents() == after
    now[0] += timedelta(seconds=60)
    assert services[1].admit_attempt('192.0.2.1','admin@example.com').outcome == 'allowed'


def test_divergent_reference_policy_is_unavailable_without_partial_debit(emulator_client):
    _, _, build, documents = emulator_client
    reference = load_admin_admission_policy(selection='complementary-local-v1')
    assert build(rule=reference).admit_attempt('192.0.2.1','admin@example.com').outcome == 'allowed'
    before = copy.deepcopy(documents())
    config = {'schema_version':1,'policy':reference.model_dump()}
    config['policy']['aggregate']['capacity'] = 10
    divergent = load_admin_admission_policy(selection='configured-v1',configuration=config)
    with pytest.raises(AdminAdmissionUnavailable):
        build(1,divergent).admit_attempt('192.0.2.2','other@example.com')
    assert documents() == before
