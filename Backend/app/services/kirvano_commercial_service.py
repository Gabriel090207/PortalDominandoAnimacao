"""Pure extraction only. Call with authenticated data and explicit configuration.

The future caller must supply os.getenv('KIRVANO_WEBHOOK_TIMEZONE'). This module
does not read environment, log, persist, or change inbox identities.
"""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.email import normalize_email
from app.domain.kirvano_commercial import (
    COMMERCIAL_IDENTITY_VERSION, CancellationCandidate, CommercialCandidate, CommercialClassification,
    CommercialReason as Reason, CommercialResult,
)
from app.services.kirvano_event_service import SOURCE_SCOPE, digest, normalize_event

AUTHORIZED_PRODUCT_ID = "0c5f6369-5a8a-467c-ba81-61cde05b7917"
AUTHORIZED_OFFER_ID = "75562bd7-4d63-4463-bc3e-53439a130710"
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\Z")


def _parse_timestamp(value, zone):
    if zone is None or not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        return None
    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        # Round-trip rejects nonexistent local times. Distinct valid instants
        # reject ambiguous local times rather than arbitrarily choosing fold.
        instants = set()
        for fold in (0, 1):
            utc = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                instants.add(utc)
        return instants.pop() if len(instants) == 1 else None
    except (ValueError, OverflowError):
        return None


def classify_commercial_event(payload, *, timezone_name: str | None) -> CommercialResult:
    """Eligibility is only a candidate classification, never permission to access."""
    reasons = set()
    if not isinstance(payload, dict):
        return CommercialResult(CommercialClassification.REVIEW_REQUIRED, (Reason.INVALID_STRUCTURE,))
    normalized = normalize_event(payload)
    if normalized.validation_issues:
        reasons.add(Reason.INBOX_VALIDATION_FAILED)
    data = normalized.normalized_payload
    cancellation = payload.get('event') == 'SUBSCRIPTION_CANCELED'
    if payload.get('event') not in ('SALE_APPROVED', 'SUBSCRIPTION_RENEWED', 'SUBSCRIPTION_CANCELED'):
        reasons.add(Reason.EVENT_NOT_AUTHORIZED)
    for key, expected, reason in (
        ('status', 'CANCELED' if cancellation else 'APPROVED', Reason.STATUS_NOT_CANCELED if cancellation else Reason.STATUS_NOT_APPROVED),
        ('type', 'RECURRING', Reason.TYPE_NOT_RECURRING),
    ):
        if payload.get(key) != expected:
            reasons.add(reason)
    sale_id = data.get('sale_id')
    charge = data.get('charge_number')
    if sale_id is None:
        reasons.add(Reason.INVALID_SALE_ID)
    if charge is None:
        reasons.add(Reason.INVALID_CHARGE_NUMBER)
    if data.get('charge_frequency') != 'MONTHLY':
        reasons.add(Reason.FREQUENCY_NOT_AUTHORIZED)
    customer = payload.get('customer')
    email = None
    if not isinstance(customer, dict):
        reasons.add(Reason.INVALID_STRUCTURE)
    else:
        try:
            email = normalize_email(customer.get('email'))
        except ValueError:
            pass
    if email is None:
        reasons.add(Reason.INVALID_EMAIL)
    for key in (('plan', 'products') if cancellation else ('plan', 'payment', 'products')):
        expected = list if key == 'products' else dict
        if not isinstance(payload.get(key), expected):
            reasons.add(Reason.INVALID_STRUCTURE)
    matches = [item for item in data.get('products', [])
               if item.get('product_id') == AUTHORIZED_PRODUCT_ID
               and item.get('offer_id') == AUTHORIZED_OFFER_ID
               and item.get('is_order_bump') is False]
    if not matches:
        reasons.add(Reason.PRODUCT_NOT_AUTHORIZED)
    elif len(matches) > 1:
        reasons.add(Reason.MULTIPLE_AUTHORIZED_PRODUCTS)
    zone = None
    if isinstance(timezone_name, str) and timezone_name:
        try:
            zone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    if zone is None:
        reasons.add(Reason.INVALID_TIMEZONE)
    if not cancellation:
        start = _parse_timestamp(data.get('payment_finished_at'), zone)
        end = _parse_timestamp(data.get('next_charge_date'), zone)
        if start is None:
            reasons.add(Reason.INVALID_PERIOD_START)
        if end is None:
            reasons.add(Reason.INVALID_PERIOD_END)
        if start is not None and end is not None and end <= start:
            reasons.add(Reason.INVALID_PERIOD_ORDER)
    if reasons:
        return CommercialResult(CommercialClassification.REVIEW_REQUIRED, tuple(sorted(reasons)))
    subscription_id = digest(['kirvano-subscription', COMMERCIAL_IDENTITY_VERSION, SOURCE_SCOPE, sale_id])
    if cancellation:
        return CommercialResult(CommercialClassification.ELIGIBLE, (), CancellationCandidate(
            email, sale_id, charge, 'MONTHLY', AUTHORIZED_PRODUCT_ID, AUTHORIZED_OFFER_ID,
            SOURCE_SCOPE, subscription_id,
        ))
    purchase_id = digest(['kirvano-charge', COMMERCIAL_IDENTITY_VERSION, SOURCE_SCOPE, sale_id, charge])
    return CommercialResult(CommercialClassification.ELIGIBLE, (), CommercialCandidate(
        email, sale_id, charge, 'MONTHLY', AUTHORIZED_PRODUCT_ID, AUTHORIZED_OFFER_ID,
        start, end, SOURCE_SCOPE, subscription_id, purchase_id,
    ))
