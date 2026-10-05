"""Pure commercial candidate contracts; not access grants or persistence records."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

COMMERCIAL_SCHEMA_VERSION = 1
COMMERCIAL_IDENTITY_VERSION = 1


class CommercialClassification(StrEnum):
    ELIGIBLE = "eligible"
    REVIEW_REQUIRED = "review_required"


class CommercialReason(StrEnum):
    INVALID_STRUCTURE = "invalid_structure"
    INBOX_VALIDATION_FAILED = "inbox_validation_failed"
    EVENT_NOT_AUTHORIZED = "event_not_authorized"
    STATUS_NOT_APPROVED = "status_not_approved"
    TYPE_NOT_RECURRING = "type_not_recurring"
    INVALID_EMAIL = "invalid_email"
    INVALID_SALE_ID = "invalid_sale_id"
    INVALID_CHARGE_NUMBER = "invalid_charge_number"
    FREQUENCY_NOT_AUTHORIZED = "frequency_not_authorized"
    PRODUCT_NOT_AUTHORIZED = "product_not_authorized"
    MULTIPLE_AUTHORIZED_PRODUCTS = "multiple_authorized_products"
    INVALID_TIMEZONE = "invalid_timezone"
    INVALID_PERIOD_START = "invalid_period_start"
    INVALID_PERIOD_END = "invalid_period_end"
    INVALID_PERIOD_ORDER = "invalid_period_order"


@dataclass(frozen=True)
class CommercialCandidate:
    email_normalized: str = field(repr=False)
    sale_id: str
    charge_number: int
    charge_frequency: str
    product_id: str
    offer_id: str
    valid_from: datetime
    valid_until: datetime
    source_scope: str
    subscription_id: str
    purchase_id: str
    schema_version: int = COMMERCIAL_SCHEMA_VERSION
    identity_version: int = COMMERCIAL_IDENTITY_VERSION


@dataclass(frozen=True)
class CommercialResult:
    classification: CommercialClassification
    reason_codes: tuple[CommercialReason, ...]
    candidate: CommercialCandidate | None = None
