"""Explicit token-bucket contracts and pure arithmetic; no credentials or I/O."""
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_MAX_INT = 2**63-1


class BucketPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    capacity: int = Field(strict=True, gt=0, le=_MAX_INT)
    refill_tokens: int = Field(strict=True, gt=0, le=_MAX_INT)
    refill_period_seconds: int = Field(strict=True, gt=0, le=_MAX_INT)

    @property
    def unit(self):
        return self.refill_period_seconds * 1_000_000

    @property
    def maximum(self):
        return self.capacity * self.unit

    @model_validator(mode="after")
    def valid_storage_range(self):
        if self.maximum > _MAX_INT:
            raise ValueError("Bucket policy exceeds supported storage range.")
        return self


class AdminAdmissionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    origin: BucketPolicy
    origin_identity: BucketPolicy


class AdmissionOutcome(StrEnum):
    ALLOWED = "allowed"
    LIMITED = "limited"


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    outcome: AdmissionOutcome
    retry_after_seconds: int = Field(strict=True, ge=0)


def utc_instant(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timezone-aware admission instant required.")
    return value.astimezone(timezone.utc)


def elapsed_microseconds(start, end):
    delta = end-start
    return (delta.days*86400+delta.seconds)*1_000_000+delta.microseconds


def ceil_div(value, divisor):
    return (value+divisor-1)//divisor


def expiry(now, credits, policy):
    # Physical TTL deletion is safe only once this bucket would be full again.
    return now+timedelta(microseconds=ceil_div(policy.maximum-credits, policy.refill_tokens))


def read_bucket(document, policy, scope):
    if document is None:
        return None
    keys = {"schema_version", "purpose", "scope", "policy", "credits", "updated_at", "expires_at"}
    if not isinstance(document, dict) or set(document) != keys:
        raise ValueError("Invalid admission storage structure.")
    if (type(document["schema_version"]) is not int or document["schema_version"] != 1
        or document["purpose"] != "admin-admission-v1" or document["scope"] != scope
        or type(document["credits"]) is not int or not 0 <= document["credits"] <= policy.maximum):
        raise ValueError("Invalid admission storage contract.")
    stored_policy = BucketPolicy.model_validate(document["policy"])
    if stored_policy != policy:
        raise ValueError("Admission policy change requires explicit migration.")
    updated = utc_instant(document["updated_at"])
    if utc_instant(document["expires_at"]) != expiry(updated, document["credits"], policy):
        raise ValueError("Invalid admission expiry.")
    return document


def evaluate_buckets(documents, policy, now):
    """Both consume or neither does. Rejects schema/config drift, even if expired."""
    policies = (policy.origin, policy.origin_identity)
    scopes = ("origin", "origin_identity")
    stored = [read_bucket(doc, rule, scope) for doc, rule, scope in zip(documents, policies, scopes)]
    logical_now = max([utc_instant(now)]+[utc_instant(doc["updated_at"]) for doc in stored if doc is not None])
    balances = [rule.maximum if doc is None else min(rule.maximum, doc["credits"]+
        elapsed_microseconds(utc_instant(doc["updated_at"]), logical_now)*rule.refill_tokens)
        for doc, rule in zip(stored, policies)]
    wait_us = max(ceil_div(max(0, rule.unit-balance), rule.refill_tokens)
                  for balance, rule in zip(balances, policies))
    if wait_us:
        return AdmissionDecision(outcome="limited", retry_after_seconds=ceil_div(wait_us, 1_000_000)), None
    updates = []
    for balance, rule, scope in zip(balances, policies, scopes):
        credits = balance-rule.unit
        updates.append(dict(schema_version=1, purpose="admin-admission-v1", scope=scope,
            policy=rule.model_dump(), credits=credits, updated_at=logical_now,
            expires_at=expiry(logical_now, credits, rule)))
    return AdmissionDecision(outcome="allowed", retry_after_seconds=0), updates
