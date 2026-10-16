"""Test-only routes, origins and headers; no production dependencies."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.admin_request_security import AdminRequestSecurity
from app.config.admin_http_security import AdminRequestSecurityConfig, AdminRequestSecurityConfigurationError

ORIGIN = 'https://admin.example.test'


def app_for(*, json=True):
    app = FastAPI()
    security = AdminRequestSecurity(AdminRequestSecurityConfig((ORIGIN,)), requires_json=json)
    @app.api_route('/operation', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], dependencies=[Depends(security)])
    async def operation():
        return {'ok': True}
    return app


def headers():
    return [('Origin', ORIGIN), ('X-Admin-Request', '1'), ('Content-Type', 'application/json')]


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_legitimate_json_mutation(method):
    with TestClient(app_for()) as client:
        assert client.request(method, '/operation', headers=headers(), content='{}').status_code == 200


@pytest.mark.parametrize('origin', [None, 'null', '*', 'https://unknown.test',
    'https://admin.example.test.evil.test', 'https://eviladmin.example.test',
    'https://admin.example.test@evil.test', 'http://admin.example.test',
    ORIGIN+':444', ORIGIN+'/', ORIGIN+'/path', ORIGIN+'?x=1', ORIGIN+'#x',
    ORIGIN+' https://evil.test', 'https://*.example.test', 'https://ADMIN.example.test',
    'https://admin.example.test:', 'https://admin.example.test:000443'])
def test_origin_rejected(origin):
    h = [(k,v) for k,v in headers() if k != 'Origin']
    if origin is not None: h.append(('Origin', origin))
    with TestClient(app_for()) as client:
        assert client.post('/operation', headers=h, content='{}').status_code == 403


@pytest.mark.parametrize('name,value', [('Origin', ORIGIN), ('origin', 'https://evil.test'),
    ('X-Admin-Request', '1'), ('x-admin-request', 'wrong')])
def test_duplicate_headers(name, value):
    with TestClient(app_for()) as client:
        assert client.post('/operation', headers=headers()+[(name,value)], content='{}').status_code == 403


@pytest.mark.parametrize('value', [None, '', '0', 'secret', '1, 1', ' 1', '1 '])
def test_required_marker(value):
    h = [(k,v) for k,v in headers() if k != 'X-Admin-Request']
    if value is not None: h.append(('X-Admin-Request', value))
    with TestClient(app_for()) as client:
        assert client.post('/operation', headers=h, content='{}').status_code == 403


@pytest.mark.parametrize('value,status', [('application/json',200), ('application/json; charset=utf-8',200),
    ('Application/JSON',200), ('text/plain',415), ('application/x-www-form-urlencoded',415),
    ('multipart/form-data; boundary=x',415), ('application/json, text/plain',415), (None,415)])
def test_content_type(value, status):
    h = [(k,v) for k,v in headers() if k != 'Content-Type']
    if value is not None: h.append(('Content-Type',value))
    with TestClient(app_for()) as client:
        assert client.post('/operation', headers=h, content='{}').status_code == status


def test_duplicate_content_type():
    with TestClient(app_for()) as client:
        assert client.post('/operation', headers=headers()+[('Content-Type','application/json')], content='{}').status_code == 415


def test_logout_without_json_body_still_requires_origin_and_marker():
    with TestClient(app_for(json=False)) as client:
        assert client.post('/operation', headers=headers()[:2]).status_code == 200
        assert client.post('/operation', headers=[('Origin', ORIGIN)]).status_code == 403
        assert client.get('/operation', headers=headers()).status_code == 405


@pytest.mark.parametrize('origins', [(), None, [], ('*',), ('null',), ('http://localhost:5173',),
    (ORIGIN, ORIGIN), (ORIGIN+'/path',), ('https://*.example.test',)])
def test_bad_configuration(origins):
    with pytest.raises(AdminRequestSecurityConfigurationError): AdminRequestSecurityConfig(origins)


def test_exact_https_ports_and_development_profile():
    for origin in ('https://localhost:5173', 'https://admin.example.test:8443', 'https://[::1]:5173'):
        config = AdminRequestSecurityConfig((origin,))
        assert config.allowed_origins == (origin,)


def test_sanitized_and_cookie_not_authentication(caplog, capsys):
    private = 'synthetic-private-token'
    with TestClient(app_for()) as client:
        response = client.post('/operation', headers={'Origin': 'https://evil.test',
            'Cookie': '__Host-admin_session='+private, 'X-Admin-Request': private})
    output = capsys.readouterr()
    assert response.status_code == 403
    assert private not in response.text+caplog.text+output.out+output.err


def test_public_routes_and_kirvano_unchanged(monkeypatch):
    from app.main import app
    monkeypatch.setattr('app.api.kirvano.load_dotenv', lambda *a, **k: None)
    monkeypatch.setenv('KIRVANO_WEBHOOK_TOKEN', 'synthetic-webhook-test')
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.post('/webhooks/kirvano', json={}).status_code == 401
        assert client.post('/admin/auth/login').status_code == 404


def test_missing_dependency_config_is_sanitized():
    with pytest.raises(AdminRequestSecurityConfigurationError): AdminRequestSecurity(None)
    with pytest.raises(AdminRequestSecurityConfigurationError):
        AdminRequestSecurity(AdminRequestSecurityConfig((ORIGIN,)), requires_json='false')
