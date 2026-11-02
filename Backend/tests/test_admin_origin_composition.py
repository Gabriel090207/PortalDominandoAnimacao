"""Local synthetic wiring only. A test switch NEVER attests Render ingress."""
import copy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.admin_origin import resolve_cf_connecting_ip, AdminOriginResolutionError
from test_admin_composition import compose, app_for, ORIGIN
from test_admin_sessions import sessions


def synthetic_origin(*, boundary_approved=False):
    """Test-only injection; not an environment flag or production provider.

    Approval here is a fixture assumption, NOT inferred from any HTTP header.
    Keep production login unavailable pending explicit ingress approval.
    """
    def resolve(request):
        if not boundary_approved:
            raise AdminOriginResolutionError()
        return resolve_cf_connecting_ip(request.scope['headers'])
    return resolve



@pytest.fixture
def origin_composition(sessions):
    # Existing session storage fake has point reads/transactions, not queries.
    # Mock only indexed admin lookup; keep Argon2, admission and sessions real.
    from app.persistence.admin_records import AdminRecord
    storage, _ = sessions
    composition = compose(storage, trusted_origin_dependency=synthetic_origin(boundary_approved=True))
    record = AdminRecord.from_document(storage.data['admins/synthetic-admin'])
    composition.login_service.auth_service.repository.find_by_email = Mock(return_value=record)
    return storage, composition


def login(http, extra=(), password='incorrect synthetic password', origin=ORIGIN):
    return http.post('/admin/auth/login', headers=[('Origin', origin),
        ('X-Admin-Request', '1'), *extra],
        json={'email': 'admin@example.com', 'password': password})


@pytest.mark.parametrize('extra', [[], [('CF-Connecting-IP', '')],
    [('CF-Connecting-IP', 'invalid')], [('CF-Connecting-IP', '192.0.2.1, 192.0.2.2')],
    [('CF-Connecting-IP', '192.0.2.1'), ('cf-connecting-ip', '192.0.2.1')],
    [('CF-Connecting-IP', '192.0.2.1'), ('CF-Connecting-IP', '192.0.2.2')],
    [('CF-Connecting-IP', '192.0.2. 1')], [('CF-Connecting-IP', 'fe80::1%eth0')],
    [('CF-Connecting-IP', '192.0.2.1\r\nX-Injected: value')],
    [('X-Forwarded-For', '192.0.2.1'), ('X-Real-IP', '192.0.2.1')]])
def test_resolution_failure_never_reaches_admission_or_auth(extra):
    storage = Mock()
    composition = compose(storage, trusted_origin_dependency=synthetic_origin(boundary_approved=True))
    composition.login_service.authenticate = Mock(side_effect=AssertionError('Must not authenticate'))
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        response = login(http, extra)
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers
    composition.login_service.authenticate.assert_not_called()
    assert storage.mock_calls == []


def test_valid_forged_header_does_not_approve_boundary():
    storage = Mock()
    composition = compose(storage, trusted_origin_dependency=synthetic_origin())
    with TestClient(app_for(composition)) as http:
        response = login(http, [('CF-Connecting-IP', '192.0.2.66'),
            ('X-Forwarded-For', '192.0.2.66'), ('RENDER', 'true'), ('X-Boundary-Approved', 'true')])
    assert response.status_code == 503
    assert storage.mock_calls == []


@pytest.mark.parametrize('value', ['192.0.2.1', '2001:db8::1',
    '2001:0DB8:0:0:0:0:0:1', '::ffff:192.0.2.1', ' \t192.0.2.1\t '])
def test_parser_wiring_uses_canonical_cf_not_rewritten_peer(origin_composition, value):
    storage, composition = origin_composition
    authenticate = Mock(wraps=composition.login_service.authenticate)
    composition.login_service.authenticate = authenticate
    app = ProxyHeadersMiddleware(app_for(composition), trusted_hosts='*')
    with TestClient(app, base_url='https://testserver') as http:
        response = login(http, [('cF-CoNnEcTiNg-Ip', value), ('X-Forwarded-For', '198.51.100.66')])
    assert response.status_code == 401
    expected = '2001:db8::1' if value.startswith('2001') else '192.0.2.1'
    assert authenticate.call_args.args[0] == expected
    assert len([p for p in storage.data if p.startswith('auth_throttles/')]) == 2
    assert not any(p.startswith('admin_sessions/') for p in storage.data)


def test_same_canonical_origin_keeps_budget_despite_forged_xff(origin_composition):
    storage, composition = origin_composition
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        for i in range(5):
            assert login(http, [('CF-Connecting-IP', '192.0.2.1'),
                ('X-Forwarded-For', f'198.51.100.{i+1}')]).status_code == 401
        before = copy.deepcopy(storage.data)
        assert login(http, [('CF-Connecting-IP', '::ffff:192.0.2.1')]).status_code == 429
        assert storage.data == before
        # This fixture explicitly ASSUMES ingress approval. A parser alone
        # cannot distinguish a forged replacement CF value: no security claim.
        assert login(http, [('CF-Connecting-IP', '192.0.2.2')]).status_code == 401
    assert len([p for p in storage.data if p.startswith('auth_throttles/')]) == 4


def test_admission_outage_blocks_real_authentication(origin_composition):
    storage, composition = origin_composition
    composition.admission_service.repository.admit = Mock(side_effect=RuntimeError('synthetic private detail'))
    composition.login_service.auth_service.authenticate = Mock()
    with TestClient(app_for(composition)) as http:
        response = login(http, [('CF-Connecting-IP', '192.0.2.1')])
    assert response.status_code == 503
    assert 'synthetic private detail' not in response.text
    composition.login_service.auth_service.authenticate.assert_not_called()
    assert not any(p.startswith('admin_sessions/') for p in storage.data)


def test_real_login_session_logout_and_csrf_preserved(origin_composition, caplog, capsys):
    storage, composition = origin_composition
    with TestClient(app_for(composition), base_url='https://testserver') as http:
        extra = [('CF-Connecting-IP', '192.0.2.1')]
        before = copy.deepcopy(storage.data)
        assert login(http, extra, origin='https://attacker.example.test').status_code == 403
        assert storage.data == before
        response = login(http, extra, password='synthetic session admin password')
        assert response.status_code == 200
        token = http.cookies.get('__Host-admin_session')
        assert token and token not in response.text and token not in str(storage.data)
        security = {'Origin': ORIGIN, 'X-Admin-Request': '1'}
        assert http.get('/admin/auth/session', headers=security).status_code == 200
        assert http.post('/admin/auth/logout', headers={'Origin': ORIGIN}).status_code == 403
        assert http.get('/admin/auth/session', headers=security).status_code == 200
        assert http.post('/admin/auth/logout', headers=security).status_code == 200
        assert composition.session_service.validate(token) is None
        assert http.get('/admin/auth/session', headers=security).status_code == 401
    output = capsys.readouterr()
    assert token not in output.out + output.err + caplog.text
    assert 'synthetic session admin password' not in output.out + output.err + caplog.text
