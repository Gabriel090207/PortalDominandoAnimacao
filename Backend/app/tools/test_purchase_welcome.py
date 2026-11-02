"""Manual single-operation test. Import/prepare NEVER builds a live provider.

Only --send-once --confirm-single-send may cross the network boundary, in a future
explicitly authorized execution. No integration with public runtime or startup.
"""
import argparse
from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Literal
from uuid import uuid4

from dotenv import dotenv_values
from google.cloud import firestore
from google.auth.credentials import AnonymousCredentials
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, SecretStr
from app.config.purchase_welcome import PurchaseWelcomeConfig
from app.domain.email import normalize_email
from app.domain.email_identity import derive_email_identity
from app.domain.welcome_email import welcome_intent_id
from app.domain.welcome_dispatch import WelcomeDispatchRecord, WelcomeRequest
from app.services.purchase_welcome_email import WelcomeEmailContact, render_purchase_welcome
from app.services.purchase_welcome_dispatch import create_purchase_welcome_dispatch
from app.services.kirvano_commercial_service import classify_commercial_event
from app.services.kirvano_event_service import normalize_event
from app.persistence.kirvano_commerce_repository import commercial_transaction
from app.tools.prepare_local_customer import sale_payload

BACKEND = Path(__file__).resolve().parents[2]
CREDENTIALS = BACKEND / 'credentials'
PROJECT = 'demo-dominando-animacao-test'
HOST = '127.0.0.1:8080'


class ControlledTestError(RuntimeError):
    def __init__(self):
        super().__init__('Controlled email test not confirmed. No automatic retry; inspect the private operation record before proceeding.')


class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)
    version: Literal[1] = 1
    operation_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    status: Literal['preparing','prepared','attempt_started','accepted','requires_review']
    not_before: AwareDatetime
    created_at: AwareDatetime
    intent_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    purchase_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    recipient_digest: str = Field(pattern=r'^[0-9a-f]{64}$',repr=False)
    request_digest: str = Field(pattern=r'^[0-9a-f]{64}$',repr=False)
    provider_id: str | None = Field(default=None,pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def require_emulator(environment):
    if environment.get('FIRESTORE_EMULATOR_HOST') != HOST or environment.get('FIRESTORE_TEST_PROJECT_ID') != PROJECT:
        raise ControlledTestError()


def local_configuration(env_file, environment):
    # Read-only, no interpolation/export. Explicitly require BOTH switches false.
    with redirect_stderr(io.StringIO()):
        values = dict(dotenv_values(env_file,interpolate=False))
    for name in ('PURCHASE_WELCOME_SEND_ENABLED','PURCHASE_WELCOME_RECOVERY_ENABLED'):
        if values.get(name) != 'false' or environment.get(name,'false') != 'false':
            raise ControlledTestError()
    values.update(environment)
    # enabled here is an in-memory manual-operation capability, NEVER a global
    # environment change or runtime installation. Constructors do not send.
    return PurchaseWelcomeConfig(True,SecretStr(values.get('RESEND_API_KEY','')),
        values.get('PURCHASE_WELCOME_FROM'),WelcomeEmailContact(values.get('PURCHASE_WELCOME_WHATSAPP_URL')))


def cutoff_instant(value):
    if not isinstance(value,str) or 'T' not in value:raise ControlledTestError()
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:raise ControlledTestError()
    return instant.astimezone(timezone.utc)


def _private_file(path):
    fd = os.open(path,os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ControlledTestError()
        with os.fdopen(fd,'r',encoding='utf-8') as stream:
            fd = None
            data = stream.read(32769)
        if len(data) > 32768:raise ControlledTestError()
        return data
    finally:
        if fd is not None:os.close(fd)


def _safe_under(path, root):
    root = Path(root).absolute()
    if root.is_symlink():raise ControlledTestError()
    path = Path(path).absolute()
    relative = path.relative_to(root)
    if '..' in relative.parts:raise ControlledTestError()
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():raise ControlledTestError()
    return path


def read_recipient(path, root):
    address = _private_file(_safe_under(path,root)).strip()
    return normalize_email(address)


def _atomic_record(path, operation):
    # Lock inode is separate and stable; record replacement never replaces lock.
    fd,temporary = tempfile.mkstemp(prefix='.operation-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(operation.model_dump_json())
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary) # only this call's temp file


@contextmanager
def operation_lock(root):
    root = Path(root).absolute()
    if root.is_symlink():raise ControlledTestError()
    directory = _safe_under(root/'resend-test',root)
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:raise ControlledTestError()
    lock = os.open(directory/'operation.lock',os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:raise ControlledTestError()
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield directory/'operation.json'
    finally:os.close(lock)


def create_demo_client(environment):
    require_emulator(environment)
    # No Firebase initialization, ADC, service accounts or get_firestore_client.
    # The SDK also reads its process emulator host: require exact equality.
    require_emulator(os.environ)
    client = firestore.Client(project=PROJECT,credentials=AnonymousCredentials(),client_options={'api_endpoint':HOST})
    if client.project != PROJECT or client._database != '(default)' or client._emulator_host != HOST:
        client.close();raise ControlledTestError()
    return client


class ScopedClient:
    def __init__(self,client,operation_id):
        if client.project != PROJECT or client._database != '(default)' or client._emulator_host != HOST:
            raise ControlledTestError()
        self.client = client
        self.root = client.collection('resend_test_operations').document(operation_id)
    def collection(self,name):return self.root.collection(name)
    def transaction(self):return self.client.transaction()


def _request(intent,config):
    mail = render_purchase_welcome(intent,contact=config.contact)
    return WelcomeRequest(sender=config.sender,recipient=mail.recipient,subject=mail.subject,html=mail.html,text=mail.text)


def _digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()


def prepare(*, recipient_file, not_before, env_file=BACKEND/'.env', credentials_root=CREDENTIALS,
            environment=None, client_factory=None, clock=None):
    client = None
    try:
        environment = os.environ if environment is None else environment
        require_emulator(environment)
        config = local_configuration(env_file,environment)
        recipient = read_recipient(recipient_file,credentials_root)
        cutoff = cutoff_instant(not_before)
        now = (clock or (lambda:datetime.now(timezone.utc)))()
        if now < cutoff:raise ControlledTestError()
        # If configured privately, the persisted cutoff must agree with CLI input.
        with redirect_stderr(io.StringIO()):values=dotenv_values(env_file,interpolate=False)
        configured = environment.get('PURCHASE_WELCOME_NOT_BEFORE',values.get('PURCHASE_WELCOME_NOT_BEFORE'))
        if configured and cutoff_instant(configured) != cutoff:raise ControlledTestError()
        with operation_lock(credentials_root) as path:
            if path.exists() or path.is_symlink():raise ControlledTestError() # no silent replacement
            operation_id = uuid4().hex
            data = sale_payload(now,email=recipient,sale_id='resend-test-'+operation_id)
            data['customer']['name']='Cliente Exemplo'
            event = normalize_event(data)
            classified = classify_commercial_event(data,timezone_name='UTC')
            if classified.candidate is None:raise ControlledTestError()
            from app.domain.welcome_email import WelcomeEmailIntent
            candidate=classified.candidate
            intent=WelcomeEmailIntent(purchase_id=candidate.purchase_id,user_id='resend-test-'+operation_id,
                origin_event_id=event.logical_id,recipient=recipient,customer_name='Cliente Exemplo',created_at=now)
            operation = Operation(operation_id=operation_id,status='preparing',not_before=cutoff,created_at=now,
                intent_id=welcome_intent_id(candidate.purchase_id),purchase_id=candidate.purchase_id,
                recipient_digest=_digest(recipient),request_digest=_request(intent,config).digest())
            _atomic_record(path,operation) # durable BEFORE any emulator writes
            client = (client_factory or create_demo_client)(environment)
            scoped = ScopedClient(client,operation_id)
            identity = derive_email_identity(recipient,secret='local-resend-test-identity-'+operation_id)
            firestore.transactional(commercial_transaction)(scoped.transaction(),scoped,event,classified,identity,intent.user_id)
            operation=operation.model_copy(update={'status':'prepared'})
            _atomic_record(path,operation)
            return operation.operation_id
    except Exception:raise ControlledTestError() from None
    finally:
        if client is not None:
            try:client.close()
            except Exception:pass


def _live_provider(config):
    # Never reached by import or prepare. Only future explicit --send-once.
    import httpx
    from app.services.resend_email_provider import ResendEmailProvider
    return ResendEmailProvider(config,transport=httpx.HTTPTransport(retries=0,verify=True))


def send_once(*, recipient_file, confirmed=False, env_file=BACKEND/'.env', credentials_root=CREDENTIALS,
              environment=None, client_factory=None, provider_factory=None):
    client=provider=None
    try:
        if confirmed is not True:raise ControlledTestError()
        environment = os.environ if environment is None else environment
        require_emulator(environment)
        config = local_configuration(env_file,environment)
        recipient = read_recipient(recipient_file,credentials_root)
        with operation_lock(credentials_root) as path:
            operation = Operation.model_validate_json(_private_file(path))
            if operation.status != 'prepared' or operation.recipient_digest != _digest(recipient):raise ControlledTestError()
            client=(client_factory or create_demo_client)(environment)
            scoped=ScopedClient(client,operation.operation_id)
            ref=scoped.collection('transactional_emails').document(operation.intent_id)
            snapshot=ref.get(timeout=10)
            if not snapshot.exists:raise ControlledTestError() # emulator reset is NOT a reset of the operation
            record=WelcomeDispatchRecord.model_validate(snapshot.to_dict())
            if (record.status != 'pending' or record.purchase_id != operation.purchase_id
                or welcome_intent_id(record.purchase_id) != operation.intent_id
                or record.recipient != recipient or record.created_at < operation.not_before
                or _request(record.pending_intent(),config).digest() != operation.request_digest):raise ControlledTestError()
            # Permanent local guard BEFORE provider construction/reservation/HTTP.
            operation=operation.model_copy(update={'status':'attempt_started'})
            _atomic_record(path,operation)
            try:
                provider=(provider_factory or _live_provider)(config)
                dispatcher=create_purchase_welcome_dispatch(firestore_client=scoped,config=config,provider=provider)
                outcome=dispatcher.dispatch(operation.intent_id,not_before=operation.not_before)
                final=WelcomeDispatchRecord.model_validate(ref.get(timeout=10).to_dict())
                status='accepted' if outcome=='accepted' and final.status=='accepted' else 'requires_review'
                operation=operation.model_copy(update={'status':status,'provider_id':final.provider_id})
                _atomic_record(path,operation)
                return status
            except Exception:
                _atomic_record(path,operation.model_copy(update={'status':'requires_review'}))
                raise
    except Exception:raise ControlledTestError() from None
    finally:
        if provider is not None:
            try:provider.close()
            except Exception:pass
        if client is not None:
            try:client.close()
            except Exception:pass


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local single-operation welcome email test; no automatic send.')
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare',action='store_true')
    modes.add_argument('--send-once',action='store_true')
    parser.add_argument('--recipient-file',type=Path,default=CREDENTIALS/'resend-test-recipient.txt')
    parser.add_argument('--not-before',help='Explicit PURCHASE_WELCOME_NOT_BEFORE ISO-8601 instant with timezone.')
    parser.add_argument('--confirm-single-send',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.prepare:
            if not args.not_before or args.confirm_single_send:raise ControlledTestError()
            prepare(recipient_file=args.recipient_file,not_before=args.not_before)
            print('Prepared one private synthetic operation. No email sent.')
        else:
            if args.not_before:raise ControlledTestError()
            result=send_once(recipient_file=args.recipient_file,confirmed=args.confirm_single_send)
            print('Single operation result: '+result+'. Acceptance is not proof of delivery.')
    except ControlledTestError:
        raise SystemExit(str(ControlledTestError())) from None


if __name__=='__main__':main()
