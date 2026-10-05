"""Authenticated-request orchestration; one commit for receipt and commerce."""
import os
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.email_identity import derive_email_identity
from app.services.kirvano_event_service import normalize_event
from app.services.kirvano_commercial_service import classify_commercial_event


def receive_commercial_event(payload):
    zone = os.getenv('KIRVANO_WEBHOOK_TIMEZONE')
    try:
        if not isinstance(zone, str) or not zone:
            raise ValueError
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise RuntimeError('Invalid commercial timezone configuration.') from None
    event = normalize_event(payload)
    commercial = classify_commercial_event(payload, timezone_name=zone)
    identity = None
    if commercial.candidate is not None:
        try:
            identity = derive_email_identity(commercial.candidate.email_normalized,
                                            secret=os.getenv('EMAIL_IDENTITY_HMAC_SECRET'))
        except ValueError:
            raise RuntimeError('Invalid commercial identity configuration.') from None
    from app.persistence.kirvano_commerce_repository import record_commercial_event
    return record_commercial_event(event, commercial, identity, uuid4().hex)
