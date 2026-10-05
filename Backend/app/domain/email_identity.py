"""Pure identities for already-normalized email; no environment or persistence.

Version arguments are explicit identity namespaces, not implementations of future
normalization policies. Callers must normalize with the corresponding policy.
Future email_identities documents must store all three returned versions.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json

from app.domain.email import normalize_email
from app.domain.policies import EMAIL_NORMALIZATION_VERSION

EMAIL_IDENTITY_PURPOSE = "portal-email-identity"
EMAIL_IDENTITY_VERSION = 1
EMAIL_HMAC_KEY_VERSION = 1


@dataclass(frozen=True)
class EmailIdentity:
    identity_id: str
    normalization_version: int
    identity_version: int
    hmac_key_version: int


def derive_email_identity(
    normalized_email: str,
    *,
    secret: str,
    normalization_version: int = EMAIL_NORMALIZATION_VERSION,
    identity_version: int = EMAIL_IDENTITY_VERSION,
    hmac_key_version: int = EMAIL_HMAC_KEY_VERSION,
) -> EmailIdentity:
    """Derive an opaque hex ID; reject raw/noncanonical email and invalid inputs.

The secret is a nonblank UTF-8 string, used exactly as supplied (not stripped).
Strength/entropy is an operational responsibility; no arbitrary length policy.
Version labels must be positive integers, including for future migrations.
"""
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Invalid email identity secret.")
    versions = (normalization_version, identity_version, hmac_key_version)
    if any(type(version) is not int or version <= 0 for version in versions):
        raise ValueError("Invalid email identity version.")
    try:
        # Current canonical address policy; this does not implement policy v2.
        canonical_email = normalize_email(normalized_email)
    except ValueError:
        raise ValueError("Invalid normalized email.") from None
    if canonical_email != normalized_email:
        raise ValueError("Email must already be normalized.")
    message = json.dumps(
        {
            "purpose": EMAIL_IDENTITY_PURPOSE,
            "identity_version": identity_version,
            "normalization_version": normalization_version,
            "hmac_key_version": hmac_key_version,
            "normalized_email": normalized_email,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )
    try:
        key_bytes = secret.encode("utf-8")
        message_bytes = message.encode("utf-8")
    except UnicodeError:
        raise ValueError("Invalid email identity encoding.") from None
    identity_id = hmac.new(key_bytes, message_bytes, hashlib.sha256).hexdigest()
    return EmailIdentity(identity_id, normalization_version, identity_version, hmac_key_version)
