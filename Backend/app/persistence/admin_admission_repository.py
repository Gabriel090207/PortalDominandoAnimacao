"""Atomic admission; one extra cycle ONLY for proven pre-write read Aborted."""
import re

from google.cloud import firestore
from google.api_core.exceptions import Aborted

from app.domain.admin_admission import validate_admission_policy, evaluate_buckets, utc_instant
from app.persistence.collections import CollectionName


class AdminAdmissionUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Administrative admission unavailable.")


class _ReadAbortedBeforeProgress(RuntimeError):
    """Internal signal: no callback in this SDK cycle completed its reads."""


class AdminAdmissionRepository:
    def __init__(self, client):
        self.client = client

    def admit(self, identifiers, policy, now, *, allow_read_retry=True):
        try:
            policy = validate_admission_policy(policy)
            now = utc_instant(now)
            if type(allow_read_retry) is not bool:
                raise ValueError
            if (len(identifiers) != len(policy.bucket_rules)
                or len(set(identifiers)) != len(identifiers)
                or any(not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) for key in identifiers)):
                raise ValueError
            collection = self.client.collection(CollectionName.AUTH_THROTTLES.value)
            refs = tuple(collection.document(key) for key in identifiers)
            for cycle in range(2 if allow_read_retry else 1):
                # Sticky across the SDK's own commit retries. Once ANY callback
                # has finished reads, a commit may subsequently have been tried.
                progress = {'reads_completed': False}
                try:
                    return firestore.transactional(self._admit)(
                        self.client.transaction(), refs, policy, now, progress)
                except _ReadAbortedBeforeProgress:
                    if cycle or not allow_read_retry:
                        raise
        except Exception:
            raise AdminAdmissionUnavailable() from None

    def _admit(self, transaction, refs, policy, now, progress):
        try:
            snapshots = [ref.get(transaction=transaction) for ref in refs]
        except Aborted:
            if not progress['reads_completed']:
                # SDK must finish rollback before this signal reaches admit().
                # Any different rollback error fails closed, without retry.
                raise _ReadAbortedBeforeProgress() from None
            raise
        progress['reads_completed'] = True  # Before evaluation or buffering writes.
        decision, updates = evaluate_buckets(
            [snapshot.to_dict() if snapshot.exists else None for snapshot in snapshots], policy, now)
        if updates is not None:
            for ref, snapshot, document in zip(refs, snapshots, updates):
                if snapshot.exists:
                    transaction.update(ref, document)
                else:
                    transaction.create(ref, document)
        return decision
