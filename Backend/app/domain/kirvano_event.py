"""Receipt identities are candidates, never commercial authorization."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.states import KirvanoEventState


class ValidationIssue(StrEnum):
    INVALID_STRUCTURE = "invalid_structure"
    MISSING_IDENTITY = "missing_identity"
    UNKNOWN_EVENT = "unknown_event"
    INVALID_FIELD = "invalid_field"
    CONTENT_CONFLICT = "content_conflict"


@dataclass(frozen=True)
class NormalizedEvent:
    logical_id: str
    fingerprint: str
    normalized_payload: dict[str, Any]
    validation_issues: tuple[str, ...]
    identity_basis: str
    identity_confidence: str
    processing_status: KirvanoEventState


@dataclass(frozen=True)
class ReceiptResult:
    logical_id: str
    processing_status: KirvanoEventState
    outcome: str
