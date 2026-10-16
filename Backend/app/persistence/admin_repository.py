"""First-owner persistence and bounded lookup; no general admin registration."""
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.domain.admin import AdminRole, AdminStatus
from app.domain.email import normalize_email
from app.persistence.admin_records import AdminRecord
from app.persistence.collections import CollectionName

BOOTSTRAP_ACTOR = "bootstrap"  # Existing domain test convention; not an admin ID.
BOOTSTRAP_DOCUMENT = "first_owner_v1"


class AdminBootstrapError(RuntimeError):
    """Sanitized failure: callers must never expose underlying storage errors."""


class AdminLookupError(RuntimeError):
    """Storage unavailable, duplicate identity or invalid administrative record."""


class AdminRepository:
    def __init__(self, client):
        self.client = client

    def find_by_email(self, email_normalized):
        """Indexed equality query, at most two documents; duplicates fail closed.

        Works with existing UUID documents, without a production migration.
        Future writers must enforce normalized-email uniqueness transactionally.
        """
        try:
            if normalize_email(email_normalized) != email_normalized:
                raise ValueError
            snapshots = list(self.client.collection(CollectionName.ADMINS.value).where(
                filter=FieldFilter("email_normalized", "==", email_normalized)
            ).limit(2).stream(timeout=10))
            if len(snapshots) > 1:
                raise AdminLookupError("Administrator lookup failed.")
            if not snapshots:
                return None
            snapshot = snapshots[0]
            record = AdminRecord.from_document(snapshot.to_dict())
            if record.admin_id != snapshot.id or record.email_normalized != email_normalized:
                raise ValueError
            return record
        except Exception:
            raise AdminLookupError("Administrator lookup failed.") from None


def create_first_owner(client, record: AdminRecord):
    """Atomically consume bootstrap and create a validated owner, once only.

    The singleton is deliberately separate from admins. It must never be reset
    after deletion/disablement of the owner. All future admin writers must have
    their own uniqueness policy; this is not a general create API.
    """
    try:
        document = record.to_document()
        validated = AdminRecord.from_document(document)
        if (validated.role != AdminRole.OWNER or validated.status != AdminStatus.ENABLED
            or validated.created_by != BOOTSTRAP_ACTOR
            or validated.admin_id == BOOTSTRAP_ACTOR or validated.auth_version != 1):
            raise AdminBootstrapError("Invalid first-owner contract.")
        firestore.transactional(_create_first_owner)(client.transaction(), client, document)
        return validated.to_admin()
    except AdminBootstrapError:
        raise
    except Exception:
        raise AdminBootstrapError("Administrator persistence failed; bootstrap was not confirmed.") from None


def _create_first_owner(transaction, client, document):
    admins = client.collection(CollectionName.ADMINS.value)
    control = client.collection(CollectionName.ADMIN_BOOTSTRAP.value).document(BOOTSTRAP_DOCUMENT)
    admin = admins.document(document["admin_id"])
    # Shared document read + create serializes competing bootstraps even when
    # both queries see an empty admins collection. SDK retries recheck the gate.
    if control.get(transaction=transaction).exists:
        raise AdminBootstrapError("Administrator bootstrap is already consumed.")
    if list(admins.limit(1).stream(transaction=transaction)):
        raise AdminBootstrapError("Administrator bootstrap requires an empty admin collection.")
    if admin.get(transaction=transaction).exists:
        raise AdminBootstrapError("Administrator already exists.")
    transaction.create(admin, document)
    transaction.create(control, {
        "schema_version": 1,
        "operation": "first_owner_provisioned",
        "admin_id": document["admin_id"],
        "created_by": BOOTSTRAP_ACTOR,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
