"""Explicit composition end to end, only guarded local demo emulator clients."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from test_admin_auth_integration import seed, PASSWORD

pytestmark = pytest.mark.firestore_emulator
KEY = '0123456789abcdef'*4
ORIGIN = 'https://admin.example.test'


@pytest.mark.parametrize('role',['owner','operator'])
def test_composed_login_session_logout(emulator_client,role,caplog,capsys):
    seed(emulator_client,role)
    config = load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':KEY},env_file=None)
    composition = compose_admin_http(firestore_client=emulator_client,admission_config=config,
        security_config=AdminRequestSecurityConfig((ORIGIN,)),
        trusted_origin_dependency=lambda request:'192.0.2.1')
    app = FastAPI()
    app.include_router(composition.router)
    h = {'Origin':ORIGIN,'X-Admin-Request':'1'}
    login_service = composition.login_service
    with TestClient(app,base_url='https://testserver') as http:
        login = http.post('/admin/auth/login',headers=h,json={'email':' ADMIN@EXAMPLE.COM ','password':PASSWORD})
        assert login.status_code == 200
        token = http.cookies.get('__Host-admin_session')
        assert token and token not in login.text
        before = list(emulator_client.collection('admin_sessions').stream(timeout=5))
        assert len(before) == 1
        expiry = before[0].to_dict()['expires_at']
        for _ in range(2):
            response = http.get('/admin/auth/session',headers=h)
            assert response.status_code == 200 and response.json()['role'] == role
            assert response.headers['cache-control'] == 'no-store'
            assert 'set-cookie' not in response.headers
        records = list(emulator_client.collection('admin_sessions').stream(timeout=5))
        assert len(records) == 1 and records[0].to_dict()['expires_at'] == expiry
        assert composition.login_service is login_service
        logout = http.post('/admin/auth/logout',headers=h)
        assert logout.status_code == 200 and logout.json() == {'success':True}
        assert composition.session_service.validate(token) is None
        assert http.get('/admin/auth/session',headers=h).status_code == 401
        assert len(list(emulator_client.collection('admin_sessions').stream(timeout=5))) == 1
    output = capsys.readouterr()
    assert all(value not in output.out+output.err+caplog.text+login.text+response.text+logout.text
               for value in (KEY,PASSWORD,token))
