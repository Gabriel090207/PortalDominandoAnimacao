"""Shared bounded purchase/right/subscription resolution for portal access."""
from google.cloud.firestore_v1.base_query import FieldFilter
from app.domain.models import PortalEntitlement,UserAccessState
from app.domain.states import ActivationStatus,CommercialStatus,ResourceKey,SubscriptionInterval
from app.domain.admin_customers import customer_identifier
from app.persistence.collections import CollectionName as C
from app.persistence.kirvano_commerce_repository import _validate_stored
from app.services.access_service import can_access_portal
from app.services.kirvano_event_service import digest


def _resolve_candidate(transaction,client,identifier,snapshot):
    purchase=snapshot.to_dict();_validate_stored(C.PURCHASES,purchase)
    if purchase['user_id']!=identifier or purchase['status']!=CommercialStatus.ACTIVE.value:
        raise ValueError
    purchase_id=customer_identifier(snapshot.id)
    subscription_id=customer_identifier(purchase['subscription_id'])
    right_id=digest(['kirvano-entitlement',1,purchase_id,ResourceKey.PORTAL.value])
    stored=client.collection(C.ENTITLEMENTS.value).document(right_id).get(transaction=transaction,timeout=10)
    if not stored.exists:return None
    right=stored.to_dict();_validate_stored(C.ENTITLEMENTS,right)
    if (right['user_id']!=identifier or right['purchase_id']!=purchase_id or
        right['valid_from']!=purchase['valid_from'] or right['valid_until']!=purchase['valid_until']):
        return None
    stored=client.collection(C.SUBSCRIPTIONS.value).document(subscription_id).get(transaction=transaction,timeout=10)
    if not stored.exists:return None
    subscription=stored.to_dict();_validate_stored(C.SUBSCRIPTIONS,subscription)
    if subscription['status']==CommercialStatus.ACTIVE.value and 'cancellation' in subscription:
        raise ValueError('Inconsistent commercial state.')
    expected_id=digest(['kirvano-subscription',1,subscription['source_scope'],subscription['sale_id']])
    if (subscription_id!=expected_id or subscription['interval']!=SubscriptionInterval.MONTHLY.value or
        any(subscription[key]!=purchase[key] for key in ('user_id','source_scope','product_id','offer_id'))):
        return None
    return PortalEntitlement(**{key:right[key] for key in ('user_id','resource_key','status','valid_from','valid_until')},
        purchase_id=purchase_id,subscription_id=subscription_id,subscription_status=subscription['status'])


def has_eligible_portal_access(transaction,client,identifier,account_status,now):
    """Evaluate proposed ACTIVE using one canonical access rule.

    Per-user indexed candidates, one snapshot per request and cursor pagination;
    point reads follow persisted IDs. No collection scan, offset or global veto.
    Missing/ineligible bindings do not grant access. Corruption/I/O propagates for
    callers to sanitize as unavailable, never as a positive authorization.
    All reads are part of the caller's transaction, before any administrative write.
    """
    if now.utcoffset() is None:raise ValueError
    query=client.collection(C.PURCHASES.value)
    for field,op,value in [('user_id','==',identifier),('status','==',CommercialStatus.ACTIVE.value),
        ('valid_from','<=',now),('valid_until','>',now)]:
        query=query.where(filter=FieldFilter(field,op,value))
    cursor=None;seen=set()
    while True:
        page=query.start_after(cursor) if cursor is not None else query
        rows=list(page.limit(1).stream(transaction=transaction,timeout=10))
        if not rows:return False
        if len(rows)!=1 or rows[0].id in seen:raise ValueError
        seen.add(rows[0].id)
        right=_resolve_candidate(transaction,client,identifier,rows[0])
        if right is not None and can_access_portal(identifier,UserAccessState(account_status=account_status,
            activation_status=ActivationStatus.ACTIVE),[right],now=now):return True
        cursor=rows[0]
