import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.api.kirvano import MAX_BODY_BYTES


class KirvanoDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict('os.environ', {'KIRVANO_WEBHOOK_TOKEN':'test-configured-secret'})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        loader = patch('app.api.kirvano.load_dotenv')
        loader.start()
        self.addCleanup(loader.stop)
        from app.domain.kirvano_event import ReceiptResult
        from app.domain.states import KirvanoEventState
        recorder = patch('app.api.kirvano.register_event', return_value=ReceiptResult('a'*64, KirvanoEventState.REVIEW_REQUIRED, 'review_required'))
        self.recorder = recorder.start()
        self.addCleanup(recorder.stop)
        self.client = TestClient(app, headers={'security-token':'test-configured-secret'})

    def test_valid_json(self):
        for payload in [{'test':True}, [], 'test', None]:
            response=self.client.post('/webhooks/kirvano',content=json.dumps(payload),headers={'content-type':'application/json'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),{'received':True})

    def test_invalid_json(self):
        for body in ['{', 'NaN', '']:
            self.assertEqual(self.client.post('/webhooks/kirvano',content=body,headers={'content-type':'application/json'}).status_code,400)

    def test_content_type(self):
        self.assertEqual(self.client.post('/webhooks/kirvano',content='{}').status_code,415)
        self.assertEqual(self.client.post('/webhooks/kirvano',content='{}',headers={'content-type':'text/plain'}).status_code,415)
        self.assertEqual(self.client.post('/webhooks/kirvano',content='{}',headers={'content-type':'application/test+json; charset=utf-8'}).status_code,200)

    def test_size_and_get(self):
        self.assertEqual(self.client.post('/webhooks/kirvano',content=b' '* (MAX_BODY_BYTES+1),headers={'content-type':'application/json'}).status_code,413)
        self.assertEqual(self.client.get('/webhooks/kirvano').status_code,405)

    def test_logs_and_no_persistence(self):
        secrets=['Bearer secret-123','token-value-456','cookie-value-789','person@example.com','Private Buyer','555123456','private-document']
        payload={'event':'SALE_APPROVED','type':'RECURRING','status':'APPROVED','customer':{'email':secrets[3],'name':secrets[4],'phone':secrets[5],'document':secrets[6]}}
        with patch('app.services.firebase_service.get_firestore_client',side_effect=AssertionError('Firebase must not be used')) as client, self.assertLogs('uvicorn.error.kirvano',level='INFO') as logs:
            response=self.client.post('/webhooks/kirvano',json=payload,headers={'Authorization':secrets[0],'x-unknown-token':secrets[1],'Cookie':secrets[2],'x-safe':'not-logged','x-bad name':'not-logged'})
        self.assertEqual(response.status_code,200)
        client.assert_not_called()
        output=' '.join(logs.output)
        for secret in secrets+['not-logged','x-bad name']:self.assertNotIn(secret,output)
        self.assertNotIn('test-configured-secret',output)
        self.assertNotIn('authorization',output.lower())
        self.assertNotIn('cookie',output.lower())
        self.assertNotIn('SALE_APPROVED',output)
        self.assertIn('body_bytes=',output)
        self.recorder.assert_called_once()

    def test_untrusted_labels_not_logged(self):
        with self.assertLogs('uvicorn.error.kirvano',level='INFO') as logs:
            self.client.post('/webhooks/kirvano',json={'event':'person@example.com','type':'line\nsecret','status':'x'*1000})
        for value in ['person@example.com','line','x'*1000]:
            self.assertNotIn(value,' '.join(logs.output))

    def test_invalid_authentication(self):
        unauthenticated=TestClient(app)
        for headers in [{}, {'security-token':'incorrect-received-secret'}, {'security-token':''}]:
            with self.assertNoLogs('uvicorn.error.kirvano',level='INFO'):
                response=unauthenticated.post('/webhooks/kirvano',json={},headers=headers)
            self.assertEqual(response.status_code,401)
            self.assertEqual(response.json(),{'detail':'Unauthorized'})
            self.recorder.assert_not_called()

    def test_missing_or_empty_configuration(self):
        import os
        for value in [None, '', '   ']:
            with patch.dict(os.environ):
                if value is None:os.environ.pop('KIRVANO_WEBHOOK_TOKEN',None)
                else:os.environ['KIRVANO_WEBHOOK_TOKEN']=value
                response=self.client.post('/webhooks/kirvano',json={})
            self.assertEqual(response.status_code,401)
            self.assertEqual(response.json(),{'detail':'Unauthorized'})
            self.recorder.assert_not_called()

    def test_duplicate_token_rejected(self):
        response=TestClient(app).post('/webhooks/kirvano',json={},headers=[('security-token','test-configured-secret'),('security-token','test-configured-secret')])
        self.assertEqual(response.status_code,401)

    def test_storage_failure(self):
        self.recorder.side_effect = RuntimeError('sensitive error')
        response=self.client.post('/webhooks/kirvano',json={})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),{'detail':'Service unavailable'})

    def test_existing_routes(self):
        for path in ['/','/health','/openapi.json']:self.assertEqual(self.client.get(path).status_code,200)
