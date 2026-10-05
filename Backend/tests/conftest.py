"""Integration opt-in; existing unittest cases remain collected by pytest."""
import pytest
from emulator_support import configured_emulator, clear_test_emulator, create_test_client


def pytest_addoption(parser):
    parser.addoption('--run-firestore-emulator', action='store_true', default=False,
                     help='Explicitly run guarded local Firestore Emulator tests.')


def pytest_collection_modifyitems(config, items):
    if config.getoption('--run-firestore-emulator'):
        return
    selected, excluded = [], []
    for item in items:
        (excluded if item.get_closest_marker('firestore_emulator') else selected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=excluded)


@pytest.fixture(autouse=True)
def emulator_client(request, monkeypatch):
    if not request.node.get_closest_marker('firestore_emulator'):
        yield None
        return
    try:
        configured_emulator()
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)
    # No production credential loading, even if the invoking shell has secrets.
    for name in ('GOOGLE_APPLICATION_CREDENTIALS', 'FIREBASE_CREDENTIALS_JSON', 'FIREBASE_CREDENTIALS_PATH'):
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Production Firebase initialization forbidden in emulator tests.')
    monkeypatch.setattr('firebase_admin.initialize_app', forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firebase_app', forbidden)
    monkeypatch.setattr('app.services.firebase_service.get_firestore_client', forbidden)
    try:
        clear_test_emulator()  # Also verifies that an emulator is listening.
    except Exception:
        pytest.fail('Local Firestore Emulator unavailable or cleanup failed.', pytrace=False)
    client = create_test_client()
    try:
        yield client
    finally:
        client.close()
        clear_test_emulator()  # Revalidates both guards before deletion.
