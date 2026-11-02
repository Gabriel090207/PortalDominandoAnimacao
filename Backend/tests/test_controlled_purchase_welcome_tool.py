"""Memory-only emulator and fake provider; never invoke CLI --send-once."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock
from uuid import uuid4
import pytest
from commerce_fake import Ref, Transaction
from test_welcome_dispatch import setup, configuration, PROVIDER_ID
from app.domain.welcome_dispatch import WelcomeProviderResult
from app.tools import test_purchase_welcome as tool

ENV={'FIRESTORE_EMULATOR_HOST':tool.HOST,'FIRESTORE_TEST_PROJECT_ID':tool.PROJECT}
CUTOFF='2026-01-01T00:00:00+00:00'
NOW=datetime(2026,1,1,0,1,tzinfo=timezone.utc)


@pytest.fixture
def local(setup,tmp_path,monkeypatch):
    client,_,_=setup;client.project=tool.PROJECT;client._database='(default)';client._emulator_host=tool.HOST;client.close=Mock()
    original=Ref.get
    monkeypatch.setattr(Ref,'get',lambda ref,transaction=None,**kw:original(ref,transaction or Transaction(client)))
    root=tmp_path/'credentials';root.mkdir(mode=0o700)
    recipient=root/'recipient.txt';recipient.write_text('recipient-'+uuid4().hex+'@example.com');recipient.chmod(0o600)
    config=configuration();envfile=tmp_path/'.env'
    envfile.write_text('\n'.join(['RESEND_API_KEY='+config.api_key.get_secret_value(),
        'PURCHASE_WELCOME_FROM='+config.sender,'PURCHASE_WELCOME_WHATSAPP_URL='+config.contact.whatsapp_url,
        'PURCHASE_WELCOME_SEND_ENABLED=false','PURCHASE_WELCOME_RECOVERY_ENABLED=false']))
    args={'recipient_file':recipient,'env_file':envfile,'credentials_root':root,
          'environment':dict(ENV),'client_factory':lambda env:client}
    return client,args


def prepare(local):return tool.prepare(**local[1],not_before=CUTOFF,clock=lambda:NOW)
def operation(local):return tool.Operation.model_validate_json((local[1]['credentials_root']/'resend-test/operation.json').read_text())
def provider(reason='accepted'):
    fake=Mock();fake.send.return_value=WelcomeProviderResult(reason=reason,provider_id=PROVIDER_ID if reason=='accepted' else None)
    return fake


def test_preparation_no_provider_unique_scoped_graph_private_atomic_record(local,monkeypatch):
    forbidden=Mock(side_effect=AssertionError('No live provider'))
    monkeypatch.setattr(tool,'_live_provider',forbidden)
    baseline=dict(local[0].data);identifier=prepare(local);state=operation(local)
    assert identifier==state.operation_id and state.status=='prepared'
    assert len(identifier)==32 and state.intent_id!=state.purchase_id
    assert all(local[0].data[k]==v for k,v in baseline.items())
    owned={k:v for k,v in local[0].data.items() if k not in baseline}
    assert owned and all(k.startswith('resend_test_operations/'+identifier+'/') for k in owned)
    assert any(v.get('activation_status')=='pending' for v in owned.values())
    path=local[1]['credentials_root']/'resend-test/operation.json'
    assert path.stat().st_mode & 0o777==0o600 and path.parent.stat().st_mode & 0o777==0o700
    assert local[1]['recipient_file'].read_text() not in path.read_text()
    assert 're_synthetic' not in path.read_text()
    forbidden.assert_not_called()
    with pytest.raises(tool.ControlledTestError):prepare(local)


@pytest.mark.parametrize('change',[{}, {'FIRESTORE_EMULATOR_HOST':'remote.example:8080','FIRESTORE_TEST_PROJECT_ID':tool.PROJECT},
    {'FIRESTORE_EMULATOR_HOST':tool.HOST,'FIRESTORE_TEST_PROJECT_ID':'production-project'}])
def test_guard_before_client(local,change):
    args=dict(local[1],environment=change,client_factory=Mock())
    with pytest.raises(tool.ControlledTestError):tool.prepare(**args,not_before=CUTOFF,clock=lambda:NOW)
    args['client_factory'].assert_not_called()


@pytest.mark.parametrize('cutoff',[None,'2026-01-01','2026-01-01T00:00:00','bad','2027-01-01T00:00:00Z'])
def test_cutoff_required_explicit_aware_not_future(local,cutoff):
    with pytest.raises(tool.ControlledTestError):tool.prepare(**local[1],not_before=cutoff,clock=lambda:NOW)
    assert not (local[1]['credentials_root']/'resend-test/operation.json').exists()


@pytest.mark.parametrize('setting,value',[('PURCHASE_WELCOME_SEND_ENABLED','true'),('PURCHASE_WELCOME_RECOVERY_ENABLED','true'),
    ('PURCHASE_WELCOME_WHATSAPP_URL','https://wa.me/not-digits'),('RESEND_API_KEY','')])
def test_invalid_config_blocks(local,setting,value):
    args=local[1];path=args['env_file'];lines=[line for line in path.read_text().splitlines() if not line.startswith(setting+'=')]
    path.write_text('\n'.join(lines+[setting+'='+value]))
    with pytest.raises(tool.ControlledTestError):prepare(local)


@pytest.mark.parametrize('reason',['accepted','timeout','network','rejected'])
def test_one_fake_attempt_and_permanent_guard_after_process_recreation(local,reason):
    prepare(local);fake=provider(reason)
    result=tool.send_once(**local[1],confirmed=True,provider_factory=lambda config:fake)
    assert result==('accepted' if reason=='accepted' else 'requires_review')
    fake.send.assert_called_once();fake.close.assert_called_once()
    # Same disk state, entirely new invocation; even loss of ALL in-memory demo data
    # cannot reset the durable local guard. No external operation occurs.
    local[0].data={}
    factory=Mock()
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=factory)
    factory.assert_not_called()
    # Separate Python interpreter proves that no module-global lock is relied upon.
    path=local[1]['credentials_root']/'resend-test/operation.json'
    code='from app.tools.test_purchase_welcome import Operation;from pathlib import Path;import sys;s=Operation.model_validate_json(Path(sys.argv[1]).read_text());sys.exit(0 if s.status!="prepared" else 1)'
    result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(tool.BACKEND),capture_output=True)
    assert result.returncode==0


def test_changed_recipient_and_template_snapshot_block_before_provider(local):
    prepare(local);factory=Mock();args=local[1]
    args['recipient_file'].write_text('different-'+uuid4().hex+'@example.com')
    with pytest.raises(tool.ControlledTestError):tool.send_once(**args,confirmed=True,provider_factory=factory)
    factory.assert_not_called()


def test_content_config_change_blocks(local):
    prepare(local);factory=Mock();path=local[1]['env_file']
    path.write_text(path.read_text().replace('15555550123','15555550124'))
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=factory)
    factory.assert_not_called()


def test_missing_explicit_confirmation(local):
    factory=Mock()
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],provider_factory=factory)
    factory.assert_not_called()


def test_emulator_lost_before_first_send_does_not_recreate_documents(local):
    prepare(local);local[0].data={};factory=Mock()
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=factory)
    factory.assert_not_called();assert local[0].data=={}


def test_uncertain_reservation_blocks_even_without_provider_effect(local,monkeypatch):
    prepare(local);fake=provider()
    monkeypatch.setattr('app.persistence.welcome_emails_repository.WelcomeEmailsRepository.reserve',Mock(side_effect=RuntimeError('private')))
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=lambda config:fake)
    assert operation(local).status=='requires_review';fake.send.assert_not_called()


def test_exception_after_provider_call_never_reopens(local,monkeypatch):
    prepare(local);fake=provider()
    monkeypatch.setattr('app.persistence.welcome_emails_repository.WelcomeEmailsRepository.finish',Mock(side_effect=RuntimeError('private')))
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=lambda config:fake)
    assert operation(local).status=='requires_review';fake.send.assert_called_once()


def test_cross_process_lock_prevents_two_executors(local):
    root=local[1]['credentials_root']
    code='from app.tools.test_purchase_welcome import operation_lock;from pathlib import Path;import sys\ntry:\n with operation_lock(Path(sys.argv[1])):sys.exit(1)\nexcept BlockingIOError:sys.exit(0)'
    with tool.operation_lock(root):
        result=subprocess.run([sys.executable,'-c',code,str(root)],cwd=Path(tool.BACKEND),capture_output=True)
        assert result.returncode==0


@pytest.mark.parametrize('kind',['symlink','world_readable'])
def test_recipient_requires_private_regular_file(local,kind):
    args=local[1];path=args['recipient_file']
    if kind=='symlink':
        target=path.with_name('target.txt');path.rename(target);path.symlink_to(target)
    else:path.chmod(0o644)
    with pytest.raises(tool.ControlledTestError):prepare(local)


def test_cli_prepare_requires_cutoff_without_sending(monkeypatch):
    send=Mock(side_effect=AssertionError('CLI send mode must not run'))
    monkeypatch.setattr(tool,'send_once',send)
    with pytest.raises(SystemExit):tool.main(['--prepare'])
    send.assert_not_called()


def test_failure_persisting_outcome_keeps_pre_http_guard(local,monkeypatch):
    prepare(local);fake=provider();original=tool._atomic_record
    def persist(path,state):
        if state.status in ('accepted','requires_review'):raise OSError('synthetic disk failure')
        return original(path,state)
    monkeypatch.setattr(tool,'_atomic_record',persist)
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=lambda config:fake)
    assert operation(local).status=='attempt_started';fake.send.assert_called_once()
    second=Mock()
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=second)
    second.assert_not_called()


def test_operation_lock_has_private_permissions(local):
    prepare(local)
    lock=local[1]['credentials_root']/'resend-test/operation.lock'
    assert lock.stat().st_mode & 0o777==0o600


def test_errors_do_not_expose_private_configuration_or_recipient(local,caplog):
    prepare(local);fake=provider();fake.send.side_effect=RuntimeError(local[1]['recipient_file'].read_text())
    assert tool.send_once(**local[1],confirmed=True,provider_factory=lambda config:fake)=='requires_review'
    assert local[1]['recipient_file'].read_text() not in caplog.text
    assert configuration().api_key.get_secret_value() not in caplog.text


@pytest.mark.parametrize('name',['PURCHASE_WELCOME_SEND_ENABLED','PURCHASE_WELCOME_RECOVERY_ENABLED'])
def test_process_override_cannot_enable_global_dispatch(local,name):
    args=dict(local[1],environment={**ENV,name:'true'})
    with pytest.raises(tool.ControlledTestError):tool.prepare(**args,not_before=CUTOFF,clock=lambda:NOW)


@pytest.mark.parametrize('field,value',[('project','another-project'),('_database','named'),('_emulator_host','remote.example:8080')])
def test_injected_client_cannot_escape_demo_binding(local,field,value):
    before=dict(local[0].data);setattr(local[0],field,value)
    with pytest.raises(tool.ControlledTestError):prepare(local)
    assert local[0].data==before


def test_process_interruption_after_durable_guard_is_not_rearmed(local):
    prepare(local)
    class SimulatedCrash(BaseException):pass
    def crash(config):raise SimulatedCrash()
    with pytest.raises(SimulatedCrash):tool.send_once(**local[1],confirmed=True,provider_factory=crash)
    assert operation(local).status=='attempt_started'
    other=Mock()
    with pytest.raises(tool.ControlledTestError):tool.send_once(**local[1],confirmed=True,provider_factory=other)
    other.assert_not_called()
