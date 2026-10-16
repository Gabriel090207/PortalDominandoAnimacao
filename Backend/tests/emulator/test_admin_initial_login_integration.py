"""Step 35: approved policy/config with existing services and guarded emulator."""
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from test_admin_auth_integration import seed, service, PASSWORD
from test_admin_login_integration import buckets
from test_admin_domain import START
from test_admin_admission import ORIGIN
from emulator_support import create_test_client
from app.config.admin_admission import load_admin_admission_config, AdminAdmissionConfigurationError
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_admission_repository import AdminAdmissionRepository, AdminAdmissionUnavailable
from app.services.admin_admission_service import AdminAdmissionService
from app.services.admin_auth_service import InvalidAdminCredentials
from app.services.admin_login_service import AdminLoginService, AdminLoginLimited

pytestmark = pytest.mark.firestore_emulator
KEY = '0123456789abcdef'*4
NAME = 'ADMIN_ADMISSION_HMAC_SECRET'


def compose(client, now, config):
    auth, sessions = service(client)
    admission = AdminAdmissionService(AdminAdmissionRepository(client), policy=INITIAL_ADMIN_ADMISSION_POLICY,
        admission_hmac_secret=config.secret.get_secret_value(), key_version=config.key_version, clock=lambda: now[0])
    return AdminLoginService(admission, auth), sessions


@pytest.fixture
def config(tmp_path):
    path = tmp_path / '.env'
    path.write_text(NAME+'='+KEY+'\n')
    return load_admin_admission_config(environ={}, env_file=path)


@pytest.mark.parametrize('role', ['owner', 'operator'])
def test_configuration_to_session_and_revocation(emulator_client, config, role, monkeypatch, caplog, capsys):
    seed(emulator_client, role)
    login, sessions = compose(emulator_client, [START], config)
    original = login.auth_service.authenticate
    def after_commit(email, password):
        assert {d['scope']: d['credits'] for d in buckets(emulator_client).values()} == {
            'origin': 9*30_000_000, 'origin_identity': 4*60_000_000}
        return original(email, password)
    monkeypatch.setattr(login.auth_service, 'authenticate', after_commit)
    issued = login.authenticate(ORIGIN, ' ADMIN@EXAMPLE.COM ', PASSWORD)
    token = issued.token.get_secret_value()
    instant = issued.session.created_at
    assert issued.session.expires_at-instant == timedelta(hours=8)
    assert sessions.validate(token, now=instant).role == role
    assert sessions.validate(token, now=issued.session.expires_at) is None
    assert sessions.revoke(token, now=instant+timedelta(seconds=1))
    before = sessions.get_session(token)
    assert not sessions.revoke(token, now=instant+timedelta(seconds=2))
    assert sessions.get_session(token) == before
    assert sessions.validate(token, now=instant+timedelta(seconds=3)) is None
    stored = list(emulator_client.collection('admin_sessions').stream(timeout=5))
    assert len(stored) == 1 and token not in str(stored[0].to_dict())
    output = capsys.readouterr()
    record = emulator_client.collection('admins').document('synthetic-admin').get(timeout=5).to_dict()
    public = output.out+output.err+caplog.text+repr(issued)
    assert all(secret not in public for secret in (KEY, PASSWORD, token, record['password_hash']))


@pytest.mark.parametrize('kind', ['wrong', 'missing', 'invalid', 'disabled'])
def test_failures_limit_and_gradually_recover(emulator_client, config, kind, monkeypatch):
    if kind in {'wrong', 'disabled'}:
        seed(emulator_client, **({'status': 'disabled'} if kind == 'disabled' else {}))
    now = [START]
    login, _ = compose(emulator_client, now, config)
    email = 'invalid-one' if kind == 'invalid' else 'admin@example.com'
    if kind == 'invalid':
        lookup = Mock(side_effect=AssertionError('No lookup'))
        monkeypatch.setattr(login.auth_service.repository, 'find_by_email', lookup)
    for _ in range(5):
        with pytest.raises(InvalidAdminCredentials): login.authenticate(ORIGIN, email, 'incorrect synthetic password')
    before = buckets(emulator_client)
    with monkeypatch.context() as patch:
        forbidden = Mock(side_effect=AssertionError('Authentication before admission'))
        patch.setattr(login.auth_service, 'authenticate', forbidden)
        for delta in (0, 30, 29.999999):
            now[0] += timedelta(seconds=delta)
            with pytest.raises(AdminLoginLimited):
                login.authenticate(ORIGIN, 'invalid-two' if kind == 'invalid' else email, PASSWORD)
        forbidden.assert_not_called()
    assert buckets(emulator_client) == before
    now[0] += timedelta(microseconds=1)
    with pytest.raises(InvalidAdminCredentials): login.authenticate(ORIGIN, email, 'incorrect synthetic password')
    if kind == 'invalid': lookup.assert_not_called()
    assert list(emulator_client.collection('admin_sessions').stream(timeout=5)) == []


def test_instances_share_config_and_origin_refill(emulator_client, config):
    seed(emulator_client)
    second = create_test_client()
    try:
        now = [START]
        other_config = load_admin_admission_config(environ={NAME: KEY}, env_file=None)
        first, _ = compose(emulator_client, now, config)
        other, _ = compose(second, now, other_config)
        first.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        for index in range(9):
            with pytest.raises(InvalidAdminCredentials):
                [first, other][index % 2].authenticate(ORIGIN, f'absent{index}@example.com', PASSWORD)
        before = buckets(emulator_client)
        with pytest.raises(AdminLoginLimited): other.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        assert buckets(emulator_client) == before
        now[0] += timedelta(seconds=30, microseconds=-1)
        with pytest.raises(AdminLoginLimited): first.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        now[0] += timedelta(microseconds=1)
        other.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
        assert len(list(emulator_client.collection('admin_sessions').stream(timeout=5))) == 2
    finally:
        second.close()


def test_firestore_error_prevents_authentication(emulator_client, config, monkeypatch, caplog, capsys):
    login, _ = compose(emulator_client, [START], config)
    forbidden = Mock(side_effect=AssertionError('Authentication forbidden'))
    monkeypatch.setattr(login.auth_service, 'authenticate', forbidden)
    monkeypatch.setattr(emulator_client, 'transaction', Mock(side_effect=ServiceUnavailable(KEY+PASSWORD)))
    with pytest.raises(AdminAdmissionUnavailable) as caught: login.authenticate(ORIGIN, 'admin@example.com', PASSWORD)
    forbidden.assert_not_called()
    assert buckets(emulator_client) == {}
    output = capsys.readouterr()
    public = str(caught.value)+output.out+output.err+caplog.text
    assert KEY not in public and PASSWORD not in public


@pytest.mark.parametrize('environment', [{}, {NAME: ''}, {NAME: 'malformed'}])
def test_config_error_before_initialization_public_routes_unchanged(emulator_client, environment, monkeypatch):
    with pytest.raises(AdminAdmissionConfigurationError):
        config = load_admin_admission_config(environ=environment, env_file=None)
        compose(emulator_client, [START], config)
    assert list(emulator_client.collections(timeout=5)) == []
    monkeypatch.delenv(NAME, raising=False)
    monkeypatch.setattr('app.api.kirvano.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN', 'synthetic-test-webhook-token')
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.post('/webhooks/kirvano', json={}).status_code == 401
