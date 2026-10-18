"""Explicit per-application/worker composition; no public app registration."""
from app.persistence.admin_resumption_repository import AdminResumptionRepository
from app.services.admin_resumption_service import AdminResumptionService
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from app.services.admin_suspension_service import AdminSuspensionService
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter

from app.api.admin_auth import create_admin_auth_router
from app.api.admin_customers import create_admin_customers_router
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.services.admin_activation_service import AdminActivationService
from app.persistence.admin_customers_repository import AdminCustomersRepository
from app.services.admin_customers_service import AdminCustomersService
from app.config.admin_admission import AdminAdmissionConfig
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_admission import AdminAdmissionPolicy
from app.domain.policies import INITIAL_ADMIN_ADMISSION_POLICY
from app.persistence.admin_repository import AdminRepository
from app.persistence.admin_sessions_repository import AdminSessionsRepository
from app.persistence.admin_admission_repository import AdminAdmissionRepository
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_session_service import AdminSessionService
from app.services.admin_admission_service import AdminAdmissionService
from app.services.admin_login_service import AdminLoginService


class AdminCompositionError(RuntimeError):
    def __init__(self):
        super().__init__('Administrative HTTP composition unavailable.')


@dataclass(frozen=True)
class AdminHTTPComposition:
    router: APIRouter = field(repr=False)
    session_service: AdminSessionService = field(repr=False)
    admission_service: AdminAdmissionService = field(repr=False)
    login_service: AdminLoginService = field(repr=False)


def _utc_now():
    return datetime.now(timezone.utc)


def compose_admin_http(*, firestore_client, admission_config, security_config,
                       trusted_origin_dependency=None, clock=_utc_now,
                       policy=INITIAL_ADMIN_ADMISSION_POLICY):
    """Call once per app/worker, outside request handling and event-loop work.

    Client ownership stays with the caller. No connection creation, credentials,
    env writes/reads, DB operations or sessions here. The caller may explicitly
    supply the shared client from firebase_service.get_firestore_client().
    Absence of trusted origin deliberately leaves login unavailable, not inferred.
    """
    try:
        if (firestore_client is None or not callable(getattr(firestore_client, 'collection', None)) or
            not callable(getattr(firestore_client, 'transaction', None)) or
            not isinstance(admission_config, AdminAdmissionConfig) or
            not isinstance(security_config, AdminRequestSecurityConfig) or
            not callable(clock) or
            (trusted_origin_dependency is not None and not callable(trusted_origin_dependency))):
            raise ValueError
        admission_config = AdminAdmissionConfig(admission_config.secret, admission_config.key_version)
        security_config = AdminRequestSecurityConfig(security_config.allowed_origins)
        policy = AdminAdmissionPolicy.model_validate(policy.model_dump())
        session_service = AdminSessionService(AdminSessionsRepository(firestore_client))
        admission_service = AdminAdmissionService(AdminAdmissionRepository(firestore_client),
            policy=policy, admission_hmac_secret=admission_config.secret.get_secret_value(),
            key_version=admission_config.key_version, clock=clock)
        authentication = AdminAuthService(AdminRepository(firestore_client), session_service)
        login_service = AdminLoginService(admission_service, authentication)
        router = APIRouter()
        router.include_router(create_admin_auth_router(session_service=session_service, security_config=security_config,
            login_service=login_service, trusted_origin_dependency=trusted_origin_dependency))
        customers_service = AdminCustomersService(AdminCustomersRepository(firestore_client))
        router.include_router(create_admin_customers_router(session_service=session_service,
            customers_service=customers_service, security_config=security_config,
            activation_service=AdminActivationService(AdminActivationRepository(firestore_client,clock=clock)),
            suspension_service=AdminSuspensionService(AdminSuspensionRepository(firestore_client,clock=clock)),
            resumption_service=AdminResumptionService(AdminResumptionRepository(firestore_client,clock=clock))))
        return AdminHTTPComposition(router, session_service, admission_service, login_service)
    except Exception:
        raise AdminCompositionError() from None
