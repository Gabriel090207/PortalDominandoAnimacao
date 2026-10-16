"""Internal admission/authentication coordinator; no HTTP or origin resolution.

Construct once per worker with configured admission/authentication services.
The caller must supply a canonical origin from a verified trust boundary.
Construction may warm the authentication service's dummy hash; attempts never
perform password verification until admission has successfully committed.
"""
from app.domain.admin_admission import AdmissionDecision, AdmissionOutcome
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from app.services.admin_auth_service import (
    AdminAuthenticationUnavailable, InvalidAdminCredentials,
)


class AdminLoginLimited(RuntimeError):
    def __init__(self, retry_after_seconds):
        super().__init__("Administrative authentication temporarily limited.")
        self.retry_after_seconds = retry_after_seconds


class AdminLoginService:
    def __init__(self, admission_service, auth_service):
        self.admission_service = admission_service
        self.auth_service = auth_service

    def authenticate(self, trusted_origin, email, password):
        try:
            decision = self.admission_service.admit_attempt(trusted_origin, email)
            # Fail closed even for a malformed dependency result.
            if not isinstance(decision, AdmissionDecision):
                raise AdminAdmissionUnavailable()
            if decision.outcome == AdmissionOutcome.LIMITED:
                raise AdminLoginLimited(decision.retry_after_seconds)
            if decision.outcome != AdmissionOutcome.ALLOWED:
                raise AdminAdmissionUnavailable()
        except AdminLoginLimited:
            raise
        except Exception:
            raise AdminAdmissionUnavailable() from None

        # The admission transaction has finished. No refunds, resets or retries,
        # even if credential verification/session creation subsequently fails.
        try:
            return self.auth_service.authenticate(email, password)
        except (InvalidAdminCredentials, AdminAuthenticationUnavailable):
            raise
        except Exception:
            raise AdminAuthenticationUnavailable() from None
