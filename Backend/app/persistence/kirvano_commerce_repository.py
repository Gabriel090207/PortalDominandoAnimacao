"""SALE_APPROVED only. All snapshots precede writes; no external side effects."""
from datetime import datetime
import random
import time
from google.api_core.exceptions import Aborted
from google.cloud import firestore

from app.domain.models import UserAccessState, Entitlement
from app.domain.states import AccountStatus, ActivationStatus, CommercialStatus, EntitlementStatus, ResourceKey, SubscriptionInterval, KirvanoEventState
from app.persistence.collections import CollectionName as C
from app.persistence.kirvano_events_repository import prepare_receipt
from app.services.kirvano_event_service import digest
from app.services.firebase_service import get_firestore_client

_MAX_TRANSACTION_EXECUTIONS = 3


def _is_retryable_contention(error):
    """Firestore 2.34.0 raises ValueError from Aborted after commit retries.

    Recognize only Aborted itself or that explicit cause, never messages,
    implicit context, or arbitrary wrappers/domain ValueErrors.
    """
    return isinstance(error, Aborted) or (
        type(error) is ValueError and isinstance(error.__cause__, Aborted)
    )


def _wait_before_transaction_retry(retry_number):
    base = min(0.05 * 2 ** retry_number, 0.1)
    time.sleep(min(base + random.uniform(0.0, base), 0.2))


def record_commercial_event(event, commercial, identity, candidate_user_id):
    client = get_firestore_client()
    for attempt in range(_MAX_TRANSACTION_EXECUTIONS):
        try:
            # Fresh SDK runner and transaction; UUID and immutable inputs stay fixed.
            return firestore.transactional(commercial_transaction)(client.transaction(), client, event, commercial, identity, candidate_user_id)
        except Exception as error:
            if not _is_retryable_contention(error) or attempt == _MAX_TRANSACTION_EXECUTIONS - 1:
                raise
            _wait_before_transaction_retry(attempt)


def _document(client, collection, identifier):
    return client.collection(collection.value).document(identifier)


def _read(ref, transaction):
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    if not isinstance(data, dict):
        raise RuntimeError('Invalid commercial storage structure.')
    return data


def _structure(data, required, *, versioned=True):
    if data is None:
        return
    if not required.issubset(data) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise RuntimeError('Invalid commercial storage structure.')
    if versioned and (type(data.get('identity_version')) is not int or data['identity_version'] != 1):
        raise RuntimeError('Invalid commercial identity version.')
    if 'user_id' in required and (not isinstance(data['user_id'], str) or not data['user_id'] or '/' in data['user_id']):
        raise RuntimeError('Invalid commercial user reference.')
    if not isinstance(data['created_at'], datetime) or data['created_at'].utcoffset() is None:
        raise RuntimeError('Invalid commercial timestamp.')


def _validate_stored(collection, data):
    required = {
        C.USERS: {'schema_version','email_normalized','email_normalization_version','account_status','activation_status','created_at'},
        C.SUBSCRIPTIONS: {'schema_version','identity_version','source_scope','sale_id','user_id','product_id','offer_id','interval','status','origin_event_id','created_at'},
        C.PURCHASES: {'schema_version','identity_version','source_scope','subscription_id','user_id','charge_number','product_id','offer_id','status','valid_from','valid_until','origin_event_id','origin_fingerprint','created_at'},
        C.ENTITLEMENTS: {'schema_version','identity_version','purchase_id','user_id','resource_key','status','valid_from','valid_until','created_at'},
    }[collection]
    _structure(data, required, versioned=collection != C.USERS)
    if data is None:
        return
    for key in required - {'schema_version','identity_version','email_normalization_version','charge_number','created_at','valid_from','valid_until'}:
        if not isinstance(data[key], str) or not data[key]:
            raise RuntimeError('Invalid commercial field type.')
    if collection == C.USERS:
        if type(data['email_normalization_version']) is not int or data['email_normalization_version'] != 1:
            raise RuntimeError('Invalid user email version.')
        UserAccessState(account_status=data['account_status'], activation_status=data['activation_status'])
    elif collection == C.SUBSCRIPTIONS:
        CommercialStatus(data['status'])
        SubscriptionInterval(data['interval'])
    else:
        if collection == C.PURCHASES:
            CommercialStatus(data['status'])
            if type(data['charge_number']) is not int or not 0 < data['charge_number'] <= 2**63-1:
                raise RuntimeError('Invalid stored charge.')
        for key in ('valid_from','valid_until'):
            if not isinstance(data[key], datetime) or data[key].utcoffset() is None:
                raise RuntimeError('Invalid stored commercial period.')
        Entitlement(user_id=data['user_id'], resource_key=data.get('resource_key', ResourceKey.PORTAL),
                    status=data['status'] if collection == C.ENTITLEMENTS else EntitlementStatus.GRANTED,
                    valid_from=data['valid_from'], valid_until=data['valid_until'])


def commercial_transaction(transaction, client, event, commercial, identity, candidate_user_id):
    root = _document(client, C.KIRVANO_EVENTS, event.logical_id)
    variant = root.collection('variants').document(event.fingerprint)
    main_snapshot = root.get(transaction=transaction)
    variant_snapshot = variant.get(transaction=transaction)
    plan, receipt = prepare_receipt(root, variant, event, main_snapshot, variant_snapshot)
    main = main_snapshot.to_dict() if main_snapshot.exists else {}
    application = main.get('application')
    if 'business_schema_version' in main:
        if type(main['business_schema_version']) is not int or main['business_schema_version'] != 1 or main.get('business_status') not in ('applied', 'review_required') or not isinstance(main.get('business_reason_codes'), list):
            raise RuntimeError('Invalid business receipt structure.')
        if main['business_status'] == 'applied' and application is None:
            raise RuntimeError('Missing commercial application.')
    elif application is not None:
        raise RuntimeError('Invalid commercial application.')
    if application is not None:
        keys = {'policy_version', 'fingerprint', 'processed_at', 'user_id', 'purchase_id', 'subscription_id', 'entitlement_id'}
        if not isinstance(application, dict) or set(application) != keys or type(application['policy_version']) is not int or application['policy_version'] != 1 or not isinstance(application['processed_at'], datetime):
            raise RuntimeError('Invalid commercial application.')
        for key in keys - {'policy_version', 'processed_at'}:
            if not isinstance(application[key], str) or not application[key] or '/' in application[key]:
                raise RuntimeError('Invalid application reference.')
        # Even conflicting/noneligible retries must not hide missing applied effects.
        for collection, key in ((C.USERS,'user_id'), (C.PURCHASES,'purchase_id'), (C.SUBSCRIPTIONS,'subscription_id'), (C.ENTITLEMENTS,'entitlement_id')):
            stored = _read(_document(client, collection, application[key]), transaction)
            if stored is None:
                raise RuntimeError('Missing applied commercial document.')
            _validate_stored(collection, stored)

    def finish(reason=None):
        update = {'business_schema_version': 1, 'business_status': 'review_required' if reason else 'applied',
                  'business_reason_codes': [reason] if reason else []}
        plan.update(root, update)
        plan.apply(transaction)
        return receipt

    if receipt.processing_status != KirvanoEventState.RECEIVED:
        return finish('inbox_conflict' if receipt.processing_status == KirvanoEventState.CONFLICT else 'inbox_review_required')
    candidate = commercial.candidate
    if candidate is None:
        plan.update(root, {'business_schema_version': 1, 'business_status': 'review_required',
                           'business_reason_codes': [code.value for code in commercial.reason_codes]})
        plan.apply(transaction)
        return receipt
    if identity is None or (identity.normalization_version, identity.identity_version, identity.hmac_key_version) != (1,1,1):
        raise RuntimeError('Invalid commercial identity contract.')
    entitlement_id = digest(['kirvano-entitlement', 1, candidate.purchase_id, ResourceKey.PORTAL.value])
    identity_ref = _document(client, C.EMAIL_IDENTITIES, identity.identity_id)
    subscription_ref = _document(client, C.SUBSCRIPTIONS, candidate.subscription_id)
    purchase_ref = _document(client, C.PURCHASES, candidate.purchase_id)
    entitlement_ref = _document(client, C.ENTITLEMENTS, entitlement_id)
    email_identity = _read(identity_ref, transaction)
    subscription = _read(subscription_ref, transaction)
    purchase = _read(purchase_ref, transaction)
    entitlement = _read(entitlement_ref, transaction)
    for collection, stored in ((C.SUBSCRIPTIONS,subscription),(C.PURCHASES,purchase),(C.ENTITLEMENTS,entitlement)):
        _validate_stored(collection, stored)
    if email_identity is not None:
        _structure(email_identity, {'schema_version','normalization_version','identity_version','hmac_key_version','user_id','created_at'})
        if any(type(email_identity[k]) is not int or email_identity[k] != 1 for k in ('normalization_version','hmac_key_version')):
            raise RuntimeError('Invalid email identity version.')
        user_id = email_identity['user_id']
    else:
        user_id = candidate_user_id
    user_ref = _document(client, C.USERS, user_id)
    user = _read(user_ref, transaction)
    if email_identity is not None and user is None:
        raise RuntimeError('Orphan email identity.')
    if email_identity is None and user is not None:
        raise RuntimeError('Candidate user already exists.')
    if user is not None:
        _validate_stored(C.USERS, user)
        if user['email_normalized'] != candidate.email_normalized:
            return finish('email_binding_mismatch')
    if (purchase is None) != (entitlement is None):
        raise RuntimeError('Incomplete purchase entitlement pair.')
    if purchase is not None and subscription is None:
        raise RuntimeError('Missing purchase subscription.')
    timestamp = firestore.SERVER_TIMESTAMP
    sub_data = {'schema_version':1,'identity_version':1,'source_scope':candidate.source_scope,'sale_id':candidate.sale_id,'user_id':user_id,
                'product_id':candidate.product_id,'offer_id':candidate.offer_id,'interval':SubscriptionInterval.MONTHLY.value,
                'status':CommercialStatus.ACTIVE.value,'origin_event_id':event.logical_id,'created_at':timestamp}
    purchase_data = {'schema_version':1,'identity_version':1,'source_scope':candidate.source_scope,'subscription_id':candidate.subscription_id,'user_id':user_id,
                     'charge_number':candidate.charge_number,'product_id':candidate.product_id,'offer_id':candidate.offer_id,
                     'status':CommercialStatus.ACTIVE.value,'valid_from':candidate.valid_from,'valid_until':candidate.valid_until,
                     'origin_event_id':event.logical_id,'origin_fingerprint':event.fingerprint,'created_at':timestamp}
    entitlement_data = {'schema_version':1,'identity_version':1,'purchase_id':candidate.purchase_id,'user_id':user_id,
                        'resource_key':ResourceKey.PORTAL.value,'status':EntitlementStatus.GRANTED.value,
                        'valid_from':candidate.valid_from,'valid_until':candidate.valid_until,'created_at':timestamp}
    for existing, expected in ((subscription,sub_data),(purchase,purchase_data),(entitlement,entitlement_data)):
        if existing is None:
            continue
        _structure(existing, set(expected))
        if expected is purchase_data:
            CommercialStatus(existing['status'])
            if type(existing['charge_number']) is not int or existing['charge_number'] <= 0:
                raise RuntimeError('Invalid stored charge.')
        elif expected is sub_data:
            CommercialStatus(existing['status'])
        else:
            Entitlement(**{key:existing[key] for key in ('user_id','resource_key','status','valid_from','valid_until')})
            if existing['valid_until'] is None:
                raise RuntimeError('Missing recurring period end.')
        # A subscription may originate from an earlier charge/event.
        excluded = {'created_at','status'} | ({'origin_event_id'} if expected is sub_data else set())
        if any(existing[key] != value for key,value in expected.items() if key not in excluded):
            return finish('commercial_binding_mismatch')
    if email_identity is None and any(item is not None for item in (subscription,purchase,entitlement)):
        return finish('identity_missing_for_existing_commerce')
    expected_application = {'policy_version':1,'fingerprint':event.fingerprint,'user_id':user_id,
                            'purchase_id':candidate.purchase_id,'subscription_id':candidate.subscription_id,'entitlement_id':entitlement_id}
    if application is not None:
        if any(application[key] != value for key,value in expected_application.items()):
            return finish('application_binding_mismatch')
        return finish()  # Proven retry: never restore subsequent commercial states.
    if purchase is not None:
        return finish('unproven_existing_purchase')
    if subscription is not None and subscription['status'] != CommercialStatus.ACTIVE.value:
        return finish('subscription_not_active')
    if user is None:
        plan.create(user_ref, {'schema_version':1,'email_normalized':candidate.email_normalized,'email_normalization_version':1,
                               'account_status':AccountStatus.ENABLED.value,'activation_status':ActivationStatus.PENDING.value,'created_at':timestamp})
        plan.create(identity_ref, {'schema_version':1,'normalization_version':1,'identity_version':1,'hmac_key_version':1,'user_id':user_id,'created_at':timestamp})
    if subscription is None:
        plan.create(subscription_ref, sub_data)
    plan.create(purchase_ref, purchase_data)
    plan.create(entitlement_ref, entitlement_data)
    plan.update(root, {'application': {**expected_application,'processed_at':timestamp}})
    return finish()
