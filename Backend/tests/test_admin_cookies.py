"""Cookie response transport with synthetic sessions; no real credentials."""
import copy
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.responses import JSONResponse

from app.api.admin_cookies import issue_admin_session_cookie, remove_admin_session_cookie, AdminCookieError
from app.api.admin_dependencies import ADMIN_SESSION_COOKIE_NAME as NAME, AdminHTTPAuthentication
from app.domain.admin import AdminSession
from app.services.admin_session_service import IssuedAdminSession, AdminSessionServiceError
from test_admin_domain import START, admin
from test_admin_sessions import sessions

TOKEN = 'a'*64


def issued():
    return IssuedAdminSession(SecretStr(TOKEN), AdminSession(admin_id='synthetic-admin',
        auth_version_at_issue=1, authentication_method='password', created_at=START, expires_at=START+timedelta(hours=8)))


def cookie(response):
    parsed = SimpleCookie()
    parsed.load(response.headers['set-cookie'])
    return parsed[NAME]


def assert_security(value):
    assert value['secure'] and value['httponly']
    assert value['samesite'] == 'lax' and value['path'] == '/'
    assert value['domain'] == ''


@pytest.mark.parametrize('elapsed,expected', [(0,28800), (3600,25200), (0.9,28799), (28799,1)])
def test_issue_attributes_remaining_lifetime(elapsed, expected, caplog, capsys):
    response = JSONResponse({'ok': True})
    issue_admin_session_cookie(response, issued(), now=START+timedelta(seconds=elapsed))
    value = cookie(response)
    assert value.value == TOKEN
    assert_security(value)
    assert int(value['max-age']) == expected
    assert parsedate_to_datetime(value['expires']) <= issued().session.expires_at
    assert response.headers['cache-control'] == 'no-store'
    output = capsys.readouterr()
    assert TOKEN not in response.body.decode()+output.out+output.err+caplog.text


@pytest.mark.parametrize('now', [START+timedelta(hours=8), START+timedelta(hours=9),
    START-timedelta(seconds=1), START.replace(tzinfo=None), 'invalid', START+timedelta(hours=8, microseconds=-1)])
def test_reject_bad_time_without_emitting_cookie(now):
    response = JSONResponse({})
    with pytest.raises(AdminCookieError): issue_admin_session_cookie(response, issued(), now=now)
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('kind', ['bad_token', 'plain_token', 'revoked', 'bad_dates', 'wrong_type'])
def test_invalid_issuance_is_sanitized(kind):
    value = issued()
    if kind == 'bad_token': value = IssuedAdminSession(SecretStr('private-invalid'), value.session)
    elif kind == 'plain_token': value = IssuedAdminSession(TOKEN, value.session)
    elif kind == 'revoked': value = IssuedAdminSession(value.token, value.session.model_copy(update={'revoked_at': START}))
    elif kind == 'bad_dates': value = IssuedAdminSession(value.token, value.session.model_copy(update={'expires_at': START+timedelta(hours=9)}))
    else: value = None
    response = JSONResponse({})
    with pytest.raises(AdminCookieError) as caught: issue_admin_session_cookie(response, value, now=START)
    assert str(caught.value) == 'Administrative cookie operation unavailable.'
    assert caught.value.__cause__ is None and 'set-cookie' not in response.headers


def test_removal_immediate_and_preserves_unrelated_cookie():
    response = JSONResponse({'ok': True})
    response.set_cookie('portal-user', 'synthetic-user')
    remove_admin_session_cookie(response)
    values = response.headers.getlist('set-cookie')
    assert len(values) == 2 and 'portal-user=synthetic-user' in values[0]
    parsed = SimpleCookie()
    parsed.load(values[1])
    value = parsed[NAME]
    assert_security(value)
    assert value.value == '' and int(value['max-age']) == 0
    assert parsedate_to_datetime(value['expires']) <= datetime.now(timezone.utc)
    assert response.headers['cache-control'] == 'no-store'


def test_existing_session_not_modified_or_revoked_by_cookie_transport(sessions):
    storage, service = sessions
    result = service.create(admin(), now=START)
    before = copy.deepcopy(storage.data)
    response = JSONResponse({})
    issue_admin_session_cookie(response, result, now=START+timedelta(hours=1))
    remove_admin_session_cookie(response)
    assert storage.data == before
    assert service.validate(result.token.get_secret_value(), now=START+timedelta(hours=1)) == admin()


def test_https_cookie_compatible_with_http_authentication():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    result = IssuedAdminSession(SecretStr(TOKEN), issued().session.model_copy(update={
        'created_at': now, 'expires_at': now+timedelta(hours=8)}))
    service = Mock()
    service.validate.return_value = admin()
    app = FastAPI()
    @app.get('/issue')
    async def issue():
        response = JSONResponse({'ok': True})
        issue_admin_session_cookie(response, result)
        return response
    @app.get('/protected')
    async def protected(administrator=Depends(AdminHTTPAuthentication(service))):
        return {'id': administrator.admin_id}
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get('/issue').status_code == 200
        response = client.get('/protected')
        assert response.status_code == 200 and 'set-cookie' not in response.headers
    service.validate.assert_called_once_with(TOKEN)


def test_failed_revocation_is_not_logout_confirmation():
    service = Mock()
    service.revoke.side_effect = AdminSessionServiceError('Session revocation failed.')
    response = JSONResponse({})
    # Contract for the FUTURE caller: failure propagates before clearing cookie.
    with pytest.raises(AdminSessionServiceError):
        service.revoke(TOKEN)
        remove_admin_session_cookie(response)
    assert 'set-cookie' not in response.headers


def test_timezone_offset_and_existing_cookie_on_issuance():
    response = JSONResponse({})
    response.set_cookie('portal-user', 'synthetic-user')
    now = START.astimezone(timezone(timedelta(hours=-3)))+timedelta(minutes=30)
    issue_admin_session_cookie(response, issued(), now=now)
    assert len(response.headers.getlist('set-cookie')) == 2
    assert 'portal-user=synthetic-user' in response.headers.getlist('set-cookie')[0]
    parsed = SimpleCookie()
    parsed.load(response.headers.getlist('set-cookie')[1])
    assert int(parsed[NAME]['max-age']) == 27000
