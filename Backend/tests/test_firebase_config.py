import unittest
from unittest.mock import patch, sentinel
from app.services import firebase_service as service


class FirebaseConfigTests(unittest.TestCase):
    def test_json_precedence(self):
        with patch.object(service.firebase_admin,'get_app',side_effect=ValueError), patch.object(service,'load_dotenv'), patch.dict('os.environ',{'FIREBASE_CREDENTIALS_JSON':'{"type":"service_account"}','FIREBASE_CREDENTIALS_PATH':'missing.json'}), patch.object(service.credentials,'Certificate',return_value=sentinel.credential) as certificate, patch.object(service.firebase_admin,'initialize_app',return_value=sentinel.app):
            self.assertIs(service.get_firebase_app(),sentinel.app)
            certificate.assert_called_once_with({'type':'service_account'})

    def test_invalid_json_no_fallback(self):
        for value in ['invalid','[]']:
            with patch.object(service.firebase_admin,'get_app',side_effect=ValueError), patch.object(service,'load_dotenv'), patch.dict('os.environ',{'FIREBASE_CREDENTIALS_JSON':value,'FIREBASE_CREDENTIALS_PATH':'firebase-key.json'}), patch.object(service.credentials,'Certificate') as certificate:
                with self.assertRaisesRegex(RuntimeError,'credencial inválida'): service.get_firebase_app()
                certificate.assert_not_called()

    def test_missing_configuration(self):
        with patch.object(service.firebase_admin,'get_app',side_effect=ValueError), patch.object(service,'load_dotenv'), patch.dict('os.environ',{'FIREBASE_CREDENTIALS_JSON':'','FIREBASE_CREDENTIALS_PATH':''}):
            with self.assertRaisesRegex(RuntimeError,'Configure'):service.get_firebase_app()

    def test_app_reuse(self):
        with patch.object(service.firebase_admin,'get_app',return_value=sentinel.app), patch.object(service.credentials,'Certificate') as certificate:
            self.assertIs(service.get_firebase_app(),sentinel.app)
            certificate.assert_not_called()
