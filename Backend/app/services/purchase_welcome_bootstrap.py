"""Public app.main:app bootstrap. Process config only; disabled has no side effects."""
import os
import re
from app.config.purchase_welcome import load_purchase_welcome_config
from app.services.purchase_welcome_runtime import WelcomeRuntimeInstallation, prepare_purchase_welcome_runtime
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy

_FORBIDDEN=('FIRESTORE_EMULATOR_HOST','DATASTORE_EMULATOR_HOST','FIRESTORE_TEST_PROJECT_ID')


def _provider(config):
    # Constructed only after every guard. No request until an approved reservation.
    import httpx
    from app.services.resend_email_provider import ResendEmailProvider
    return ResendEmailProvider(config,transport=httpx.HTTPTransport(retries=0,verify=True))


def prepare_public_welcome(app, *, environ=None, client_factory=None, provider_factory=None):
    if (getattr(app.state,'purchase_welcome_installation',None) is not None
        or getattr(app.state,'purchase_welcome_trigger',None) is not None):return False
    env=os.environ if environ is None else environ
    try:
        config=load_purchase_welcome_config(environ=env,env_file=None)
        if config is None:return False
        if env.get('PURCHASE_WELCOME_RECOVERY_ENABLED','false') != 'false':raise ValueError
        project=env.get('FIREBASE_PROJECT_ID')
        if not isinstance(project,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',project) or project.startswith('demo-'):raise ValueError
        if any(name in env for name in _FORBIDDEN):raise ValueError
        for name in ('GOOGLE_CLOUD_PROJECT','GCLOUD_PROJECT','GCP_PROJECT'):
            if name in env and env[name]!=project:raise ValueError
        if client_factory is None:
            from app.services.firebase_service import get_firestore_client
            client_factory=get_firestore_client
        client=client_factory()
        # SDK initialization may load local .env. Recheck bindings, without RPCs.
        if any(name in os.environ for name in _FORBIDDEN):raise ValueError
        installation=WelcomeRuntimeInstallation(True,config,WelcomeTriggerPolicy(config.not_before,False,1),
            client,project,provider_factory or _provider,False)
        installation.validate()
        prepare_purchase_welcome_runtime(app,installation)
        return True
    except Exception:
        app.state.purchase_welcome_runtime_status='unavailable'
        return False  # Public health/webhook continue, no provider/fallback.


def clear_public_welcome(app):
    # Only lifespan's automatically prepared selection; no shared Firestore close.
    for name in ('purchase_welcome_installation','purchase_welcome_installation_lock'):
        if hasattr(app.state,name):delattr(app.state,name)
