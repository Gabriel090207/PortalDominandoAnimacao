"""Opt-in post-commit trigger and bounded durable recovery. No polling or routes."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from starlette.concurrency import run_in_threadpool
from app.services.purchase_welcome_dispatch import create_purchase_welcome_dispatch
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError


@dataclass(frozen=True)
class WelcomeTriggerPolicy:
    not_before: datetime
    recovery_enabled: bool = False
    batch_size: int = 5

    def __post_init__(self):
        if (not isinstance(self.not_before, datetime) or self.not_before.utcoffset() is None
            or type(self.recovery_enabled) is not bool
            or type(self.batch_size) is not int or not 1 <= self.batch_size <= 20):
            raise WelcomeEmailConfigurationError()


class PurchaseWelcomeTrigger:
    def __init__(self, dispatcher, policy):
        if not isinstance(policy, WelcomeTriggerPolicy):
            raise WelcomeEmailConfigurationError()
        self.dispatcher, self.policy = dispatcher, policy

    def after_event(self, event_id):
        # Called only after receipt commit; failure never changes commercial ACK.
        try:
            identifier = self.dispatcher.repository.pending_for_event(event_id, not_before=self.policy.not_before)
            if identifier is not None:
                return self.dispatcher.dispatch(identifier, not_before=self.policy.not_before)
        except Exception:
            return 'unavailable'
        return 'not_dispatched'

    def recover_pending(self):
        if not self.policy.recovery_enabled:
            return {'processed':0, 'unavailable':0}
        try:
            identifiers = self.dispatcher.repository.pending_batch(not_before=self.policy.not_before,
                limit=self.policy.batch_size)
        except Exception:
            return {'processed':0, 'unavailable':1}
        processed = unavailable = 0
        for identifier in identifiers:
            try:
                self.dispatcher.dispatch(identifier, not_before=self.policy.not_before)
                processed += 1
            except Exception:
                unavailable += 1
        return {'processed':processed, 'unavailable':unavailable}


def install_purchase_welcome_trigger(app, *, firestore_client, config, policy, transport=None, provider=None,
                                     _managed=False):
    """Explicit internal composition BEFORE serving. No environment/live defaults.

    Missing/disabled config cannot install a partially usable trigger. Caller owns
    client/transport lifecycle; no public request can configure these dependencies.
    """
    if (not isinstance(policy, WelcomeTriggerPolicy)
        or (getattr(app.state, 'purchase_welcome_installation', None) is not None and not _managed)
        or getattr(app.state, 'purchase_welcome_trigger', None) is not None):
        raise WelcomeEmailConfigurationError()
    runtime = PurchaseWelcomeTrigger(create_purchase_welcome_dispatch(firestore_client=firestore_client,
        config=config, transport=transport, provider=provider), policy)
    app.state.purchase_welcome_trigger = runtime
    return runtime


def schedule_purchase_welcome(request, tasks, payload, result):
    """Only new approved receipts may schedule; storage verifies actual intent."""
    runtime = getattr(request.app.state, 'purchase_welcome_trigger', None)
    if (not isinstance(runtime, PurchaseWelcomeTrigger) or not isinstance(payload, dict)
        or payload.get('event') != 'SALE_APPROVED' or result.outcome != 'new'
        or result.processing_status.value != 'received'):
        return
    try:
        tasks.add_task(runtime.after_event, result.logical_id)
    except Exception:
        # The committed pending intent remains recoverable; never fail the webhook.
        return


@asynccontextmanager
async def purchase_welcome_lifespan(app):
    from app.services.purchase_welcome_runtime import start_purchase_welcome_runtime, stop_purchase_welcome_runtime
    owned = start_purchase_welcome_runtime(app)
    runtime = getattr(app.state, 'purchase_welcome_trigger', None)
    task = None
    if isinstance(runtime, PurchaseWelcomeTrigger) and runtime.policy.recovery_enabled:
        # Synchronous Firestore/HTTP runs off the event loop, after startup yields.
        task = asyncio.create_task(run_in_threadpool(runtime.recover_pending))
    try:
        yield
    finally:
        try:
            if task is not None:
                await task  # finite batch; does not release in-progress reservations
        finally:
            stop_purchase_welcome_runtime(app, owned)


def configure_purchase_welcome_trigger(app, *, firestore_client, transport, environ=None, env_file=None):
    """Future bootstrap hook. Explicit injection, no connection/default transport.

    No caller in the production entrypoints yet. Invalid config never installs
    a trigger or changes the public webhook's ability to persist commerce.
    """
    from app.config.purchase_welcome import load_purchase_welcome_config
    import os
    from dotenv import dotenv_values
    config = load_purchase_welcome_config(environ=environ, env_file=env_file)
    if config is None:
        return None
    try:
        env = os.environ if environ is None else environ
        values = dict(dotenv_values(env_file, interpolate=False)) if env_file is not None else {}
        values.update(env)
        cutoff = values.get('PURCHASE_WELCOME_NOT_BEFORE')
        if not isinstance(cutoff, str) or 'T' not in cutoff: raise ValueError
        cutoff = datetime.fromisoformat(cutoff)
        flag = values.get('PURCHASE_WELCOME_RECOVERY_ENABLED', 'false')
        if flag not in ('true', 'false'): raise ValueError
        size = values.get('PURCHASE_WELCOME_RECOVERY_BATCH_SIZE', '5')
        if not isinstance(size, str) or not size.isascii() or not size.isdecimal(): raise ValueError
        policy = WelcomeTriggerPolicy(cutoff, flag == 'true', int(size))
        return install_purchase_welcome_trigger(app, firestore_client=firestore_client,
            config=config, policy=policy, transport=transport)
    except Exception:
        raise WelcomeEmailConfigurationError() from None
