"""Internal password authentication; no HTTP, clients, logs or authorization.

Instantiate once per worker. Future HTTP callers must rate-limit BEFORE calling
this synchronous service and offload its database/Argon2 work from the event loop.
"""
from functools import lru_cache

from app.domain.admin import is_admin_enabled
from app.domain.email import normalize_email
from app.services.admin_password_service import (
    AdminPasswordPolicyError, hash_admin_password, verify_admin_password,
)

_DUMMY_PROBE = "administrative dummy verification probe"


class InvalidAdminCredentials(ValueError):
    def __init__(self):
        super().__init__("Invalid administrative credentials.")


class AdminAuthenticationUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Administrative authentication unavailable.")


@lru_cache(maxsize=1)
def _dummy_hash():
    # Non-authenticating fixture, generated with the same current Argon2 policy.
    # Warmed during service construction, not only for a nonexistent account.
    return hash_admin_password(_DUMMY_PROBE)


class AdminAuthService:
    def __init__(self, repository, session_service):
        self.repository = repository
        self.session_service = session_service
        try:
            self._dummy = _dummy_hash()
        except Exception:
            raise AdminAuthenticationUnavailable() from None

    def _verify(self, password, encoded):
        try:
            return verify_admin_password(password, encoded)
        except AdminPasswordPolicyError:
            # Invalid input must still pay one bounded Argon2 verification cost.
            verify_admin_password(_DUMMY_PROBE, self._dummy)
            return False

    def authenticate(self, email, password):
        """Return IssuedAdminSession only after valid enabled-admin credentials.

        Invalid email/missing account/wrong password/disabled account share one
        failure. Storage/corruption/session errors remain a distinct safe error.
        No automatic retry or password rehash writes are performed here.
        """
        try:
            try:
                normalized = normalize_email(email)
            except ValueError:
                self._verify(password, self._dummy)
                raise InvalidAdminCredentials() from None
            try:
                record = self.repository.find_by_email(normalized)
            except Exception:
                # Includes corrupt hashes rejected by AdminRecord at load time.
                self._verify(_DUMMY_PROBE, self._dummy)
                raise AdminAuthenticationUnavailable() from None
            encoded = record.password_hash.get_secret_value() if record is not None else self._dummy
            correct = self._verify(password, encoded)
            if record is None or not correct or not is_admin_enabled(record.to_admin()):
                raise InvalidAdminCredentials()
            # Existing service atomically rechecks enabled status and auth_version.
            return self.session_service.create(record.to_admin())
        except (InvalidAdminCredentials, AdminAuthenticationUnavailable):
            raise
        except Exception:
            raise AdminAuthenticationUnavailable() from None
