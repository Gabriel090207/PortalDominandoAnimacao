"""Atomic inbox recording, restricted to kirvano_events and its variants."""
from google.cloud import firestore

from app.domain.kirvano_event import ReceiptResult, ValidationIssue
from app.domain.states import KirvanoEventState
from app.persistence.collections import CollectionName
from app.persistence.firestore import get_collection_reference
from app.services.kirvano_event_service import SOURCE_SCOPE
from app.services.firebase_service import get_firestore_client


def record_event(event):
    collection = get_collection_reference(CollectionName.KIRVANO_EVENTS)
    root = collection.document(event.logical_id)
    variant = root.collection('variants').document(event.fingerprint)
    return firestore.transactional(_record_transaction)(get_firestore_client().transaction(), root, variant, event)


def _record_transaction(transaction, root, variant, event):
    main_snapshot = root.get(transaction=transaction)
    variant_snapshot = variant.get(transaction=transaction)
    timestamp = firestore.SERVER_TIMESTAMP
    if not main_snapshot.exists:
        if variant_snapshot.exists:raise RuntimeError('Invalid event storage structure')
        transaction.create(root,{'schema_version':1,'source':'kirvano','source_scope':SOURCE_SCOPE,'identity_version':1,'identity_basis':event.identity_basis,'identity_confidence':event.identity_confidence,'first_fingerprint':event.fingerprint,'processing_status':event.processing_status.value,'review_reasons':list(event.validation_issues),'first_received_at':timestamp,'last_received_at':timestamp,'receipt_count':1,'variant_count':1})
        outcome='review_required' if event.processing_status==KirvanoEventState.REVIEW_REQUIRED else 'new'
        state=event.processing_status
    else:
        main=main_snapshot.to_dict()
        if (main.get('schema_version')!=1 or main.get('source')!='kirvano' or main.get('identity_version')!=1 or main.get('identity_confidence')!=event.identity_confidence or main.get('source_scope')!=SOURCE_SCOPE or main.get('identity_basis')!=event.identity_basis or type(main.get('receipt_count')) is not int or main['receipt_count']<1 or type(main.get('variant_count')) is not int or main['variant_count']<1 or not isinstance(main.get('first_fingerprint'),str) or not isinstance(main.get('review_reasons'),list)):
            raise RuntimeError('Invalid event storage structure')
        state=KirvanoEventState(main['processing_status'])
        if (main['variant_count']>1)!=(state==KirvanoEventState.CONFLICT):raise RuntimeError('Invalid conflict structure')
        if not variant_snapshot.exists and main['first_fingerprint']==event.fingerprint:raise RuntimeError('Missing original variant')
        changes={'receipt_count':main['receipt_count']+1,'last_received_at':timestamp}
        if main['variant_count']==1 and main['first_fingerprint']!=event.fingerprint and variant_snapshot.exists:raise RuntimeError('Unexpected variant')
        if variant_snapshot.exists:
            old=variant_snapshot.to_dict()
            if old.get('normalization_version')!=1 or old.get('normalized_payload')!=event.normalized_payload or old.get('validation_issues')!=list(event.validation_issues) or type(old.get('receipt_count')) is not int or old['receipt_count']<1:raise RuntimeError('Invalid variant structure')
            transaction.update(variant,{'receipt_count':old['receipt_count']+1,'last_received_at':timestamp})
            outcome='retry'
        else:
            state=KirvanoEventState.CONFLICT
            changes.update(variant_count=main['variant_count']+1,processing_status=state.value,review_reasons=sorted(set(main['review_reasons']+list(event.validation_issues)+[ValidationIssue.CONTENT_CONFLICT.value])))
            outcome='conflict'
        transaction.update(root,changes)
    if not variant_snapshot.exists:
        transaction.create(variant,{'normalization_version':1,'normalized_payload':event.normalized_payload,'validation_issues':list(event.validation_issues),'first_received_at':timestamp,'last_received_at':timestamp,'receipt_count':1})
    return ReceiptResult(event.logical_id,state,outcome)
