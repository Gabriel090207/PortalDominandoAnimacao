"""Validated storage contracts only; no database clients or CRUD.

Default serialization excludes the password hash. Only to_document explicitly
includes it for a future repository. Never expose document payloads or Pydantic
errors() in logs/HTTP; use the sanitized loaders at the storage boundary.
"""
from pydantic import Field, SecretStr, field_validator

from app.domain.admin import Admin, AdminSession
from app.services.admin_password_service import needs_admin_password_rehash


class InvalidAdminRecordError(ValueError):
    """Invalid storage data; never contains source inputs."""


class AdminRecord(Admin):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    password_hash: SecretStr = Field(repr=False, exclude=True)

    @field_validator("password_hash", mode="before")
    @classmethod
    def validate_hash(cls, value):
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        needs_admin_password_rehash(value)  # Format/cost checks only, no hashing.
        return SecretStr(value)

    def to_admin(self) -> Admin:
        return Admin.model_validate(self.model_dump(exclude={"schema_version"}))

    def to_document(self) -> dict:
        validated = AdminRecord.model_validate({
            **self.model_dump(), "password_hash": self.password_hash,
        })
        return {
            **validated.to_admin().model_dump(),
            "schema_version": 1,
            "password_hash": validated.password_hash.get_secret_value(),
        }

    @classmethod
    def from_document(cls, document) -> "AdminRecord":
        try:
            if not isinstance(document, dict) or type(document.get("schema_version")) is not int:
                raise ValueError
            return cls.model_validate(document)
        except (ValueError, TypeError):
            raise InvalidAdminRecordError("Invalid stored administrative record.") from None


class AdminSessionRecord(AdminSession):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)

    def to_session(self) -> AdminSession:
        return AdminSession.model_validate(self.model_dump(exclude={"schema_version"}))

    def to_document(self) -> dict:
        validated = AdminSessionRecord.from_document(self.model_dump(warnings=False))
        return {**validated.to_session().model_dump(), "schema_version": 1}

    @classmethod
    def from_document(cls, document) -> "AdminSessionRecord":
        try:
            if not isinstance(document, dict) or type(document.get("schema_version")) is not int:
                raise ValueError
            return cls.model_validate(document)
        except (ValueError, TypeError):
            raise InvalidAdminRecordError("Invalid stored administrative session.") from None
