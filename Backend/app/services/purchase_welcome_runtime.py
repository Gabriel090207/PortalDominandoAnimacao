"""Explicit lifespan installation. No environment, client creation or live provider."""
from dataclasses import dataclass, field
import re
from threading import RLock
from app.config.purchase_welcome import PurchaseWelcomeConfig
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError
from app.services.purchase_welcome_trigger import WelcomeTriggerPolicy, install_purchase_welcome_trigger


@dataclass(frozen=True, repr=False)
class WelcomeRuntimeInstallation:
    enabled: bool = False
    config: PurchaseWelcomeConfig | None = field(default=None, repr=False)
    policy: WelcomeTriggerPolicy | None = None
    firestore_client: object = field(default=None, repr=False)
    expected_project_id: str | None = None
    provider_factory: object = field(default=None, repr=False)
    allow_emulator: bool = False

    def validate(self):
        if type(self.enabled) is not bool or type(self.allow_emulator) is not bool:
            raise WelcomeEmailConfigurationError()
        if not self.enabled:
            return False
        if not isinstance(self.config, PurchaseWelcomeConfig) or not isinstance(self.policy, WelcomeTriggerPolicy):
            raise WelcomeEmailConfigurationError()
        # Revalidate existing contracts, even if a caller bypassed frozen constructors.
        PurchaseWelcomeConfig(self.config.enabled,self.config.api_key,self.config.sender,self.config.contact)
        WelcomeTriggerPolicy(self.policy.not_before,self.policy.recovery_enabled,self.policy.batch_size)
        project = self.expected_project_id
        if not isinstance(project,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',project):
            raise WelcomeEmailConfigurationError()
        client = self.firestore_client
        if client.project != project or client._database != '(default)' or not callable(self.provider_factory):
            raise WelcomeEmailConfigurationError()
        if self.allow_emulator:
            if project != 'demo-dominando-animacao-test' or client._emulator_host != '127.0.0.1:8080':
                raise WelcomeEmailConfigurationError()
        elif project.startswith('demo-') or client._emulator_host is not None:
            raise WelcomeEmailConfigurationError()
        return True


def prepare_purchase_welcome_runtime(app, installation):
    """Select explicitly, BEFORE startup. Does not invoke the provider/client."""
    if not isinstance(installation, WelcomeRuntimeInstallation):
        raise WelcomeEmailConfigurationError()
    if (getattr(app.state,'purchase_welcome_installation',None) is not None
        or getattr(app.state,'purchase_welcome_trigger',None) is not None):
        raise WelcomeEmailConfigurationError()
    app.state.purchase_welcome_installation = installation
    app.state.purchase_welcome_installation_lock = RLock()
    app.state.purchase_welcome_runtime_status = 'prepared'
    app.state.purchase_welcome_runtime_active = False


def start_purchase_welcome_runtime(app):
    installation = getattr(app.state,'purchase_welcome_installation',None)
    if installation is None:
        return None  # Preserve manually injected PASSO 95 runtimes and default app.
    with app.state.purchase_welcome_installation_lock:
        if app.state.purchase_welcome_runtime_active:
            raise WelcomeEmailConfigurationError()  # Reject a second concurrent lifespan.
        provider = None
        try:
            if not installation.validate():
                app.state.purchase_welcome_runtime_status = 'disabled'
                return None
            if getattr(app.state,'purchase_welcome_trigger',None) is not None:
                raise WelcomeEmailConfigurationError()
            provider = installation.provider_factory(installation.config)
            if not callable(getattr(provider,'send',None)) or not callable(getattr(provider,'close',None)):
                raise WelcomeEmailConfigurationError()
            runtime = install_purchase_welcome_trigger(app,firestore_client=installation.firestore_client,
                config=installation.config,policy=installation.policy,provider=provider,_managed=True)
            app.state.purchase_welcome_runtime_active = True
            app.state.purchase_welcome_runtime_status = 'installed'
            return runtime
        except Exception:
            if provider is not None and callable(getattr(provider,'close',None)):
                try:provider.close()
                except Exception:pass
            app.state.purchase_welcome_runtime_status = 'unavailable'
            return None  # Public webhook/health survive invalid email installation.


def stop_purchase_welcome_runtime(app, owned_runtime):
    if owned_runtime is None:
        return
    with app.state.purchase_welcome_installation_lock:
        try:
            owned_runtime.dispatcher.provider.close()
        except Exception:
            pass
        finally:
            if getattr(app.state,'purchase_welcome_trigger',None) is owned_runtime:
                del app.state.purchase_welcome_trigger
            app.state.purchase_welcome_runtime_active = False
            app.state.purchase_welcome_runtime_status = 'stopped'
