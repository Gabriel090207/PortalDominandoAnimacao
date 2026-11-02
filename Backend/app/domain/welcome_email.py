"""Post-purchase intent only. No delivery state machine or provider side effects."""
from typing import Literal
import unicodedata
import hashlib
import json

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from app.domain.email import normalize_email


def optional_customer_name(value):
    """Optional provider metadata, not identity or verified legal name."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 200 or any(unicodedata.category(c).startswith('C') for c in value):
        return None
    return value


def welcome_intent_id(purchase_id):
    return hashlib.sha256(json.dumps(['purchase-welcome', 1, purchase_id],
        separators=(',', ':')).encode('utf-8')).hexdigest()


class WelcomeEmailIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)
    schema_version: Literal[1] = 1
    kind: Literal['purchase_welcome'] = 'purchase_welcome'
    template_version: Literal[1] = 1
    status: Literal['pending'] = 'pending'
    purchase_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    user_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    origin_event_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    recipient: str = Field(repr=False)
    customer_name: str | None = Field(default=None, repr=False)
    created_at: AwareDatetime

    @field_validator('recipient')
    @classmethod
    def normalized_recipient(cls, value):
        if normalize_email(value) != value:
            raise ValueError('Normalized recipient required.')
        return value

    @field_validator('customer_name')
    @classmethod
    def safe_name(cls, value):
        if value is not None and optional_customer_name(value) != value:
            raise ValueError('Invalid optional name.')
        return value
