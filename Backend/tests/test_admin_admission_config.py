"""Synthetic configuration only; no production services."""
import hashlib
import hmac
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from app.config.admin_admission import load_admin_admission_config, AdminAdmissionConfigurationError
from app.services.admin_admission_service import derive_bucket_identifiers, AdminAdmissionService
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.domain.email_identity import derive_email_identity
from test_admin_domain import START

KEY = '0123456789abcdef'*4
NAME = 'ADMIN_ADMISSION_HMAC_SECRET'


def load(value):
    return load_admin_admission_config(environ={NAME: value}, env_file=None)


def test_valid_configuration_and_service():
    config = load(KEY)
    assert config.secret.get_secret_value() == KEY and config.key_version == 1
    repo = Mock()
    service = AdminAdmissionService(repo, policy=INITIAL_ADMIN_ADMISSION_POLICY,
        admission_hmac_secret=config.secret.get_secret_value(), key_version=config.key_version, clock=lambda: START)
    service.admit('192.0.2.1', 'admin@example.com')
    repo.admit.assert_called_once()
    assert KEY not in repr(config) and KEY not in str(config.secret)


@pytest.mark.parametrize('value', [None, '', ' ', 'short', 'a'*63, 'a'*65, 'g'*64, KEY.upper(), KEY+'\n', 123])
def test_invalid_sanitized(value, caplog, capsys):
    with pytest.raises(AdminAdmissionConfigurationError) as caught: load(value)
    output = capsys.readouterr()
    assert str(caught.value) == 'Invalid administrative admission configuration.'
    assert caught.value.__cause__ is None
    assert KEY not in str(caught.value)+repr(caught.value)+output.out+output.err+caplog.text


def test_missing_no_fallback():
    with pytest.raises(AdminAdmissionConfigurationError):
        load_admin_admission_config(environ={'EMAIL_IDENTITY_HMAC_SECRET': KEY, 'KIRVANO_WEBHOOK_TOKEN': KEY}, env_file=None)


def test_dotenv_and_precedence(tmp_path):
    path = tmp_path / '.env'
    path.write_text(NAME+'='+KEY+'\n')
    environment = {}
    assert load_admin_admission_config(environ=environment, env_file=path).secret.get_secret_value() == KEY
    assert environment == {} and path.read_text() == NAME+'='+KEY+'\n'
    other = 'abcdef0123456789'*4
    assert load_admin_admission_config(environ={NAME: other}, env_file=path).secret.get_secret_value() == other
    with pytest.raises(AdminAdmissionConfigurationError): load_admin_admission_config(environ={NAME: ''}, env_file=path)
    path.write_text(NAME+'=${EMAIL_IDENTITY_HMAC_SECRET}\n')
    with pytest.raises(AdminAdmissionConfigurationError): load_admin_admission_config(environ={}, env_file=path)


def test_hmac_compatibility_determinism_and_separation():
    ids = derive_bucket_identifiers('192.0.2.1', 'admin@example.com', admission_hmac_secret=load(KEY).secret.get_secret_value())
    message = json.dumps(['portal-admin-admission', 1, 1, 'origin', ['192.0.2.1']], separators=(',', ':')).encode()
    assert ids[0] == hmac.new(KEY.encode(), message, hashlib.sha256).hexdigest()
    assert ids == derive_bucket_identifiers('192.0.2.1', 'admin@example.com', admission_hmac_secret=KEY)
    assert len(set(ids)) == 2
    assert set(ids).isdisjoint(derive_bucket_identifiers('192.0.2.1', 'admin@example.com', admission_hmac_secret='f'*64))
    assert set(ids).isdisjoint(derive_bucket_identifiers('192.0.2.1', 'admin@example.com', admission_hmac_secret=KEY, key_version=2))
    assert derive_email_identity('admin@example.com', secret=KEY).identity_id not in ids


def test_public_routes_without_admin_configuration(monkeypatch):
    monkeypatch.delenv(NAME, raising=False)
    monkeypatch.setattr('app.config.admin_admission.load_admin_admission_config', Mock(side_effect=AssertionError('Must remain lazy')))
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/').json() == {'status': 'online'}
        assert client.get('/health').status_code == 200
