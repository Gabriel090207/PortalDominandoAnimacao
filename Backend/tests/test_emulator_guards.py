"""Guard tests run without emulator or network access."""
import unittest
from unittest.mock import patch
from emulator_support import require_emulator, TEST_PROJECT_ID, EMULATOR_HOST, clear_test_emulator, create_test_client


class EmulatorGuardTests(unittest.TestCase):
    def test_missing_and_nonlocal_hosts(self):
        for host in (None, '', 'firestore.googleapis.com:443', 'http://127.0.0.1:8080', '127.0.0.1:9999', 'localhost:8080'):
            with self.assertRaises(ValueError):
                require_emulator(host, TEST_PROJECT_ID)

    def test_wrong_project(self):
        for project in (None, '', 'different-synthetic-project'):
            with self.assertRaises(ValueError):
                require_emulator(EMULATOR_HOST, project)

    def test_valid_config(self):
        self.assertEqual(require_emulator(EMULATOR_HOST, TEST_PROJECT_ID), (EMULATOR_HOST, TEST_PROJECT_ID))

    def test_no_client_or_delete_when_unsafe(self):
        with patch.dict('os.environ', {}, clear=True), patch('google.cloud.firestore.Client') as client, patch('emulator_support.build_opener') as opener:
            for operation in (create_test_client, clear_test_emulator):
                with self.assertRaises(ValueError): operation()
            client.assert_not_called()
            opener.assert_not_called()

    def test_anonymous_client_without_credentials_or_network(self):
        from google.auth.credentials import AnonymousCredentials
        with patch.dict('os.environ', {'FIRESTORE_EMULATOR_HOST': EMULATOR_HOST,
                                      'FIRESTORE_TEST_PROJECT_ID': TEST_PROJECT_ID}, clear=True), \
             patch('google.auth.default', side_effect=AssertionError('No credential discovery')):
            client = create_test_client()
            try:
                self.assertIsInstance(client._credentials, AnonymousCredentials)
                self.assertEqual(client.project, TEST_PROJECT_ID)
                self.assertEqual(client._emulator_host, EMULATOR_HOST)
            finally:
                client.close()
