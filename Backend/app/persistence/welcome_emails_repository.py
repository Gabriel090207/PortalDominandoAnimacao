"""Injected Firestore client, single non-reusable claim. No HTTP, env or logging."""
from datetime import timedelta
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from app.domain.welcome_audience import WelcomeAudience
from app.domain.welcome_dispatch import (
    WelcomeDispatchRecord, WelcomeProviderResult, WelcomeRequest, resend_idempotency_key,
)
from app.domain.welcome_email import welcome_intent_id
from app.persistence.collections import CollectionName as C
from app.persistence.kirvano_commerce_repository import _validate_stored


class WelcomeEmailStorageError(RuntimeError):
    def __init__(self):
        super().__init__('Purchase welcome email storage unavailable.')


class WelcomeEmailsRepository:
    def __init__(self, client, *, audience=None, not_before=None):
        self.client = client
        self._audience = WelcomeAudience() if audience is None else WelcomeAudience(audience.mode,audience.recipient)
        self._not_before = not_before

    def for_policy(self, audience, not_before):
        return type(self)(self.client,audience=audience,not_before=not_before)

    def _ref(self, identifier):
        resend_idempotency_key(identifier)
        return self.client.collection(C.TRANSACTIONAL_EMAILS.value).document(identifier)

    def _read(self, transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        record = WelcomeDispatchRecord.model_validate(snapshot.to_dict())
        if welcome_intent_id(record.purchase_id) != ref.id:
            raise ValueError
        return record

    def _eligible(self, transaction, record):
        def read(collection, identifier):
            snapshot = self.client.collection(collection.value).document(identifier).get(transaction=transaction)
            if not snapshot.exists: raise ValueError
            return snapshot.to_dict()
        purchase = read(C.PURCHASES, record.purchase_id)
        user = read(C.USERS, record.user_id)
        event = read(C.KIRVANO_EVENTS, record.origin_event_id)
        variant = self.client.collection(C.KIRVANO_EVENTS.value).document(record.origin_event_id).collection(
            'variants').document(purchase['origin_fingerprint']).get(transaction=transaction)
        _validate_stored(C.PURCHASES, purchase)
        _validate_stored(C.USERS, user)
        application = event.get('application', {})
        if (purchase['user_id'] != record.user_id or purchase['origin_event_id'] != record.origin_event_id
            or purchase['status'] != 'active' or user['email_normalized'] != record.recipient
            or event.get('business_status') != 'applied'
            or application.get('purchase_id') != record.purchase_id
            or application.get('user_id') != record.user_id
            or application.get('fingerprint') != purchase['origin_fingerprint']
            or not variant.exists
            or variant.to_dict().get('normalized_payload', {}).get('event') != 'SALE_APPROVED'):
            raise ValueError
        return purchase

    def reserve(self, identifier, *, attempt_id, now, build_request, not_before=None):
        try:
            return firestore.transactional(self._reserve)(self.client.transaction(), self._ref(identifier),
                attempt_id, now, build_request, not_before)
        except Exception:
            raise WelcomeEmailStorageError() from None

    def _reserve(self, transaction, ref, attempt_id, now, build_request, not_before=None):
        if self._not_before is not None:
            not_before = self._not_before if not_before is None else max(self._not_before,not_before)
        if not_before is None:return None  # No temporal authorization, no claim.
        record = self._read(transaction, ref)
        if record is None or record.status != 'pending':
            return None
        if not self._audience.allows(record.recipient):return None
        if not_before is not None:
            if not_before.utcoffset() is None: raise ValueError
            if record.created_at < not_before: return None
        purchase = self._eligible(transaction, record)
        if not_before is not None:
            # valid_from is the approved payment.finished_at, validated and
            # converted to UTC by the commercial classifier. created_at is the
            # server timestamp. A newly processed OLD sale must not pass.
            if purchase['valid_from'] < not_before or purchase['created_at'] < not_before or purchase['valid_from'] > now:
                return None
        request = WelcomeRequest.model_validate(build_request(record.pending_intent()).model_dump())
        changes = {'status':'in_progress', 'attempt_id':attempt_id, 'reserved_at':now,
            'request':request.model_dump(), 'request_digest':request.digest(),
            'idempotency_key':resend_idempotency_key(ref.id)}
        reserved = WelcomeDispatchRecord.model_validate({**record.model_dump(), **changes})
        transaction.update(ref, changes)
        return reserved

    def pending_for_event(self, event_id, *, not_before):
        try:
            # Same identifier format as an intent, but separate collection.
            resend_idempotency_key(event_id)
            root = self.client.collection(C.KIRVANO_EVENTS.value).document(event_id).get(timeout=10)
            if not root.exists: return None
            application = root.to_dict().get('application', {})
            purchase_id = application.get('purchase_id')
            if purchase_id is None: return None
            ref = self._ref(welcome_intent_id(purchase_id))
            snapshot = ref.get(timeout=10)
            if not snapshot.exists: return None
            record = WelcomeDispatchRecord.model_validate(snapshot.to_dict())
            if (record.status != 'pending' or record.origin_event_id != event_id
                or welcome_intent_id(record.purchase_id) != ref.id
                or record.created_at < not_before): return None
            return ref.id
        except Exception:
            raise WelcomeEmailStorageError() from None

    def pending_batch(self, *, not_before, limit):
        try:
            if not_before.utcoffset() is None or type(limit) is not int or not 1 <= limit <= 20: raise ValueError
            query = self.client.collection(C.TRANSACTIONAL_EMAILS.value).where(
                filter=FieldFilter('status','==','pending')).where(
                filter=FieldFilter('kind','==','purchase_welcome')).where(
                filter=FieldFilter('created_at','>=',not_before)).order_by('created_at').order_by('__name__').limit(limit)
            identifiers = []
            for snapshot in query.stream(timeout=10):
                record = WelcomeDispatchRecord.model_validate(snapshot.to_dict())
                if (record.status != 'pending' or record.created_at < not_before
                    or snapshot.id != welcome_intent_id(record.purchase_id)): raise ValueError
                identifiers.append(snapshot.id)
            return identifiers
        except Exception:
            raise WelcomeEmailStorageError() from None

    def finish(self, identifier, *, attempt_id, result, now):
        try:
            result = WelcomeProviderResult.model_validate(result.model_dump())
            return firestore.transactional(self._finish)(self.client.transaction(), self._ref(identifier),
                attempt_id, result, now)
        except Exception:
            raise WelcomeEmailStorageError() from None

    def _finish(self, transaction, ref, attempt_id, result, now):
        record = self._read(transaction, ref)
        if record is None or record.status != 'in_progress' or record.attempt_id != attempt_id:
            return False
        changes = {'status':'accepted' if result.reason == 'accepted' else 'requires_review',
            'finished_at':now, 'reason':result.reason, 'provider_id':result.provider_id}
        WelcomeDispatchRecord.model_validate({**record.model_dump(), **changes})
        transaction.update(ref, changes)
        return True

    def review_interrupted(self, identifier, *, now, minimum_age=timedelta(minutes=10)):
        """Explicit reconciliation operation; NEVER releases a claim for resending.

        This threshold only flags a case for review, not a safe-to-retry lease.
        Late results cannot overwrite that review decision.
        """
        try:
            if not isinstance(minimum_age, timedelta) or minimum_age <= timedelta(0): raise ValueError
            return firestore.transactional(self._review_interrupted)(self.client.transaction(),
                self._ref(identifier), now, minimum_age)
        except Exception:
            raise WelcomeEmailStorageError() from None

    def _review_interrupted(self, transaction, ref, now, minimum_age):
        record = self._read(transaction, ref)
        if record is None or record.status != 'in_progress' or now - record.reserved_at < minimum_age:
            return False
        return self._finish(transaction, ref, record.attempt_id,
            WelcomeProviderResult(reason='interrupted'), now)
