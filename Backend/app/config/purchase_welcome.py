"""Read-only dispatch configuration; public startup uses process-only opt-in."""
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import re
from dotenv import dotenv_values
from pydantic import SecretStr
from app.domain.email import normalize_email
from app.domain.welcome_audience import WelcomeAudience, welcome_cutoff
from app.services.purchase_welcome_email import WelcomeEmailContact, WelcomeEmailConfigurationError

_ENV_FILE = Path(__file__).resolve().parents[2] / '.env'


@dataclass(frozen=True, repr=False)
class PurchaseWelcomeConfig:
    enabled: bool
    api_key: SecretStr = field(repr=False)
    sender: str
    contact: WelcomeEmailContact
    audience: WelcomeAudience = field(default_factory=WelcomeAudience,repr=False)
    not_before: datetime | None = None

    def __post_init__(self):
        try:
            if type(self.enabled) is not bool or not self.enabled:
                raise ValueError
            key = self.api_key.get_secret_value()
            if not re.fullmatch(r're_[A-Za-z0-9_-]{8,200}', key):
                raise ValueError
            # A bare, canonical mailbox; verification with Resend is operational.
            if normalize_email(self.sender) != self.sender:
                raise ValueError
            if not isinstance(self.contact, WelcomeEmailContact):
                raise ValueError
            WelcomeEmailContact(self.contact.whatsapp_url)
            if not isinstance(self.audience,WelcomeAudience):raise ValueError
            WelcomeAudience(self.audience.mode,self.audience.recipient)
            if self.not_before is not None and (not isinstance(self.not_before,datetime) or self.not_before.utcoffset() is None):raise ValueError
        except Exception:
            raise WelcomeEmailConfigurationError() from None


def load_purchase_welcome_config(*, environ=None, env_file=_ENV_FILE):
    """Process-only opt-in. No env mutation, interpolation or secret generation."""
    try:
        env = os.environ if environ is None else environ
        enabled = env.get('PURCHASE_WELCOME_SEND_ENABLED', 'false')
        if enabled == 'false':
            return None
        if enabled != 'true':
            raise ValueError
        values = dict(dotenv_values(env_file, interpolate=False)) if env_file is not None else {}
        values.update(env)
        mode=values.get('PURCHASE_WELCOME_AUDIENCE_MODE')
        if mode == 'all':
            audience=WelcomeAudience('all')
        elif mode == 'test' and values.get('PURCHASE_WELCOME_TEST_AUTHORIZED') == 'true':
            audience=WelcomeAudience('test',SecretStr(normalize_email(values.get('PURCHASE_WELCOME_TEST_RECIPIENT'))))
        else:
            raise ValueError
        return PurchaseWelcomeConfig(True, SecretStr(values.get('RESEND_API_KEY', '')),
            values.get('PURCHASE_WELCOME_FROM'),
            WelcomeEmailContact(values.get('PURCHASE_WELCOME_WHATSAPP_URL')),audience,
            welcome_cutoff(values.get('PURCHASE_WELCOME_NOT_BEFORE')))
    except Exception:
        raise WelcomeEmailConfigurationError() from None
