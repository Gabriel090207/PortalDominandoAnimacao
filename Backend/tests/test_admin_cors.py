"""One outer CORS layer on isolated apps; main remains unchanged."""
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.api.admin_auth import create_admin_auth_router
from app.config.admin_cors import admin_cors_options
from app.config.admin_http_security import AdminRequestSecurityConfig, AdminRequestSecurityConfigurationError
from app.services.admin_auth_service import InvalidAdminCredentials, AdminAuthenticationUnavailable
from app.services.admin_login_service import AdminLoginLimited
from test_admin_login_endpoint import issued, PASSWORD, TOKEN
from test_admin_domain import admin

ORIGIN = 'https://admin.example.test'
CONFIG = AdminRequestSecurityConfig((ORIGIN,))


def application():
    sessions, login = Mock(), Mock()
    sessions.validate.return_value = admin()
    sessions.revoke.return_value = True
    login.authenticate.side_effect = lambda *args: issued()
    app = FastAPI()
    app.include_router(create_admin_auth_router(session_service=sessions,login_service=login,
        security_config=CONFIG,trusted_origin_dependency=lambda request:'192.0.2.1'))
    return app,sessions,login


def client_for(app):
    return TestClient(CORSMiddleware(app,**admin_cors_options(CONFIG)),base_url='https://testserver',raise_server_exceptions=False)


def h(): return {'Origin':ORIGIN,'X-Admin-Request':'1'}


def assert_cors(response,status,no_store=True):
    assert response.status_code == status
    assert response.headers['access-control-allow-origin'] == ORIGIN
    assert response.headers['access-control-allow-credentials'] == 'true'
    assert 'origin' in response.headers['vary'].lower()
    if no_store: assert response.headers['cache-control'] == 'no-store'
    assert TOKEN not in response.text and PASSWORD not in response.text


def test_options_are_explicit_minimal_and_independent():
    options = admin_cors_options(CONFIG)
    assert options == {'allow_origins':(ORIGIN,), 'allow_credentials':True,'allow_methods':('GET','POST'),
        'allow_headers':('Content-Type','X-Admin-Request'),'expose_headers':('Retry-After',)}
    options['allow_origins'] = ('https://other.test',)
    assert admin_cors_options(CONFIG)['allow_origins'] == (ORIGIN,)


@pytest.mark.parametrize('config',[None,{},'*'])
def test_invalid_configuration(config):
    with pytest.raises(AdminRequestSecurityConfigurationError): admin_cors_options(config)


@pytest.mark.parametrize('path,method',[('/admin/auth/login','POST'),('/admin/auth/logout','POST'),('/admin/auth/session','GET')])
def test_preflight_no_services(path,method):
    app,sessions,login = application()
    with client_for(app) as client:
        response = client.options(path,headers={'Origin':ORIGIN,'Access-Control-Request-Method':method,
            'Access-Control-Request-Headers':'content-type,x-admin-request'})
    assert_cors(response,200,no_store=False)
    assert response.headers['access-control-allow-methods'] == 'GET, POST'
    permitted = {v.strip().lower() for v in response.headers['access-control-allow-headers'].split(',')}
    assert {'content-type','x-admin-request'} <= permitted
    assert 'authorization' not in permitted
    assert sessions.mock_calls == login.mock_calls == []


@pytest.mark.parametrize('origin',['https://unknown.test',ORIGIN+'.evil.test','https://sub.admin.example.test',
    ORIGIN+':444','http://admin.example.test'])
def test_disallowed_origins(origin):
    app,sessions,login = application()
    with client_for(app) as client:
        preflight = client.options('/admin/auth/login',headers={'Origin':origin,'Access-Control-Request-Method':'POST'})
        actual = client.post('/admin/auth/login',headers={'Origin':origin,'X-Admin-Request':'1'},json={'email':'x','password':PASSWORD})
    assert preflight.status_code == 400 and actual.status_code == 403
    assert 'access-control-allow-origin' not in preflight.headers
    assert 'access-control-allow-origin' not in actual.headers
    assert actual.headers['cache-control'] == 'no-store'
    assert sessions.mock_calls == login.mock_calls == []


@pytest.mark.parametrize('method,header',[('DELETE','content-type'),('POST','authorization'),('PUT','x-extra')])
def test_preflight_rejects_unneeded_methods_headers(method,header):
    app,sessions,login = application()
    with client_for(app) as client:
        response = client.options('/admin/auth/login',headers={'Origin':ORIGIN,'Access-Control-Request-Method':method,
            'Access-Control-Request-Headers':header})
    assert response.status_code == 400
    assert sessions.mock_calls == login.mock_calls == []


def test_full_cookie_flow():
    app,sessions,login = application()
    with client_for(app) as client:
        response = client.post('/admin/auth/login',headers=h(),json={'email':'admin@example.com','password':PASSWORD})
        assert_cors(response,200)
        cookie = response.headers['set-cookie']
        assert all(v in cookie for v in ('Secure','HttpOnly','SameSite=lax','Path=/')) and 'Domain=' not in cookie
        assert_cors(client.get('/admin/auth/session',headers=h()),200)
        logout = client.post('/admin/auth/logout',headers=h())
        assert_cors(logout,200)
        assert 'Max-Age=0' in logout.headers['set-cookie']
    login.authenticate.assert_called_once()
    sessions.validate.assert_called_once_with(TOKEN)
    sessions.revoke.assert_called_once_with(TOKEN)


@pytest.mark.parametrize('status',[400,401,403,413,415,429,503])
def test_errors_keep_cors_and_no_store(status):
    app,sessions,login = application()
    request_headers = h()
    body = '{' if status == 400 else '{}' if status == 403 else 'x'*4097 if status == 413 else '{"email":"x","password":"synthetic"}'
    request_headers['Content-Type'] = 'text/plain' if status == 415 else 'application/json'
    if status == 403: del request_headers['X-Admin-Request']
    if status in (401,429,503):
        error = InvalidAdminCredentials() if status == 401 else AdminLoginLimited(60) if status == 429 else AdminAuthenticationUnavailable()
        login.authenticate.side_effect = error
    with client_for(app) as client:
        response = client.post('/admin/auth/login',headers=request_headers,content=body)
    assert_cors(response,status)
    assert 'set-cookie' not in response.headers
    if status == 429:
        assert response.headers['retry-after'] == '60'
        assert 'retry-after' in response.headers['access-control-expose-headers'].lower()


def test_inner_cors_500_limitation_and_outer_fix():
    def error_app():
        app = FastAPI()
        @app.get('/unexpected')
        async def unexpected(): raise RuntimeError('synthetic-private')
        return app
    inner = error_app()
    inner.add_middleware(CORSMiddleware,**admin_cors_options(CONFIG))
    with TestClient(inner,raise_server_exceptions=False) as client:
        response = client.get('/unexpected',headers=h())
    assert response.status_code == 500 and 'access-control-allow-origin' not in response.headers
    with client_for(error_app()) as client:
        outer = client.get('/unexpected',headers=h())
    assert_cors(outer,500,no_store=False)
    assert 'synthetic-private' not in outer.text
    # CORS itself does not set cache policy for errors outside the admin router.
    assert 'cache-control' not in outer.headers


def test_outer_500_with_explicit_no_store_error_handler():
    app = FastAPI()
    @app.exception_handler(Exception)
    async def safe_error(request,error):
        return JSONResponse({'detail':'Service unavailable.'},status_code=500,headers={'Cache-Control':'no-store'})
    @app.get('/unexpected')
    async def unexpected(): raise RuntimeError('synthetic-private')
    with client_for(app) as client:
        assert_cors(client.get('/unexpected',headers=h()),500)


def test_actual_method_and_csrf_not_replaced_by_cors():
    app,_,login = application()
    with client_for(app) as client:
        assert_cors(client.delete('/admin/auth/login',headers=h()),405)
        assert_cors(client.post('/admin/auth/login',headers={'Origin':ORIGIN},json={}),403)
    login.authenticate.assert_not_called()


def test_main_cors_unchanged_and_no_admin(monkeypatch):
    from app.main import app
    cors = [item for item in app.user_middleware if item.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs['allow_origins'] == ['http://localhost:5173','https://portaldominandoanimacao.netlify.app']
    assert cors[0].kwargs['allow_methods'] == ['*'] and cors[0].kwargs['allow_headers'] == ['*']
    monkeypatch.setattr('app.api.kirvano.load_dotenv',lambda *a,**k:None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN','synthetic-webhook')
    with TestClient(app) as client:
        assert client.get('/admin/auth/session').status_code == 404
        assert client.get('/health').status_code == 200
        assert client.post('/webhooks/kirvano',json={}).status_code == 401
