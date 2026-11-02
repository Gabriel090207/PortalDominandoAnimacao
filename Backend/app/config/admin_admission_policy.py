"""Explicit policy configuration only; no environment, secrets, I/O or startup."""
from pydantic import BaseModel, ConfigDict, Field

from app.config.admin_admission import AdminAdmissionConfigurationError
from app.domain.admin_admission import ComplementaryAdminAdmissionPolicy, validate_admission_policy


class _PolicyConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', hide_input_in_errors=True)
    schema_version: int = Field(strict=True, ge=1, le=1)
    policy: ComplementaryAdminAdmissionPolicy


def load_admin_admission_policy(*, selection, configuration=None):
    """Select local reference or supply a complete versioned configuration.

    No default selection, environment fallback or production activation.
    Configuration schema version is NOT HMAC key version or bucket schema.
    Existing persisted policy incompatibility still requires explicit transition.
    """
    try:
        if selection == 'complementary-local-v1':
            if configuration is not None:
                raise ValueError
            configuration = {'schema_version': 1, 'policy': {
                'origin': {'capacity': 10, 'refill_tokens': 1, 'refill_period_seconds': 30},
                'origin_identity': {'capacity': 5, 'refill_tokens': 1, 'refill_period_seconds': 60},
                'identity': {'capacity': 5, 'refill_tokens': 1, 'refill_period_seconds': 60},
                'aggregate': {'capacity': 20, 'refill_tokens': 1, 'refill_period_seconds': 30},
            }}
        elif selection != 'configured-v1':
            raise ValueError
        return validate_admission_policy(_PolicyConfiguration.model_validate(configuration).policy)
    except Exception:
        raise AdminAdmissionConfigurationError() from None
