"""Internal domain states; external provider values must be mapped separately."""
from enum import StrEnum


class ActivationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class AccountStatus(StrEnum):
    ENABLED = "enabled"
    BLOCKED = "blocked"


class CommercialStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    CHARGEBACK = "chargeback"


class EntitlementStatus(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class SubscriptionInterval(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class LoginChallengeState(StrEnum):
    PENDING_DELIVERY = "pending_delivery"
    ISSUED = "issued"
    CONSUMED = "consumed"
    INVALIDATED = "invalidated"
    LOCKED = "locked"
    EXPIRED = "expired"


class LoginPurpose(StrEnum):
    PORTAL_LOGIN = "portal_login"
    DEVICE_SWITCH = "device_switch"


class SessionRevocationReason(StrEnum):
    LOGOUT = "logout"
    DEVICE_SWITCH = "device_switch"
    ACCOUNT_BLOCKED = "account_blocked"
    ACTIVATION_SUSPENDED = "activation_suspended"
    COMMERCIAL_INELIGIBILITY = "commercial_ineligibility"
    ADMIN_DISABLED = "admin_disabled"
    CREDENTIAL_CHANGED = "credential_changed"


class ResourceKey(StrEnum):
    PORTAL = "portal"


class KirvanoEventState(StrEnum):
    RECEIVED = "received"
    REVIEW_REQUIRED = "review_required"
    CONFLICT = "conflict"
