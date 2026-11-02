"""Synthetic parsing/startup only; all default Firebase construction forbidden."""
import json
import runpy
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.admin_server import create_app
from app.config.admin_startup import load_admin_startup_settings,AdminStartupConfigurationError
from test_admin_composition import ORIGIN
from test_admin_sessions import sessions
from app.persistence.admin_records import AdminRecord
from app.config.admin_admission_policy import load_admin_admission_policy

API='https://api.example.test'


def environment():
    return {'ADMIN_HTTP_MODE':'public-authenticated','ADMIN_HTTP_ENVIRONMENT':'production',
        'ADMIN_HTTP_ORIGIN':ORIGIN,'ADMIN_API_ORIGIN':API,'FIREBASE_PROJECT_ID':'synthetic-startup-project',
        'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4,
        'ADMIN_ADMISSION_POLICY_CONFIG':json.dumps({'schema_version':1,
            'policy':load_admin_admission_policy(selection='complementary-local-v1').model_dump()})}


@pytest.fixture(autouse=True)
def no_real_firebase(monkeypatch):
    forbidden=Mock(side_effect=AssertionError('Production Firebase forbidden'))
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client',forbidden)


@pytest.mark.parametrize('env',[{}, {'ADMIN_HTTP_MODE':'disabled'}])
def test_disabled_before_file_or_client_access(env,tmp_path):
    provider=Mock()
    entry=create_app(environ=env,env_file=tmp_path/'does-not-exist',firestore_client_factory=provider)
    with TestClient(entry) as http:
        assert http.get('/health').status_code==200
        assert http.get('/admin').status_code==503
        assert http.post('/admin/auth/login').status_code==503
    provider.assert_not_called()


@pytest.mark.parametrize('name',['ADMIN_HTTP_ENVIRONMENT','ADMIN_HTTP_ORIGIN','ADMIN_API_ORIGIN',
    'FIREBASE_PROJECT_ID','ADMIN_ADMISSION_HMAC_SECRET','ADMIN_ADMISSION_POLICY_CONFIG'])
def test_missing_fields_never_construct_client(name):
    env=environment();del env[name]
    provider=Mock()
    entry=create_app(environ=env,env_file=None,firestore_client_factory=provider)
    with TestClient(entry) as http:assert http.get('/admin/auth/session').status_code==503
    provider.assert_not_called()


@pytest.mark.parametrize('name,value',[('ADMIN_HTTP_MODE','true'),('ADMIN_HTTP_ENVIRONMENT','development'),
    ('ADMIN_HTTP_ORIGIN','http://admin.example.test'),('ADMIN_API_ORIGIN','http://api.example.test'),
    ('ADMIN_API_ORIGIN','https://localhost:8443'),('FIREBASE_PROJECT_ID','demo-synthetic-project'),
    ('ADMIN_ADMISSION_HMAC_SECRET','synthetic invalid'),('ADMIN_ADMISSION_POLICY_CONFIG','{}')])
def test_invalid_parsing_is_sanitized(name,value):
    env=environment();env[name]=value
    with pytest.raises(AdminStartupConfigurationError) as caught:load_admin_startup_settings(environ=env,env_file=None)
    assert str(caught.value)=='Administrative startup configuration unavailable.'
    assert value not in str(caught.value)


@pytest.mark.parametrize('name',['FIRESTORE_EMULATOR_HOST','DATASTORE_EMULATOR_HOST','FIRESTORE_TEST_PROJECT_ID'])
@pytest.mark.parametrize('value',['','127.0.0.1:8080'])
def test_reject_emulator_even_empty_or_dotenv(name,value,tmp_path):
    env=environment();env[name]=value
    with pytest.raises(AdminStartupConfigurationError):load_admin_startup_settings(environ=env,env_file=None)
    del env[name]
    path=tmp_path/'.env';path.write_text(name+'='+value+'\n')
    provider=Mock()
    entry=create_app(environ=env,env_file=path,firestore_client_factory=provider)
    assert entry.composition is None
    provider.assert_not_called()


def test_dotenv_cannot_enable_and_process_invalid_does_not_fallback(tmp_path):
    path=tmp_path/'.env';path.write_text('ADMIN_HTTP_MODE=public-authenticated\nADMIN_ADMISSION_HMAC_SECRET='+'a'*64+'\n')
    assert load_admin_startup_settings(environ={},env_file=path) is None
    env=environment();env['ADMIN_ADMISSION_HMAC_SECRET']=''
    with pytest.raises(AdminStartupConfigurationError):load_admin_startup_settings(environ=env,env_file=path)


@pytest.mark.parametrize('binding,value',[('project','another-project'),('project','demo-other-project'),
    ('_database','named'),('_emulator_host','127.0.0.1:8080')])
def test_wrong_client_bindings_disable_without_queries(binding,value):
    client=Mock(project='synthetic-startup-project',_database='(default)',_emulator_host=None)
    setattr(client,binding,value)
    entry=create_app(environ=environment(),env_file=None,firestore_client_factory=lambda:client)
    assert entry.composition is None and client.mock_calls==[]


def test_client_failure_preserves_public_routes_and_sanitizes(monkeypatch,caplog):
    def fail():raise RuntimeError('synthetic private credential value')
    entry=create_app(environ=environment(),env_file=None,firestore_client_factory=fail)
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-token')
    with TestClient(entry) as http:
        assert http.get('/health').status_code==200
        assert http.post('/webhooks/kirvano',json={}).status_code==401
        response=http.get('/admin/auth/session')
        assert response.status_code==503
        assert 'synthetic private' not in response.text+caplog.text


def test_explicit_startup_real_services_with_synthetic_client(sessions,monkeypatch):
    storage,_=sessions
    storage.project='synthetic-startup-project';storage._database='(default)';storage._emulator_host=None
    provider=Mock(return_value=storage)
    entry=create_app(environ=environment(),env_file=None,firestore_client_factory=provider)
    assert entry.composition is not None and len(entry.composition.admission_service.policy.bucket_rules)==4
    entry.composition.login_service.auth_service.repository.find_by_email=Mock(
        return_value=AdminRecord.from_document(storage.data['admins/synthetic-admin']))
    h={'Origin':ORIGIN,'X-Admin-Request':'1','CF-Connecting-IP':'192.0.2.1'}
    with TestClient(entry,base_url=API) as http:
        assert http.get('/admin/auth/session',headers=h).status_code==401
        assert http.options('/admin/auth/login',headers={'Origin':ORIGIN,'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'content-type,x-admin-request'}).status_code==200
        result=http.post('/admin/auth/login',headers=h,json={'email':'admin@example.com','password':'synthetic session admin password'})
        assert result.status_code==200
        assert all(s in result.headers['set-cookie'] for s in ['Secure','HttpOnly','SameSite=lax','Path=/'])
        assert 'Domain=' not in result.headers['set-cookie']
        assert http.get('/admin/auth/session',headers=h).status_code==200
        denied=http.options('/admin/auth/login',headers={'Origin':'https://unapproved.example.test',
            'Access-Control-Request-Method':'POST'})
        assert denied.status_code==400 and 'access-control-allow-origin' not in denied.headers
        with monkeypatch.context() as patch:
            patch.setattr('app.api.admin_dependencies.role_has_permission',lambda *args:False)
            assert http.get('/admin/customers',headers=h).status_code==403
        with monkeypatch.context() as patch:
            patch.setattr(entry.composition.session_service,'validate',Mock(side_effect=RuntimeError('synthetic-private')))
            unavailable=http.get('/admin/auth/session',headers=h)
            assert unavailable.status_code==503 and 'synthetic-private' not in unavailable.text
        assert http.get('/admin/auth/session',headers=h | {'Host':'alternate.example.test'}).status_code==503
        assert http.get('/health',headers=h | {'Host':'alternate.example.test'}).status_code==200
        assert http.post('/admin/auth/logout',headers=h).status_code==200
    provider.assert_called_once_with()


def test_two_buckets_and_schema_drift_rejected():
    env=environment();data=json.loads(env['ADMIN_ADMISSION_POLICY_CONFIG'])
    for field in ['identity','aggregate']:del data['policy'][field]
    env['ADMIN_ADMISSION_POLICY_CONFIG']=json.dumps(data)
    with pytest.raises(AdminStartupConfigurationError):load_admin_startup_settings(environ=env,env_file=None)
    data={'schema_version':2,'policy':{}}
    env['ADMIN_ADMISSION_POLICY_CONFIG']=json.dumps(data)
    with pytest.raises(AdminStartupConfigurationError):load_admin_startup_settings(environ=env,env_file=None)


def test_import_inert_and_main_without_admin(monkeypatch):
    import app.admin_server as module
    forbidden=Mock(side_effect=AssertionError('No configuration on import'))
    monkeypatch.setattr('app.config.admin_startup.load_admin_startup_settings',forbidden)
    runpy.run_path(module.__file__)
    forbidden.assert_not_called()
    from app.main import app
    assert not any(getattr(r,'path','').startswith('/admin') for r in app.routes)
