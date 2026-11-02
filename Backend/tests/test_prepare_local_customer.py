from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
from app.tools import prepare_local_customer as tool
from app.services.kirvano_commercial_service import classify_commercial_event
from test_admin_local import environment


def test_synthetic_payload_matches_existing_contract():
    payload=tool.sale_payload(datetime.now(timezone.utc))
    candidate=classify_commercial_event(payload,timezone_name='UTC').candidate
    assert candidate is not None
    assert candidate.email_normalized=='cliente-teste@example.com'
    assert candidate.valid_from<datetime.now(timezone.utc)<candidate.valid_until


@pytest.mark.parametrize('key,value',[
    ('ADMIN_LOCAL_ENABLED',None),('ADMIN_LOCAL_ENVIRONMENT','production'),
    ('FIRESTORE_EMULATOR_HOST',None),('FIRESTORE_EMULATOR_HOST','remote:8080'),
    ('FIRESTORE_TEST_PROJECT_ID','portaldominandoanimacao-db'),
    ('ADMIN_ADMISSION_HMAC_SECRET',None),
])
def test_fail_before_client_when_not_explicitly_local(monkeypatch,key,value):
    env=environment()
    if value is None:env.pop(key,None)
    else:env[key]=value
    monkeypatch.setattr('os.environ',env)
    client=Mock(side_effect=AssertionError('No network'))
    monkeypatch.setattr(tool,'create_local_client',client)
    with pytest.raises(tool.LocalCustomerError):tool.prepare_customer()
    client.assert_not_called()
