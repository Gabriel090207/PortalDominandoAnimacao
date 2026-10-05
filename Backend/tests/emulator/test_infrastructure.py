"""Synthetic sentinel operations ONLY on the explicitly guarded emulator."""
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from emulator_support import TEST_PROJECT_ID, clear_test_emulator

pytestmark = pytest.mark.firestore_emulator


def test_connection_write_read_and_anonymous_credentials(emulator_client):
    assert emulator_client.project == TEST_PROJECT_ID
    assert isinstance(emulator_client._credentials, AnonymousCredentials)
    assert list(emulator_client.collections(timeout=5)) == []
    ref = emulator_client.collection('infra_sentinel').document('synthetic')
    ref.set({'value': 1}, timeout=5)
    assert ref.get(timeout=5).to_dict() == {'value': 1}


def test_real_transaction(emulator_client):
    ref = emulator_client.collection('infra_sentinel').document('counter')
    ref.set({'value': 0}, timeout=5)
    @firestore.transactional
    def increment(transaction):
        snapshot = ref.get(transaction=transaction, timeout=5)
        transaction.update(ref, {'value': snapshot.to_dict()['value'] + 1})
    increment(emulator_client.transaction())
    assert ref.get(timeout=5).to_dict() == {'value': 1}


def test_cleanup_and_empty_start(emulator_client):
    assert list(emulator_client.collections(timeout=5)) == []
    emulator_client.collection('infra_sentinel').document('cleanup').set({'synthetic': True}, timeout=5)
    clear_test_emulator()
    assert list(emulator_client.collections(timeout=5)) == []
