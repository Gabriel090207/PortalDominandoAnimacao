"""Provenance, current eligibility and manual resumption in one transaction."""
from datetime import datetime,timezone
import re
from uuid import uuid4
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from app.domain.admin import Admin,AdminPermission,is_admin_enabled,role_has_permission
from app.domain.admin_activation import CustomerActivationAudit
from app.domain.admin_suspension import CustomerSuspensionAudit
from app.domain.admin_resumption import (CustomerResumptionAudit,CustomerResumptionResult,
    CustomerResumptionConflict,CustomerResumptionUnavailable)
from app.domain.admin_customers import customer_identifier
from app.domain.states import AccountStatus,ActivationStatus
from app.persistence.admin_customers_repository import _project_customer
from app.persistence.admin_access_eligibility import has_eligible_portal_access
from app.persistence.collections import CollectionName as C


# Same commercial read set as activation, plus bounded history reads. Local only.
_RESUMPTION_MAX_ATTEMPTS=8


def _utc_now():return datetime.now(timezone.utc)


class AdminResumptionRepository:
    def __init__(self,client,*,clock=_utc_now):
        self.client=client
        self.clock=clock

    def resume(self,customer_id,administrator):
        identifier=customer_identifier(customer_id)
        try:
            if (not isinstance(administrator,Admin) or not is_admin_enabled(administrator) or
                not role_has_permission(administrator.role,AdminPermission.RESUME_CUSTOMER)):
                raise ValueError
            audit=self.client.collection(C.ACTIVATION_AUDIT.value).document(uuid4().hex)
            return firestore.transactional(self._resume)(self.client.transaction(max_attempts=_RESUMPTION_MAX_ATTEMPTS),
                identifier,administrator,audit)
        except CustomerResumptionConflict:
            raise
        except Exception:
            raise CustomerResumptionUnavailable() from None

    def _history(self,transaction,identifier,model):
        operation=model.model_fields['operation'].default
        query=self.client.collection(C.ACTIVATION_AUDIT.value)
        for field,value in [('customer_id',identifier),('operation',operation)]:
            query=query.where(filter=FieldFilter(field,'==',value))
        rows=list(query.limit(1).stream(transaction=transaction,timeout=10))
        if not rows:raise CustomerResumptionConflict()
        if len(rows)!=1:raise ValueError
        data=rows[0].to_dict()
        # Defaults/coercion must not fabricate missing historical evidence.
        if (not isinstance(data,dict) or set(data)!=set(model.model_fields) or
            type(data.get('schema_version')) is not int or data['schema_version']!=1 or
            data.get('human_confirmation') is not True or data.get('customer_id')!=identifier or
            not isinstance(data.get('admin_id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',data['admin_id']) or
            not isinstance(data.get('occurred_at'),datetime)):
            raise CustomerResumptionConflict()
        try:return model.model_validate(data)
        except Exception:raise CustomerResumptionConflict() from None

    def _resume(self,transaction,identifier,administrator,audit):
        now=self.clock()
        if now.utcoffset() is None:raise ValueError
        now=now.astimezone(timezone.utc)
        ref=self.client.collection(C.USERS.value).document(identifier)
        snapshot=ref.get(transaction=transaction,timeout=10)
        if not snapshot.exists:return None
        customer=_project_customer(snapshot)
        if (customer.account_status!=AccountStatus.ENABLED or
            customer.activation_status not in (ActivationStatus.SUSPENDED,ActivationStatus.ACTIVE)):
            raise CustomerResumptionConflict()
        actor=self.client.collection(C.ADMINS.value).document(administrator.admin_id).get(transaction=transaction,timeout=10)
        current=actor.to_dict() if actor.exists else {}
        if (current.get('status')!='enabled' or current.get('role')!=administrator.role or
            type(current.get('auth_version')) is not int or current.get('auth_version')!=administrator.auth_version):
            raise CustomerResumptionConflict()
        if customer.activation_status==ActivationStatus.ACTIVE:
            return CustomerResumptionResult(customer_id=identifier,result='already_active')
        activation=self._history(transaction,identifier,CustomerActivationAudit)
        suspension=self._history(transaction,identifier,CustomerSuspensionAudit)
        if not customer.created_at<=activation.occurred_at<=suspension.occurred_at<=now:
            raise CustomerResumptionConflict()
        if not has_eligible_portal_access(transaction,self.client,identifier,customer.account_status,now):
            raise CustomerResumptionConflict()
        record=CustomerResumptionAudit(admin_id=administrator.admin_id,customer_id=identifier,occurred_at=now)
        transaction.update(ref,{'activation_status':ActivationStatus.ACTIVE.value})
        transaction.create(audit,record.model_dump())
        return CustomerResumptionResult(customer_id=identifier,result='resumed')
