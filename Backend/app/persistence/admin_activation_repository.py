"""One atomic pending->active transition plus audit; SDK contention retries only."""
from datetime import datetime,timezone
from uuid import uuid4
from google.cloud import firestore
from app.domain.admin import Admin,AdminPermission,is_admin_enabled,role_has_permission
from app.domain.admin_activation import (CustomerActivationAudit,CustomerActivationResult,
    CustomerActivationConflict,CustomerActivationUnavailable)
from app.domain.admin_customers import customer_identifier
from app.domain.states import AccountStatus,ActivationStatus
from app.persistence.collections import CollectionName as C
from app.persistence.admin_customers_repository import _project_customer
from app.persistence.admin_access_eligibility import has_eligible_portal_access


# Local native SDK budget: at most eight commit attempts, no outer retry layer.
_ACTIVATION_MAX_ATTEMPTS = 8

def _now():return datetime.now(timezone.utc)


class AdminActivationRepository:
    def __init__(self,client,*,clock=_now):
        self.client=client
        self.clock=clock

    def activate(self,customer_id,administrator):
        identifier=customer_identifier(customer_id)
        try:
            if (not isinstance(administrator,Admin) or not is_admin_enabled(administrator) or
                not role_has_permission(administrator.role,AdminPermission.ACTIVATE_CUSTOMER)):
                raise ValueError
            # Stable audit reference across SDK attempts, create-only, no outer retry.
            audit=self.client.collection(C.ACTIVATION_AUDIT.value).document(uuid4().hex)
            return firestore.transactional(self._activate)(self.client.transaction(max_attempts=_ACTIVATION_MAX_ATTEMPTS),identifier,administrator,audit)
        except CustomerActivationConflict:
            raise
        except Exception:
            # Includes timeout/uncertain commit: never report success or retry externally.
            raise CustomerActivationUnavailable() from None

    def _activate(self,transaction,identifier,administrator,audit):
        now=self.clock()
        if now.utcoffset() is None:raise ValueError
        user_ref=self.client.collection(C.USERS.value).document(identifier)
        snapshot=user_ref.get(transaction=transaction,timeout=10)
        if not snapshot.exists:return None
        customer=_project_customer(snapshot)
        if customer.account_status!=AccountStatus.ENABLED or customer.activation_status==ActivationStatus.SUSPENDED:
            raise CustomerActivationConflict()
        # Recheck actor state/version in the same transaction without modifying it.
        actor=self.client.collection(C.ADMINS.value).document(administrator.admin_id).get(transaction=transaction,timeout=10)
        current=actor.to_dict() if actor.exists else {}
        if (current.get('status')!='enabled' or current.get('role')!=administrator.role or
            type(current.get('auth_version')) is not int or current.get('auth_version')!=administrator.auth_version):
            raise CustomerActivationConflict()
        if customer.activation_status==ActivationStatus.ACTIVE:
            return CustomerActivationResult(customer_id=identifier,result='already_active')
        if customer.activation_status!=ActivationStatus.PENDING:raise CustomerActivationConflict()
        if not has_eligible_portal_access(transaction,self.client,identifier,customer.account_status,now):
            raise CustomerActivationConflict()
        record=CustomerActivationAudit(admin_id=administrator.admin_id,customer_id=identifier,occurred_at=now)
        transaction.update(user_ref,{'activation_status':ActivationStatus.ACTIVE.value})
        transaction.create(audit,record.model_dump())
        return CustomerActivationResult(customer_id=identifier,result='activated')
