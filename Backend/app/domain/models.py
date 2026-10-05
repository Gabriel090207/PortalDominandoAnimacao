"""Minimal access facts, independent of persistence and provider payloads."""
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.domain.states import AccountStatus, ActivationStatus, EntitlementStatus, ResourceKey


class UserAccessState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    account_status: AccountStatus
    activation_status: ActivationStatus


class Entitlement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: str
    resource_key: ResourceKey
    status: EntitlementStatus
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if not self.user_id.strip():
            raise ValueError("Identificador de usuário obrigatório.")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("O fim do direito deve ser posterior ao início.")
        return self

    def is_valid_at(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Instante deve incluir fuso horário.")
        return (
            self.status == EntitlementStatus.GRANTED
            and self.valid_from <= now
            and (self.valid_until is None or now < self.valid_until)
        )
