"""Definitive CLI guards with synthetic .env files; no Firebase or database."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.tools import provision_admin as cli

VARIABLES = ("FIRESTORE_EMULATOR_HOST", "DATASTORE_EMULATOR_HOST", "FIRESTORE_TEST_PROJECT_ID")
ARGS = ["--bootstrap", "--project-id", "synthetic-project"]


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_BACKEND_ROOT", tmp_path)
    client_factory = Mock(side_effect=AssertionError("Firebase must not be initialized"))
    provision = Mock()
    prompts = Mock(side_effect=AssertionError("No input before guard"))
    password = Mock(side_effect=AssertionError("No password before guard"))
    monkeypatch.setattr(cli, "get_firestore_client", client_factory)
    monkeypatch.setattr(cli, "provision_first_owner", provision)
    monkeypatch.setattr("builtins.input", prompts)
    monkeypatch.setattr(cli.getpass, "getpass", password)
    class TerminalOutput:
        def isatty(self):
            return True

        def write(self, value):
            return sys.stderr.write(value)
    monkeypatch.setattr(cli, "sys", SimpleNamespace(
        stdin=SimpleNamespace(isatty=lambda: True), stderr=TerminalOutput()))
    initialize = Mock(side_effect=AssertionError("Production initialization forbidden"))
    firestore_client = Mock(side_effect=AssertionError("Firestore operations forbidden"))
    monkeypatch.setattr("firebase_admin.initialize_app", initialize)
    monkeypatch.setattr("firebase_admin.firestore.client", firestore_client)
    with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_ENABLED": "true"}, clear=True):
        yield tmp_path, client_factory, provision, prompts, password, initialize, firestore_client


@pytest.mark.parametrize("variable", VARIABLES)
@pytest.mark.parametrize("source", ["process", "dotenv"])
@pytest.mark.parametrize("value", ["synthetic-private-test-value", "", "   "])
def test_emulator_configuration_blocks_before_firebase(isolated_cli, capsys, variable, source, value):
    root, *spies = isolated_cli
    if source == "process":
        os.environ[variable] = value
    else:
        (root / ".env").write_text(f'{variable}="{value}"\n')
    assert cli.main(ARGS) == 1
    for spy in spies:
        spy.assert_not_called()
    output = capsys.readouterr()
    assert "emulator or test environment" in output.err
    assert "synthetic-private-test-value" not in output.out + output.err


@pytest.mark.parametrize("process_value", ["", "process-value"])
def test_dotenv_cannot_override_existing_process_configuration(isolated_cli, capsys, process_value):
    root, *spies = isolated_cli
    os.environ["FIRESTORE_EMULATOR_HOST"] = process_value
    (root / ".env").write_text('FIRESTORE_EMULATOR_HOST="dotenv-value"\n')
    assert cli.main(ARGS) == 1
    assert os.environ["FIRESTORE_EMULATOR_HOST"] == process_value
    for spy in spies:
        spy.assert_not_called()
    assert "emulator or test environment" in capsys.readouterr().err


@pytest.mark.parametrize("with_dotenv", [False, True])
def test_normal_environment_preserves_confirmation_and_provisioning(isolated_cli, capsys, with_dotenv):
    root, factory, provision, prompts, password, initialize, firestore_client = isolated_cli
    if with_dotenv:
        (root / ".env").write_text('UNRELATED_SETTING="synthetic-value"\n')
    factory.side_effect = None
    factory.return_value = Mock(project="synthetic-project")
    prompts.side_effect = ["BOOTSTRAP synthetic-project", "owner@example.com"]
    password.side_effect = ["synthetic password", "synthetic password"]
    assert cli.main(ARGS) == 0
    factory.assert_called_once_with()
    provision.assert_called_once_with(client=factory.return_value, email="owner@example.com",
        password="synthetic password", bootstrap_enabled=True, expected_project_id="synthetic-project")
    initialize.assert_not_called()
    firestore_client.assert_not_called()
    assert "synthetic password" not in capsys.readouterr().out


def test_dotenv_cannot_enable_bootstrap(isolated_cli):
    root, *spies = isolated_cli
    del os.environ["ADMIN_BOOTSTRAP_ENABLED"]
    (root / ".env").write_text('ADMIN_BOOTSTRAP_ENABLED=true\n')
    assert cli.main(ARGS) == 1
    for spy in spies:
        spy.assert_not_called()


def test_dotenv_load_failure_is_sanitized_and_never_initializes(isolated_cli, monkeypatch, capsys):
    _, *spies = isolated_cli
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-private-configuration")
    monkeypatch.setattr(cli, "load_dotenv", fail)
    assert cli.main(ARGS) == 1
    for spy in spies:
        spy.assert_not_called()
    assert "synthetic-private-configuration" not in capsys.readouterr().err
