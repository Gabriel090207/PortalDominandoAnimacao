"""Injected-client session storage. Never initializes Firebase or logs documents."""
import re
import random
import time

from google.api_core.exceptions import Aborted
from google.cloud import firestore

from app.domain.admin import is_admin_session_valid
from app.persistence.admin_records import AdminRecord, AdminSessionRecord
from app.persistence.collections import CollectionName as C

_MAX_REVOCATION_EXECUTIONS = 3


def _is_revocation_contention(error):
    return isinstance(error, Aborted) or (
        type(error) is ValueError and isinstance(error.__cause__, Aborted)
    )


def _wait_before_revocation_retry(retry_number):
    base = min(0.05 * 2 ** retry_number, 0.1)
    time.sleep(min(base + random.uniform(0.0, base), 0.2))


class AdminSessionStorageError(RuntimeError):
    pass


class SessionCollisionError(AdminSessionStorageError):
    pass


class SessionCreationRejected(AdminSessionStorageError):
    pass


class AdminSessionsRepository:
    def __init__(self, client):
        self.client = client

    def _ref(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AdminSessionStorageError("Invalid session storage identifier.")
        return self.client.collection(C.ADMIN_SESSIONS.value).document(digest)

    def create(self, digest, session):
        try:
            document = AdminSessionRecord(**session.model_dump()).to_document()
            firestore.transactional(self._create)(self.client.transaction(), self._ref(digest), document)
        except (SessionCollisionError, SessionCreationRejected):
            raise
        except Exception:
            raise AdminSessionStorageError("Session creation failed.") from None

    def _admin(self, transaction, admin_id):
        snapshot = self.client.collection(C.ADMINS.value).document(admin_id).get(transaction=transaction)
        if not snapshot.exists:
            return None
        admin = AdminRecord.from_document(snapshot.to_dict()).to_admin()
        if admin.admin_id != admin_id:
            raise AdminSessionStorageError("Invalid administrator binding.")
        return admin

    def _create(self, transaction, ref, document):
        session = AdminSessionRecord.from_document(document).to_session()
        admin = self._admin(transaction, session.admin_id)
        existing = ref.get(transaction=transaction)
        if admin is None or not is_admin_session_valid(admin, session, now=session.created_at):
            raise SessionCreationRejected("Administrator is not eligible for session creation.")
        if existing.exists:
            raise SessionCollisionError("Session identifier collision.")
        transaction.create(ref, document)

    def lookup(self, digest):
        """Read session and current admin in a consistent transaction snapshot."""
        try:
            return firestore.transactional(self._lookup)(self.client.transaction(), self._ref(digest))
        except Exception:
            raise AdminSessionStorageError("Session lookup failed.") from None

    def _lookup(self, transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        session = AdminSessionRecord.from_document(snapshot.to_dict()).to_session()
        return session, self._admin(transaction, session.admin_id)

    def revoke(self, digest, *, now, reason):
        try:
            ref = self._ref(digest)
            for attempt in range(_MAX_REVOCATION_EXECUTIONS):
                try:
                    # Fresh runner and transaction; inputs stay fixed across retries.
                    return firestore.transactional(self._revoke)(self.client.transaction(), ref, now, reason)
                except Exception as error:
                    if not _is_revocation_contention(error) or attempt == _MAX_REVOCATION_EXECUTIONS - 1:
                        raise
                    _wait_before_revocation_retry(attempt)
        except Exception:
            raise AdminSessionStorageError("Session revocation failed.") from None

    def _revoke(self, transaction, ref, now, reason):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        session = AdminSessionRecord.from_document(snapshot.to_dict())
        if session.revoked_at is not None:
            return False
        document = AdminSessionRecord.from_document({
            **session.to_document(), "revoked_at": now, "revocation_reason": reason,
        }).to_document()
        transaction.update(ref, {"revoked_at": document["revoked_at"],
                                 "revocation_reason": document["revocation_reason"]})
        return True
