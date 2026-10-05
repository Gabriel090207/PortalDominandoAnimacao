"""Pure access rule; callers must supply trusted backend-persisted facts."""
from collections.abc import Iterable
from datetime import datetime

from app.domain.models import Entitlement, UserAccessState
from app.domain.states import AccountStatus, ActivationStatus, ResourceKey


def can_access_portal(
    user_id: str, user: UserAccessState, entitlements: Iterable[Entitlement], *, now: datetime
) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Instante deve incluir fuso horário.")
    return (
        user.account_status == AccountStatus.ENABLED
        and user.activation_status == ActivationStatus.ACTIVE
        and any(
            right.user_id == user_id
            and right.resource_key == ResourceKey.PORTAL
            and right.is_valid_at(now)
            for right in entitlements
        )
    )
