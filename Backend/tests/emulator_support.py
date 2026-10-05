"""Test-only, loopback-only utilities. Never initialize the production Admin app."""
import os
from urllib.request import Request, build_opener, ProxyHandler

TEST_PROJECT_ID = 'demo-dominando-animacao-test'
EMULATOR_HOST = '127.0.0.1:8080'


def require_emulator(host, project):
    if host != EMULATOR_HOST:
        raise ValueError('Local Firestore Emulator host required.')
    if project != TEST_PROJECT_ID:
        raise ValueError('Synthetic Firestore test project required.')
    return host, project


def configured_emulator():
    return require_emulator(os.getenv('FIRESTORE_EMULATOR_HOST'), os.getenv('FIRESTORE_TEST_PROJECT_ID'))


def clear_test_emulator():
    """Delete ONLY the fixed emulator project's default database; no parameters."""
    host, project = configured_emulator()
    request = Request(f'http://{host}/emulator/v1/projects/{project}/databases/(default)/documents', method='DELETE')
    # Disable proxies so even local cleanup cannot be forwarded externally.
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError('Emulator cleanup failed.')


def create_test_client():
    host, project = configured_emulator()  # Validate BEFORE constructing the client.
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.firestore import Client
    client = Client(project=project, credentials=AnonymousCredentials(),
                    client_options={'api_endpoint': host})
    if client.project != TEST_PROJECT_ID or client._emulator_host != EMULATOR_HOST:
        client.close()
        raise RuntimeError('Unsafe emulator client configuration.')
    return client
