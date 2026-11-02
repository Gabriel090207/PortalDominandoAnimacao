"""Private dispatch audience; missing policy denies. No environment or I/O."""
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import SecretStr
from app.domain.email import normalize_email


@dataclass(frozen=True, repr=False)
class WelcomeAudience:
    mode: str = 'disabled'
    recipient: SecretStr | None = field(default=None,repr=False)

    def __post_init__(self):
        if self.mode not in ('disabled','test','all'):raise ValueError('Invalid welcome audience.')
        if self.mode == 'test':
            value=self.recipient.get_secret_value() if isinstance(self.recipient,SecretStr) else None
            if normalize_email(value) != value:raise ValueError('Invalid welcome audience.')
        elif self.recipient is not None:raise ValueError('Invalid welcome audience.')

    def allows(self, recipient):
        if self.mode == 'disabled':return False
        try:
            normalized=normalize_email(recipient)
            return self.mode == 'all' or normalized == self.recipient.get_secret_value()
        except Exception:return False


def welcome_cutoff(value):
    if not isinstance(value,str) or 'T' not in value:raise ValueError('Invalid welcome cutoff.')
    result=datetime.fromisoformat(value)
    if result.utcoffset() is None:raise ValueError('Invalid welcome cutoff.')
    return result
