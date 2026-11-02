"""Durable single-attempt dispatch contracts, extending existing pending intent."""
from datetime import datetime
from typing import Literal
import hashlib
import json
import re
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from app.domain.email import normalize_email
from app.domain.welcome_email import WelcomeEmailIntent, welcome_intent_id

Reason = Literal['accepted', 'rejected', 'authentication', 'quota', 'idempotency_conflict',
    'concurrent_request', 'network', 'timeout', 'unknown_response', 'invalid_response',
    'internal_failure', 'interrupted']


def resend_idempotency_key(intent_id):
    if not isinstance(intent_id, str) or not re.fullmatch(r'[0-9a-f]{64}', intent_id):
        raise ValueError('Invalid welcome dispatch identifier.')
    return 'purchase-welcome/' + intent_id


class WelcomeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)
    sender: str = Field(repr=False)
    recipient: str = Field(repr=False)
    subject: str = Field(min_length=1, max_length=998, repr=False)
    html: str = Field(min_length=1, max_length=200000, repr=False)
    text: str = Field(min_length=1, max_length=200000, repr=False)

    @model_validator(mode='after')
    def valid_mailboxes(self):
        if any(normalize_email(v) != v for v in (self.sender, self.recipient)):
            raise ValueError('Canonical mailboxes required.')
        if '\r' in self.subject or '\n' in self.subject:
            raise ValueError('Invalid subject.')
        return self

    def payload(self):
        return {'from': self.sender, 'to': [self.recipient], 'subject': self.subject,
                'html': self.html, 'text': self.text}

    def digest(self):
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True, ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest()


class WelcomeProviderResult(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)
    reason: Reason
    provider_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

    @model_validator(mode='after')
    def acceptance(self):
        if (self.reason == 'accepted') != (self.provider_id is not None):
            raise ValueError('Invalid provider acceptance.')
        return self


class WelcomeDispatchRecord(WelcomeEmailIntent):
    status: Literal['pending', 'in_progress', 'accepted', 'requires_review'] = 'pending'
    attempt_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    reserved_at: AwareDatetime | None = None
    request: WelcomeRequest | None = Field(default=None, repr=False)
    request_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    idempotency_key: str | None = None
    finished_at: AwareDatetime | None = None
    reason: Reason | None = None
    provider_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

    @model_validator(mode='after')
    def valid_dispatch_state(self):
        reserved = (self.attempt_id, self.reserved_at, self.request, self.request_digest, self.idempotency_key)
        finished = (self.finished_at, self.reason)
        if self.status == 'pending':
            if any(v is not None for v in (*reserved, *finished, self.provider_id)):
                raise ValueError('Pending intent already has dispatch metadata.')
        else:
            if any(v is None for v in reserved):
                raise ValueError('Missing dispatch reservation.')
            if self.request.recipient != self.recipient or self.request.digest() != self.request_digest:
                raise ValueError('Inconsistent request snapshot.')
            if self.idempotency_key != resend_idempotency_key(welcome_intent_id(self.purchase_id)):
                raise ValueError('Inconsistent idempotency key.')
            if self.reserved_at < self.created_at:
                raise ValueError('Invalid reservation time.')
            if self.status == 'in_progress':
                if any(v is not None for v in (*finished, self.provider_id)):
                    raise ValueError('In-progress intent has a result.')
            else:
                if any(v is None for v in finished) or self.finished_at < self.reserved_at:
                    raise ValueError('Missing dispatch result.')
                result = WelcomeProviderResult(reason=self.reason, provider_id=self.provider_id)
                if (self.status == 'accepted') != (result.reason == 'accepted'):
                    raise ValueError('Inconsistent dispatch outcome.')
        return self

    def pending_intent(self):
        return WelcomeEmailIntent.model_validate({key: getattr(self, key) for key in WelcomeEmailIntent.model_fields})
