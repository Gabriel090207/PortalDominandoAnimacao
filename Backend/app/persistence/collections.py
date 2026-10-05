"""Collection names only; declaring them does not create Firestore data."""
from enum import StrEnum


class CollectionName(StrEnum):
    USERS = "users"
    EMAIL_IDENTITIES = "email_identities"
    PURCHASES = "purchases"
    SUBSCRIPTIONS = "subscriptions"
    ENTITLEMENTS = "entitlements"
    ACTIVATION_AUDIT = "activation_audit"
    LOGIN_CHALLENGES = "login_challenges"
    AUTH_THROTTLES = "auth_throttles"
    USER_SESSIONS = "user_sessions"
    ADMINS = "admins"
    ADMIN_SESSIONS = "admin_sessions"
    KIRVANO_EVENTS = "kirvano_events"
    TRANSACTIONAL_EMAILS = "transactional_emails"
