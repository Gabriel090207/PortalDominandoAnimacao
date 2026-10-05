"""Allowlisted normalization and versioned candidate identities; no commerce."""
import hashlib
import json
import re
from datetime import datetime

from app.domain.kirvano_event import NormalizedEvent, ValidationIssue
from app.domain.states import KirvanoEventState

SOURCE_SCOPE = "kirvano-primary-v1"  # Stable across deploys and token rotations.
SUPPORTED_EVENTS = frozenset({'SALE_APPROVED', 'SUBSCRIPTION_RENEWED', 'SUBSCRIPTION_CANCELED', 'SALE_REFUNDED', 'SALE_CHARGEBACK'})
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_LABEL = re.compile(r'[A-Z][A-Z0-9_]{0,63}\Z')
_MONEY = re.compile(r'(?:[A-Z]{1,3}\$?\s*)?[0-9][0-9.,]{0,31}\Z')


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def normalize_event(payload) -> NormalizedEvent:
    normalized = {}
    issues = []

    def issue(kind, field):
        issues.append(f'{kind.value}:{field}')

    def extract(source, key, target, destination, kind):
        value = source.get(key)
        if value is None:
            return
        valid = False
        if kind == 'charge':
            valid = type(value) is int and 0 < value <= 2**63-1
        elif kind == 'bool':
            valid = type(value) is bool
        elif isinstance(value, str):
            if kind == 'id': valid = bool(_ID.fullmatch(value))
            elif kind == 'label': valid = bool(_LABEL.fullmatch(value))
            elif kind == 'money': valid = bool(_MONEY.fullmatch(value))
            elif kind == 'date' and len(value) <= 40:
                try:
                    datetime.fromisoformat(value)
                    valid = 'T' in value or ' ' in value
                except ValueError:
                    pass
        if valid: destination[target] = value
        else: issue(ValidationIssue.INVALID_FIELD, target)

    if not isinstance(payload, dict):
        issue(ValidationIssue.INVALID_STRUCTURE, 'payload')
        payload = {}
    for key, target, kind in [('event','event','label'),('sale_id','sale_id','id'),('checkout_id','checkout_id','id'),('type','sale_type','label'),('status','provider_status','label'),('created_at','provider_created_at','date'),('total_price','total_price','money')]:
        extract(payload,key,target,normalized,kind)
    for container, fields in [('plan',[('charge_number','charge_number','charge'),('charge_frequency','charge_frequency','label'),('next_charge_date','next_charge_date','date')]),('payment',[('finished_at','payment_finished_at','date')])]:
        value = payload.get(container)
        if value is not None:
            if not isinstance(value,dict):issue(ValidationIssue.INVALID_STRUCTURE,container)
            else:
                for key,target,kind in fields:extract(value,key,target,normalized,kind)
    products = payload.get('products')
    if products is not None:
        if not isinstance(products,list) or len(products)>100:
            issue(ValidationIssue.INVALID_STRUCTURE,'products')
        else:
            entries=[]
            for product in products:
                if not isinstance(product,dict):
                    issue(ValidationIssue.INVALID_STRUCTURE,'product')
                    continue
                item={}
                for key,target,kind in [('id','product_id','id'),('offer_id','offer_id','id'),('price','price','money'),('is_order_bump','is_order_bump','bool')]:extract(product,key,target,item,kind)
                entries.append(item)
            # Complete typed canonical tuple; duplicates deliberately preserved.
            entries.sort(key=lambda item:tuple(canonical_json(item.get(key)) for key in ('product_id','offer_id','price','is_order_bump')))
            normalized['products']=entries
    if normalized.get('event') not in SUPPORTED_EVENTS:issue(ValidationIssue.UNKNOWN_EVENT,'event')
    for key in ('sale_id','charge_number'):
        if key not in normalized:issue(ValidationIssue.MISSING_IDENTITY,key)
    issues=tuple(sorted(issues))
    fingerprint=digest({'purpose':'kirvano-event-content','version':1,'normalized_payload':normalized,'validation_issues':issues})
    candidate=normalized.get('event') in SUPPORTED_EVENTS and 'sale_id' in normalized and 'charge_number' in normalized
    logical_id=digest(['kirvano-event-identity',1,SOURCE_SCOPE,normalized['sale_id'],normalized['event'],normalized['charge_number']]) if candidate else digest(['kirvano-event-fallback',1,SOURCE_SCOPE,fingerprint])
    return NormalizedEvent(logical_id,fingerprint,normalized,issues,'sale_event_charge' if candidate else 'content_fallback','candidate' if candidate else 'insufficient',KirvanoEventState.REVIEW_REQUIRED if issues or not candidate else KirvanoEventState.RECEIVED)


def register_event(payload):
    from app.persistence.kirvano_events_repository import record_event
    return record_event(normalize_event(payload))
