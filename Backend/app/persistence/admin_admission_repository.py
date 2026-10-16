"""Two direct document reads, one transaction, no outer/uncertain-commit retry."""
import re

from google.cloud import firestore

from app.domain.admin_admission import AdminAdmissionPolicy, evaluate_buckets, utc_instant
from app.persistence.collections import CollectionName


class AdminAdmissionUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Administrative admission unavailable.")


class AdminAdmissionRepository:
    def __init__(self, client):
        self.client = client

    def admit(self, identifiers, policy, now):
        try:
            policy = AdminAdmissionPolicy.model_validate(policy.model_dump())
            now = utc_instant(now)
            if (len(identifiers) != 2 or identifiers[0] == identifiers[1]
                or any(not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) for key in identifiers)):
                raise ValueError
            collection = self.client.collection(CollectionName.AUTH_THROTTLES.value)
            refs = tuple(collection.document(key) for key in identifiers)
            return firestore.transactional(self._admit)(self.client.transaction(), refs, policy, now)
        except Exception:
            raise AdminAdmissionUnavailable() from None

    def _admit(self, transaction, refs, policy, now):
        snapshots = [ref.get(transaction=transaction) for ref in refs]
        decision, updates = evaluate_buckets(
            [snapshot.to_dict() if snapshot.exists else None for snapshot in snapshots], policy, now)
        if updates is not None:
            for ref, snapshot, document in zip(refs, snapshots, updates):
                if snapshot.exists:
                    transaction.update(ref, document)
                else:
                    transaction.create(ref, document)
        return decision
