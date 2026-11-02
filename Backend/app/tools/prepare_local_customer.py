"""One synthetic customer, only in the explicitly guarded local demo emulator.

Uses the real commercial classifier/transaction; never calls a provider or the
public webhook. Existing, changed or expired fixtures are never repaired/reset.
"""
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.tools.admin_local import require_local_environment, create_local_client
from app.domain.email import normalize_email
from app.domain.email_identity import derive_email_identity
from app.domain.models import UserAccessState
from app.persistence.admin_access_eligibility import _resolve_candidate
from app.persistence.kirvano_commerce_repository import commercial_transaction, _validate_stored
from app.persistence.collections import CollectionName as C
from app.services.access_service import can_access_portal
from app.services.kirvano_commercial_service import (
    AUTHORIZED_PRODUCT_ID, AUTHORIZED_OFFER_ID, classify_commercial_event,
)
from app.services.kirvano_event_service import normalize_event, digest, SOURCE_SCOPE

EMAIL = 'cliente-teste@example.com'
USER_ID = 'local-step74-customer-v1'
SALE_ID = 'local-step74-sale-v1'
# Public synthetic fixture key, NOT an authentication credential or production key.
# Stable across terminal restarts; used only after the local emulator guards.
_FIXTURE_KEY = 'synthetic-demo-step74-email-identity-not-for-production'


class LocalCustomerError(RuntimeError):
    def __init__(self):
        super().__init__('Synthetic customer preparation not confirmed; inspect the local demo state. No reset was performed.')


def sale_payload(now, *, email=None, sale_id=None):
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=1)
    return {'event':'SALE_APPROVED', 'status':'APPROVED', 'type':'RECURRING', 'sale_id':SALE_ID if sale_id is None else sale_id,
        'customer':{'email':normalize_email(EMAIL if email is None else email)},
        'plan':{'charge_number':1, 'charge_frequency':'MONTHLY',
                'next_charge_date':(start+timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')},
        'payment':{'finished_at':start.strftime('%Y-%m-%d %H:%M:%S')},
        'products':[{'id':AUTHORIZED_PRODUCT_ID, 'offer_id':AUTHORIZED_OFFER_ID, 'is_order_bump':False}]}


def references(client):
    subscription = digest(['kirvano-subscription',1,SOURCE_SCOPE,SALE_ID])
    purchase = digest(['kirvano-charge',1,SOURCE_SCOPE,SALE_ID,1])
    event = normalize_event(sale_payload(datetime.now(timezone.utc)))
    identity = derive_email_identity(normalize_email(EMAIL),secret=_FIXTURE_KEY)
    return {C.USERS:client.collection(C.USERS.value).document(USER_ID),
        C.SUBSCRIPTIONS:client.collection(C.SUBSCRIPTIONS.value).document(subscription),
        C.PURCHASES:client.collection(C.PURCHASES.value).document(purchase),
        C.ENTITLEMENTS:client.collection(C.ENTITLEMENTS.value).document(digest(['kirvano-entitlement',1,purchase,'portal'])),
        C.EMAIL_IDENTITIES:client.collection(C.EMAIL_IDENTITIES.value).document(identity.identity_id),
        C.KIRVANO_EVENTS:client.collection(C.KIRVANO_EVENTS.value).document(event.logical_id)}


def _prepare(transaction, client, now):
    refs = references(client)
    rows = list(client.collection(C.USERS.value).where(filter=FieldFilter(
        'email_normalized','==',normalize_email(EMAIL))).limit(2).stream(transaction=transaction,timeout=10))
    snapshots = {key:ref.get(transaction=transaction,timeout=10) for key,ref in refs.items()}
    if not any(row.exists for row in snapshots.values()) and not rows:
        payload = sale_payload(now)
        event = normalize_event(payload)
        classified = classify_commercial_event(payload,timezone_name='UTC')
        if classified.candidate is None:
            raise LocalCustomerError()
        identity = derive_email_identity(normalize_email(EMAIL),secret=_FIXTURE_KEY)
        commercial_transaction(transaction,client,event,classified,identity,USER_ID)
        return 'created'
    if not all(row.exists for row in snapshots.values()) or len(rows)!=1 or rows[0].id!=USER_ID:
        raise LocalCustomerError()
    data = {key:row.to_dict() for key,row in snapshots.items()}
    for key in (C.USERS,C.SUBSCRIPTIONS,C.PURCHASES,C.ENTITLEMENTS):
        _validate_stored(key,data[key])
    user, purchase, sub, right = (data[key] for key in (C.USERS,C.PURCHASES,C.SUBSCRIPTIONS,C.ENTITLEMENTS))
    payload = sale_payload(now)
    # Preserve the original immutable period/fingerprint on every subsequent run.
    payload['payment']['finished_at'] = purchase['valid_from'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    payload['plan']['next_charge_date'] = purchase['valid_until'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    expected = normalize_event(payload)
    root = data[C.KIRVANO_EVENTS]
    variant = refs[C.KIRVANO_EVENTS].collection('variants').document(expected.fingerprint).get(transaction=transaction,timeout=10)
    projection = _resolve_candidate(transaction,client,USER_ID,snapshots[C.PURCHASES])
    identity = data[C.EMAIL_IDENTITIES]
    application = root.get('application',{})
    if (user['email_normalized']!=normalize_email(EMAIL) or user['account_status']!='enabled' or
        user['activation_status']!='pending' or purchase['status']!='active' or
        sub['status']!='active' or sub['sale_id']!=SALE_ID or
        purchase['charge_number']!=1 or
        any(purchase[key]!=value for key,value in {'source_scope':SOURCE_SCOPE,
            'product_id':AUTHORIZED_PRODUCT_ID,'offer_id':AUTHORIZED_OFFER_ID,
            'origin_event_id':expected.logical_id,'origin_fingerprint':expected.fingerprint}.items()) or
        right['status']!='granted' or projection is None or not projection.is_valid_at(now) or
        projection.subscription_status!='active' or
        can_access_portal(USER_ID,UserAccessState(**{key:user[key] for key in ('account_status','activation_status')}),[projection],now=now) or
        identity.get('user_id')!=USER_ID or any(type(identity.get(key)) is not int or identity[key]!=1
            for key in ('schema_version','normalization_version','identity_version','hmac_key_version')) or
        root.get('business_status')!='applied' or root.get('processing_status')!='received' or
        application.get('fingerprint')!=expected.fingerprint or
        any(application.get(key)!=refs[collection].id for key,collection in (
            ('user_id',C.USERS),('purchase_id',C.PURCHASES),('subscription_id',C.SUBSCRIPTIONS),('entitlement_id',C.ENTITLEMENTS))) or
        not variant.exists or variant.to_dict().get('normalized_payload')!=expected.normalized_payload):
        raise LocalCustomerError()
    return 'already_consistent'  # Read-only: no receipt counters or timestamps change.


def prepare_customer():
    client = None
    try:
        require_local_environment()
        client = create_local_client()
        now = datetime.now(timezone.utc)
        return firestore.transactional(_prepare)(client.transaction(),client,now)
    except Exception:
        raise LocalCustomerError() from None
    finally:
        if client is not None:
            client.close()


def main():
    try:
        result = prepare_customer()
    except LocalCustomerError:
        raise SystemExit(str(LocalCustomerError())) from None
    print(f'Synthetic demo customer: {result}; {EMAIL}; enabled/pending. No administrative action executed.')


if __name__ == '__main__':
    main()
