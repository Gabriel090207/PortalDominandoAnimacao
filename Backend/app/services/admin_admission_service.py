"""Internal admission only; no HTTP origin extraction or authentication calls."""
import hashlib
import hmac
import json

from app.domain.admin_admission import validate_admission_policy, utc_instant
from app.domain.email import normalize_email
from app.persistence.admin_admission_repository import AdminAdmissionUnavailable


def _derive_bucket_identifiers(origin, email_normalized, *, admission_hmac_secret, key_version,
                               invalid_identity=False, complementary=False):
    """Opaque IDs, dedicated caller-supplied secret; never reads commercial secrets."""
    if (not isinstance(admission_hmac_secret, str) or not admission_hmac_secret.strip()
        or not 32 <= len(admission_hmac_secret.encode("utf-8")) <= 1024
        or type(key_version) is not int or key_version <= 0
        or not isinstance(origin, str) or not origin or len(origin) > 256
        or origin != origin.strip() or any(ord(char) < 32 or ord(char) == 127 for char in origin)
        or (not invalid_identity and normalize_email(email_normalized) != email_normalized)):
        raise ValueError("Invalid admission identity configuration.")
    def identify(scope, values):
        message = json.dumps(["portal-admin-admission", 1, key_version, scope, values],
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hmac.new(admission_hmac_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    pair = (identify("origin_invalid_identity", [origin]) if invalid_identity else
            identify("origin_identity", [origin, email_normalized]))
    original = (identify("origin", [origin]), pair)
    if not complementary:
        return original
    identity = (identify("identity_invalid", []) if invalid_identity else
                identify("identity", [email_normalized]))
    return original + (identity, identify("aggregate", []))


def derive_bucket_identifiers(origin, email_normalized, *, admission_hmac_secret, key_version=1):
    try:
        return _derive_bucket_identifiers(origin, email_normalized,
            admission_hmac_secret=admission_hmac_secret, key_version=key_version)
    except Exception:
        raise ValueError("Invalid admission identity configuration.") from None


class AdminAdmissionService:
    def __init__(self, repository, *, policy, admission_hmac_secret, clock, key_version=1):
        try:
            # No defaults, environment loading or permissive fallback.
            self.policy = validate_admission_policy(policy)
            derive_bucket_identifiers("configuration-validation", "validation@example.com",
                admission_hmac_secret=admission_hmac_secret, key_version=key_version)
            if not callable(clock):
                raise ValueError
            self.repository, self.clock = repository, clock
            self._secret, self._key_version = admission_hmac_secret, key_version
        except Exception:
            raise AdminAdmissionUnavailable() from None

    def admit(self, trusted_origin, email):
        """Origin must already be canonical and trusted; clock must be server-owned."""
        try:
            normalized = normalize_email(email)
            identifiers = _derive_bucket_identifiers(trusted_origin, normalized,
                admission_hmac_secret=self._secret, key_version=self._key_version,
                complementary=len(self.policy.bucket_rules) == 4)
            now = utc_instant(self.clock())  # Fixed for SDK retries of this admission.
            return self.repository.admit(identifiers, self.policy, now)
        except Exception:
            raise AdminAdmissionUnavailable() from None

    def admit_attempt(self, trusted_origin, email):
        """Admit even malformed identities, sharing one opaque bucket per origin.

        This does not validate credentials. Invalid identities cannot create an
        unbounded set of buckets or bypass the same general origin budget.
        The strict admit() contract and existing valid-identity IDs are unchanged.
        """
        try:
            try:
                normalized = normalize_email(email)
            except ValueError:
                normalized = None
            identifiers = _derive_bucket_identifiers(trusted_origin, normalized,
                admission_hmac_secret=self._secret, key_version=self._key_version,
                invalid_identity=normalized is None, complementary=len(self.policy.bucket_rules) == 4)
            now = utc_instant(self.clock())
            if normalized is None:
                # Preserve invalid-identity admission accounting, but do not
                # spend an extra transaction cycle on malformed identities.
                return self.repository.admit(identifiers, self.policy, now, allow_read_retry=False)
            return self.repository.admit(identifiers, self.policy, now)
        except Exception:
            raise AdminAdmissionUnavailable() from None
