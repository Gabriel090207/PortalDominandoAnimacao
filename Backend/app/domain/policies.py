"""Approved authentication policies; no authentication implementation."""
from datetime import timedelta

from app.domain.admin_admission import AdminAdmissionPolicy, BucketPolicy

LOGIN_CODE_LENGTH = 6
LOGIN_CHALLENGE_LIFETIME = timedelta(minutes=10)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_RESEND_COOLDOWN = timedelta(seconds=60)
USER_SESSION_LIFETIME = timedelta(hours=8)
ADMIN_SESSION_LIFETIME = timedelta(hours=8)
MAX_ACTIVE_USER_SESSIONS = 1
EMAIL_NORMALIZATION_VERSION = 1

# Explicit opt-in by the composition layer; importing this does not enable login.
# Changing a persisted policy requires an approved transition, not just new values.
INITIAL_ADMIN_ADMISSION_POLICY = AdminAdmissionPolicy(
    origin=BucketPolicy(capacity=10, refill_tokens=1, refill_period_seconds=30),
    origin_identity=BucketPolicy(capacity=5, refill_tokens=1, refill_period_seconds=60),
)
