"""Explicit composition only, with synthetic config and isolated storage."""
import runpy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_composition import compose_admin_http, AdminCompositionError
from app.config.admin_admission import load_admin_admission_config, AdminAdmissionConfig
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from test_admin_sessions import sessions

KEY = '0123456789abcdef'*4
ORIGIN = 'https://admin.example.test'


def config():
    return load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':KEY},env_file=None)


def compose(client, **changes):
    parameters = dict(firestore_client=client,admission_config=config(),
        security_config=AdminRequestSecurityConfig((ORIGIN,)),trusted_origin_dependency=lambda request:'192.0.2.1')
    return compose_admin_http(**(parameters | changes))


def app_for(composition):
    app = FastAPI()
    app.include_router(composition.router)
    return app


def test_services_shared_without_database_operations(monkeypatch):
    client = Mock()
    composition = compose(client)
    assert client.mock_calls == []
    assert composition.session_service.repository.client is client
    assert composition.admission_service.repository.client is client
    assert composition.login_service.auth_service.repository.client is client
    assert composition.login_service.auth_service.session_service is composition.session_service
    assert composition.login_service.admission_service is composition.admission_service
    assert composition.admission_service.policy == INITIAL_ADMIN_ADMISSION_POLICY
    assert composition.admission_service._secret == KEY  # Same UTF-8 text; not hex-decoded.
    assert composition.admission_service._key_version == 1
    assert KEY not in repr(composition)


def test_import_is_inert(monkeypatch):
    import app.admin_composition as module
    forbidden = Mock(side_effect=AssertionError('No automatic initialization'))
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)
    monkeypatch.setattr('app.config.admin_admission.load_admin_admission_config',forbidden)
    runpy.run_path(module.__file__)
    forbidden.assert_not_called()


@pytest.mark.parametrize('changes',[{'admission_config':None},{'security_config':None},
    {'firestore_client':None},{'clock':None},{'trusted_origin_dependency':'CF-Connecting-IP'},
    {'policy':None}])
def test_invalid_config_fails_before_storage(changes):
    client = Mock()
    with pytest.raises(AdminCompositionError) as caught: compose(client,**changes)
    assert KEY not in str(caught.value) and caught.value.__cause__ is None
    assert client.mock_calls == []


def test_missing_origin_no_fallback():
    client = Mock()
    composition = compose(client,trusted_origin_dependency=None)
    with TestClient(app_for(composition)) as http:
        response = http.post('/admin/auth/login',headers={'Origin':ORIGIN,'X-Admin-Request':'1',
            'CF-Connecting-IP':'192.0.2.2','X-Forwarded-For':'192.0.2.2'},json={'email':'x','password':'synthetic password'})
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers
    assert client.mock_calls == []


def test_session_logout_reuse_and_no_renewal(sessions):
    storage, _ = sessions
    composition = compose(storage)
    from test_admin_domain import admin
    issued = composition.session_service.create(admin())
    token = issued.token.get_secret_value()
    session_before = issued.session
    h = {'Origin':ORIGIN,'X-Admin-Request':'1','Cookie':'__Host-admin_session='+token}
    with TestClient(app_for(composition)) as http:
        for _ in range(2):
            response = http.get('/admin/auth/session',headers=h)
            assert response.status_code == 200
            assert 'set-cookie' not in response.headers
        assert composition.session_service.get_session(token) == session_before
        assert http.post('/admin/auth/logout',headers=h).json() == {'success':True}
        assert http.get('/admin/auth/session',headers=h).status_code == 401
    assert len([key for key in storage.data if key.startswith('admin_sessions/')]) == 1
    assert composition.session_service.validate(token) is None


def test_separate_apps_configs_do_not_mix():
    first, second = compose(Mock()), compose(Mock(),security_config=AdminRequestSecurityConfig(('https://other.example.test',)))
    assert first.session_service is not second.session_service
    with TestClient(app_for(second)) as http:
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code == 403
    with TestClient(app_for(first)) as http:
        assert http.get('/admin/auth/session',headers={'Origin':ORIGIN}).status_code == 401


def test_corrupt_hmac_configuration_rejected():
    from pydantic import SecretStr
    bad = object.__new__(AdminAdmissionConfig)
    object.__setattr__(bad,'secret',SecretStr('invalid-synthetic'))
    object.__setattr__(bad,'key_version',1)
    client = Mock()
    with pytest.raises(AdminCompositionError): compose(client,admission_config=bad)
    assert client.mock_calls == []


def test_public_main_still_independent(monkeypatch):
    monkeypatch.delenv('ADMIN_ADMISSION_HMAC_SECRET',raising=False)
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-webhook')
    with TestClient(app) as http:
        assert http.get('/health').status_code == 200
        assert http.get('/admin/auth/session').status_code == 404
        assert http.post('/admin/auth/login').status_code == 404
        assert http.post('/admin/auth/logout').status_code == 404
        assert http.post('/webhooks/kirvano',json={}).status_code == 401
