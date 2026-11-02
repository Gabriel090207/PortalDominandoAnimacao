"""Controlled single-intent dispatch, reused by the explicitly installed trigger."""
from datetime import datetime, timezone
import secrets
from app.config.purchase_welcome import PurchaseWelcomeConfig
from app.domain.welcome_dispatch import WelcomeRequest, WelcomeProviderResult
from app.persistence.welcome_emails_repository import WelcomeEmailsRepository
from app.services.purchase_welcome_email import (
    render_purchase_welcome, RenderedWelcomeEmail, WelcomeEmailConfigurationError,
)
from app.services.resend_email_provider import ResendEmailProvider


class WelcomeDispatchUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Purchase welcome email dispatch not confirmed; internal reconciliation required.')


class PurchaseWelcomeDispatchService:
    def __init__(self, repository, provider, config, *, clock=None):
        if not isinstance(config, PurchaseWelcomeConfig) or not config.enabled:
            raise WelcomeEmailConfigurationError()
        self.repository, self.provider, self.config = repository, provider, config
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _request(self, intent):
        message = render_purchase_welcome(intent, contact=self.config.contact)
        return WelcomeRequest(sender=self.config.sender, recipient=message.recipient,
            subject=message.subject, html=message.html, text=message.text)

    def dispatch(self, identifier, *, not_before=None):
        """Only the invocation receiving a confirmed reservation can call HTTP.

        No retries: accepted, in-progress and review records never send again.
        A storage exception (including ambiguous claim commit) always stops HTTP.
        """
        attempt_id = secrets.token_hex(32)
        try:
            options = {} if not_before is None else {'not_before':not_before}
            reserved = self.repository.reserve(identifier, attempt_id=attempt_id,
                now=self.clock(), build_request=self._request, **options)
        except Exception:
            raise WelcomeDispatchUnavailable() from None
        if reserved is None:
            return 'not_dispatched'
        request = reserved.request
        try:
            message = RenderedWelcomeEmail(request.recipient, request.subject, request.html, request.text)
            result = self.provider.send(message, sender=request.sender, idempotency_key=reserved.idempotency_key)
            result = WelcomeProviderResult.model_validate(result.model_dump())
        except Exception:
            # Could be before OR after external effects. Never infer non-delivery.
            result = WelcomeProviderResult(reason='internal_failure')
        try:
            confirmed = self.repository.finish(identifier, attempt_id=attempt_id, result=result, now=self.clock())
            if not confirmed:
                raise ValueError
        except Exception:
            # Do not resend or overwrite reservation if acceptance cannot be stored.
            raise WelcomeDispatchUnavailable() from None
        return 'accepted' if result.reason == 'accepted' else 'requires_review'


def create_purchase_welcome_dispatch(*, firestore_client, config, transport=None, provider=None):
    """Explicit composition only. No automatic env loading or live transport."""
    if (transport is None) == (provider is None):
        raise WelcomeEmailConfigurationError()
    return PurchaseWelcomeDispatchService(WelcomeEmailsRepository(firestore_client),
        provider if provider is not None else ResendEmailProvider(config, transport=transport), config)
