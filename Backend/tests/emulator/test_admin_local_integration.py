"""The actual local factory, anonymous demo emulator, real authentication."""
import pytest
from fastapi.testclient import TestClient
from app.tools import admin_local as local
from test_admin_local import environment
from test_admin_auth_integration import seed, PASSWORD

pytestmark=pytest.mark.firestore_emulator


@pytest.mark.parametrize('role',['owner','operator'])
def test_local_login_session_logout(emulator_client,monkeypatch,role,caplog,capsys):
    seed(emulator_client,role)
    monkeypatch.setattr(local.os,'environ',environment())
    # Exercise production local anonymous client creation, not a Firebase client.
    app=local.create_local_app()
    h={'Origin':local.ORIGIN,'X-Admin-Request':'1'}
    with TestClient(app,base_url='https://localhost:8443',client=('127.0.0.1',1234)) as http:
        assert http.get('/admin/auth/session',headers=h).status_code==401
        bad=http.post('/admin/auth/login',headers=h,json={'email':'admin@example.com','password':'wrong synthetic password'})
        assert bad.status_code==401
        assert list(emulator_client.collection('admin_sessions').stream())==[]
        login=http.post('/admin/auth/login',headers=h,json={'email':'admin@example.com','password':PASSWORD})
        assert login.status_code==200
        cookie=login.headers['set-cookie']
        assert all(flag in cookie for flag in ('__Host-admin_session=', 'Secure', 'HttpOnly', 'SameSite=lax','Path=/'))
        assert 'Domain=' not in cookie
        token=http.cookies.get('__Host-admin_session')
        session=http.get('/admin/auth/session',headers=h)
        assert session.status_code==200 and session.json()['role']==role
        assert 'read_customers' in session.json()['permissions']
        assert http.get('/admin/customers',headers=h).status_code==200
        assert http.post('/admin/auth/logout',headers={'Origin':local.ORIGIN}).status_code==403
        assert http.post('/admin/auth/logout',headers=h).status_code==200
        assert http.get('/admin/auth/session',headers=h).status_code==401
        http.cookies.set('__Host-admin_session',token,domain='localhost.local',path='/')
        assert http.get('/admin/auth/session',headers=h).status_code==401
    out=capsys.readouterr()
    assert PASSWORD not in caplog.text+out.out+out.err
    assert token not in caplog.text+out.out+out.err+login.text+session.text


def test_preparation_is_emulator_only_and_once(emulator_client,monkeypatch):
    monkeypatch.setattr(local.os,'environ',environment())
    local.prepare_owner('synthetic local integration password')
    records=list(emulator_client.collection('admins').stream())
    assert len(records)==1 and records[0].to_dict()['email_normalized']=='local-admin@example.com'
    assert 'synthetic local integration password' not in str(records[0].to_dict())
    with pytest.raises(RuntimeError):local.prepare_owner('another synthetic local password')
    assert len(list(emulator_client.collection('admins').stream()))==1
