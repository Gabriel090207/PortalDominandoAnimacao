"""Restrict access and audit atomically; no commercial reads or writes."""
from datetime import datetime, timezone
from uuid import uuid4
from google.cloud import firestore
from app.domain.admin import Admin, AdminPermission, is_admin_enabled, role_has_permission
from app.domain.admin_suspension import (CustomerSuspensionAudit, CustomerSuspensionResult,
    CustomerSuspensionConflict, CustomerSuspensionUnavailable)
from app.domain.admin_customers import customer_identifier
from app.domain.states import AccountStatus, ActivationStatus
from app.persistence.collections import CollectionName as C
from app.persistence.admin_customers_repository import _project_customer


# Explicit SDK default budget for two document reads; no external retry layer.
_SUSPENSION_MAX_ATTEMPTS = 5


class AdminSuspensionRepository:
    def __init__(self, client, *, clock=lambda: datetime.now(timezone.utc)):
        self.client = client
        self.clock = clock

    def suspend(self, customer_id, administrator):
        identifier = customer_identifier(customer_id)
        try:
            if (not isinstance(administrator, Admin) or not is_admin_enabled(administrator) or
                not role_has_permission(administrator.role, AdminPermission.SUSPEND_CUSTOMER)):
                raise ValueError
            audit = self.client.collection(C.ACTIVATION_AUDIT.value).document(uuid4().hex)
            return firestore.transactional(self._suspend)(
                self.client.transaction(max_attempts=_SUSPENSION_MAX_ATTEMPTS), identifier, administrator, audit)
        except CustomerSuspensionConflict:
            raise
        except Exception:
            raise CustomerSuspensionUnavailable() from None

    def _suspend(self, transaction, identifier, administrator, audit):
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError
        now = now.astimezone(timezone.utc)
        ref = self.client.collection(C.USERS.value).document(identifier)
        snapshot = ref.get(transaction=transaction, timeout=10)
        if not snapshot.exists:
            return None
        customer = _project_customer(snapshot)
        if (customer.account_status != AccountStatus.ENABLED or
            customer.activation_status not in (ActivationStatus.ACTIVE, ActivationStatus.SUSPENDED)):
            raise CustomerSuspensionConflict()
        actor = self.client.collection(C.ADMINS.value).document(administrator.admin_id).get(
            transaction=transaction, timeout=10)
        current = actor.to_dict() if actor.exists else {}
        if (current.get('status') != 'enabled' or current.get('role') != administrator.role or
            type(current.get('auth_version')) is not int or current.get('auth_version') != administrator.auth_version):
            raise CustomerSuspensionConflict()
        if customer.activation_status == ActivationStatus.SUSPENDED:
            return CustomerSuspensionResult(customer_id=identifier, result='already_suspended')
        record = CustomerSuspensionAudit(admin_id=administrator.admin_id, customer_id=identifier, occurred_at=now)
        transaction.update(ref, {'activation_status': ActivationStatus.SUSPENDED.value})
        transaction.create(audit, record.model_dump())
        return CustomerSuspensionResult(customer_id=identifier, result='suspended')
