"""Explicit versioned local configuration, synthetic secrets/storage only."""
import copy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.admin_admission_policy import load_admin_admission_policy
from app.config.admin_admission import AdminAdmissionConfigurationError, AdminAdmissionConfig, load_admin_admission_config
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from test_admin_admission import admission
from test_admin_complementary_admission import attempt
from test_admin_composition import compose, app_for, ORIGIN
from test_admin_origin_composition import origin_composition
from test_admin_sessions import sessions


def reference():
    return load_admin_admission_policy(selection='complementary-local-v1')


def configuration():
    return {'schema_version':1, 'policy':reference().model_dump()}


def test_reference_and_explicit_composition():
    rule = reference()
    assert [(scope,p.capacity,p.refill_tokens,p.refill_period_seconds) for scope,p in rule.bucket_rules] == [
        ('origin',10,1,30), ('origin_identity',5,1,60), ('identity',5,1,60), ('aggregate',20,1,30)]
    storage = Mock()
    composition = compose(storage, policy=rule)
    assert composition.admission_service.policy == rule
    assert len(compose(Mock()).admission_service.policy.bucket_rules) == 2
    assert len(INITIAL_ADMIN_ADMISSION_POLICY.bucket_rules) == 2
    assert storage.mock_calls == []


@pytest.mark.parametrize('selection', [None,'','complementary-local-v2','production',1])
def test_no_implicit_selection(selection):
    with pytest.raises(AdminAdmissionConfigurationError): load_admin_admission_policy(selection=selection)


@pytest.mark.parametrize('change', ['missing','version','bool_version','incomplete','extra','null'])
def test_incomplete_or_unsupported_configuration(change):
    data = configuration()
    if change == 'missing': data = None
    elif change == 'version': data['schema_version'] = 2
    elif change == 'bool_version': data['schema_version'] = True
    elif change == 'incomplete': del data['policy']['aggregate']
    elif change == 'extra': data['unexpected'] = 'synthetic private value'
    else: data['policy'] = None
    with pytest.raises(AdminAdmissionConfigurationError) as caught:
        load_admin_admission_policy(selection='configured-v1',configuration=data)
    assert str(caught.value) == 'Invalid administrative admission configuration.'
    assert caught.value.__cause__ is None


@pytest.mark.parametrize('scope', ['origin','origin_identity','identity','aggregate'])
@pytest.mark.parametrize('field,value', [('capacity',0),('capacity',-1),('capacity',True),
    ('refill_tokens',0),('refill_tokens',-1),('refill_period_seconds',0),('refill_period_seconds',1.5)])
def test_all_limits_strictly_validated(scope,field,value):
    data = configuration()
    data['policy'][scope][field] = value
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_policy(selection='configured-v1',configuration=data)


def test_configured_values_revalidated_and_no_reference_override():
    assert load_admin_admission_policy(selection='configured-v1',configuration=configuration()) == reference()
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_policy(selection='complementary-local-v1',configuration=configuration())


def test_missing_secret_and_unsupported_hmac_version():
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_config(environ={},env_file=None)
    with pytest.raises(AdminAdmissionConfigurationError):
        AdminAdmissionConfig(secret=SecretStr('a'*64),key_version=2)
    from app.admin_composition import AdminCompositionError
    with pytest.raises(AdminCompositionError): compose(Mock(),policy=reference(),admission_config=None)


def test_old_buckets_preserved_on_opt_in_and_divergence_fails_closed(admission):
    storage,_,build = admission
    old = build(INITIAL_ADMIN_ADMISSION_POLICY)
    assert attempt(old) == 'allowed'
    original = copy.deepcopy(storage.data)
    assert attempt(build(reference())) == 'allowed'
    assert len(storage.data) == 4
    assert set(original) <= set(storage.data)
    data = configuration()
    data['policy']['aggregate']['capacity'] = 10
    different = load_admin_admission_policy(selection='configured-v1',configuration=data)
    before = copy.deepcopy(storage.data)
    with pytest.raises(AdminAdmissionUnavailable): attempt(build(different))
    assert storage.data == before
    # Old instances remain capable of ignoring independent budgets: no claim
    # that stored documents coordinate a deployment or enforce schema globally.
    assert attempt(old) == 'allowed'
    aggregate = next(d for d in storage.data.values() if d['scope']=='aggregate')
    assert aggregate == next(d for d in before.values() if d['scope']=='aggregate')


def test_reference_uses_existing_full_login_lifecycle(origin_composition):
    storage, composition = origin_composition
    # Recompose explicitly with configured policy; reuse only synthetic lookup.
    lookup = composition.login_service.auth_service.repository.find_by_email
    composition = compose(storage, policy=reference())
    composition.login_service.auth_service.repository.find_by_email = lookup
    h={'Origin':ORIGIN,'X-Admin-Request':'1'}
    with TestClient(app_for(composition),base_url='https://testserver') as http:
        assert http.post('/admin/auth/login',headers=h,json={'email':'admin@example.com',
            'password':'synthetic session admin password'}).status_code == 200
        assert len([d for d in storage.data.values() if d.get('scope')]) == 4
        assert http.get('/admin/auth/session',headers=h).status_code == 200
        assert http.post('/admin/auth/logout',headers={'Origin':ORIGIN}).status_code == 403
        assert http.post('/admin/auth/logout',headers=h).status_code == 200
        assert http.get('/admin/auth/session',headers=h).status_code == 401


def test_preconstructed_policy_is_revalidated():
    broken = reference().model_copy(update={'aggregate':None})
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_policy(selection='configured-v1',configuration={'schema_version':1,'policy':broken})


def test_reference_never_approves_network_origin():
    storage = Mock()
    composition = compose(storage,policy=reference(),trusted_origin_dependency=None)
    with TestClient(app_for(composition)) as http:
        result = http.post('/admin/auth/login',headers={'Origin':ORIGIN,'X-Admin-Request':'1',
            'CF-Connecting-IP':'192.0.2.1'},json={'email':'admin@example.com','password':'synthetic password'})
    assert result.status_code == 503
    assert 'set-cookie' not in result.headers
    assert storage.mock_calls == []
