"""Approved authentication policies; no authentication implementation."""
from datetime import timedelta

LOGIN_CODE_LENGTH = 6
LOGIN_CHALLENGE_LIFETIME = timedelta(minutes=10)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_RESEND_COOLDOWN = timedelta(seconds=60)
USER_SESSION_LIFETIME = timedelta(hours=8)
ADMIN_SESSION_LIFETIME = timedelta(hours=8)
MAX_ACTIVE_USER_SESSIONS = 1
EMAIL_NORMALIZATION_VERSION = 1
