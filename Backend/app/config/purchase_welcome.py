"""Explicit dispatch configuration. Never called by webhook or startup."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from dotenv import dotenv_values
from pydantic import SecretStr
from app.domain.email import normalize_email
from app.services.purchase_welcome_email import WelcomeEmailContact, WelcomeEmailConfigurationError

_ENV_FILE = Path(__file__).resolve().parents[2] / '.env'


@dataclass(frozen=True, repr=False)
class PurchaseWelcomeConfig:
    enabled: bool
    api_key: SecretStr = field(repr=False)
    sender: str
    contact: WelcomeEmailContact

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
        return PurchaseWelcomeConfig(True, SecretStr(values.get('RESEND_API_KEY', '')),
            values.get('PURCHASE_WELCOME_FROM'),
            WelcomeEmailContact(values.get('PURCHASE_WELCOME_WHATSAPP_URL')))
    except Exception:
        raise WelcomeEmailConfigurationError() from None
