"""Local entry point gates, without Firebase or network access."""
from unittest.mock import Mock
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from app.tools import admin_local as local


def environment():
    return {'ADMIN_LOCAL_ENABLED':'true', 'ADMIN_LOCAL_ENVIRONMENT':'development',
        'FIRESTORE_EMULATOR_HOST':local.EMULATOR, 'FIRESTORE_TEST_PROJECT_ID':local.PROJECT,
        'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4}


@pytest.mark.parametrize('key,value',[
    ('ADMIN_LOCAL_ENABLED',None), ('ADMIN_LOCAL_ENABLED','false'),
    ('ADMIN_LOCAL_ENVIRONMENT','production'), ('FIRESTORE_EMULATOR_HOST',None),
    ('FIRESTORE_EMULATOR_HOST','remote:8080'),
    ('FIRESTORE_TEST_PROJECT_ID','portaldominandoanimacao-db'),
    ('DATASTORE_EMULATOR_HOST','remote:8080'),
    ('ADMIN_ADMISSION_HMAC_SECRET',None), ('ADMIN_ADMISSION_HMAC_SECRET','invalid'),
])
def test_invalid_environment_before_client(monkeypatch,key,value):
    env=environment()
    if value is None:env.pop(key,None)
    else:env[key]=value
    monkeypatch.setattr(local.os,'environ',env)
    client=Mock(side_effect=AssertionError('No client allowed'))
    monkeypatch.setattr(local,'create_local_client',client)
    with pytest.raises(RuntimeError):local.create_local_app()
    client.assert_not_called()


def test_valid_environment():
    assert local.require_local_environment(environment()).key_version==1


@pytest.mark.parametrize('peer,expected',[('127.0.0.1',True),('::1',True),('192.0.2.1',False)])
def test_transport_peer_ignores_forged_headers(peer,expected):
    request=Request({'type':'http','client':(peer,1234),'headers':[
        (b'cf-connecting-ip',b'203.0.113.1'),(b'x-forwarded-for',b'127.0.0.1')]})
    if expected:assert local.local_connection_origin(request)==peer
    else:
        with pytest.raises(local.LocalAdminError):local.local_connection_origin(request)


def test_isolated_routes_and_boundary(monkeypatch):
    monkeypatch.setattr(local.os,'environ',environment())
    client=Mock()
    monkeypatch.setattr(local,'create_local_client',lambda:client)
    app=local.create_local_app()
    from app.main import app as public
    assert not any(path.startswith('/admin') for path in public.openapi()['paths'])
    assert '/admin/auth/login' in app.openapi()['paths']
    with TestClient(app,base_url='https://localhost:8443',client=('127.0.0.1',1234)) as http:
        assert http.get('/admin/auth/session',headers={'Origin':local.ORIGIN}).status_code==401
        assert http.get('/admin/auth/session',headers={'Origin':'https://evil.example'}).status_code==403
        assert http.get('/admin/auth/session',headers={'Host':'evil.example'}).status_code==403
        assert http.get('http://localhost:8443/admin/auth/session').status_code==403
        assert http.post('/admin/auth/login',headers={'Origin':local.ORIGIN},json={}).status_code==403
        preflight=http.options('/admin/auth/login',headers={'Origin':local.ORIGIN,
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Admin-Request,Content-Type'})
        assert preflight.status_code==200
        assert preflight.headers['access-control-allow-origin']==local.ORIGIN
        # Infrastructure failure with a syntactically valid token is not 200/401.
        def unavailable(*args):
            raise RuntimeError('synthetic internal storage detail')
        monkeypatch.setattr('app.services.admin_session_service.AdminSessionService.validate',unavailable)
        failure=http.get('/admin/auth/session',headers={'Origin':local.ORIGIN,
            'Cookie':'__Host-admin_session='+'a'*64})
        assert failure.status_code==503
        assert 'synthetic internal storage detail' not in failure.text
        assert 'a'*64 not in failure.text
    client.close.assert_called_once()


def test_runner_pins_loopback_tls_and_disables_forwarded_headers(monkeypatch):
    env=environment() | {'ADMIN_LOCAL_TLS_CERT':'synthetic-cert-path',
                         'ADMIN_LOCAL_TLS_KEY':'synthetic-key-path'}
    monkeypatch.setattr(local.os,'environ',env)
    monkeypatch.setattr('sys.argv',['admin_local'])
    tls=Mock()
    monkeypatch.setattr(local.ssl,'SSLContext',lambda protocol:tls)
    app=Mock()
    monkeypatch.setattr(local,'create_local_app',lambda:app)
    run=Mock()
    monkeypatch.setattr('uvicorn.run',run)
    local.main()
    tls.load_cert_chain.assert_called_once_with('synthetic-cert-path','synthetic-key-path')
    run.assert_called_once_with(app,host='127.0.0.1',port=8443,proxy_headers=False,
        ssl_certfile='synthetic-cert-path',ssl_keyfile='synthetic-key-path',access_log=False)


def test_invalid_tls_does_not_initialize_application(monkeypatch):
    monkeypatch.setattr(local.os,'environ',environment() | {
        'ADMIN_LOCAL_TLS_CERT':'nonexistent-synthetic-cert',
        'ADMIN_LOCAL_TLS_KEY':'nonexistent-synthetic-key'})
    monkeypatch.setattr('sys.argv',['admin_local'])
    app=Mock()
    monkeypatch.setattr(local,'create_local_app',app)
    with pytest.raises(SystemExit,match='Local administrative environment unavailable'):
        local.main()
    app.assert_not_called()
