from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FAMILY_AUTHORIZATION_CONTRACT_VERSION = "hexe.family-identity-authorization.v1"

IdentityState = Literal["authenticated", "verified", "confirmed", "probable", "unknown", "conflicted"]
PlatformRole = Literal["owner", "admin", "member", "guest"]
AudienceMode = Literal["private", "shared", "group", "public", "unknown"]
MemoryAction = Literal["memory.read", "memory.write", "memory.delete", "memory.export"]
MemoryRisk = Literal["general", "personal", "personal_sensitive"]
MemoryVisibility = Literal["private", "explicit", "household", "room", "guardian_managed"]
AuthorizationEffect = Literal["allow", "deny"]
MemoryLifecycleStatus = Literal["active", "expired", "deleted"]
AuditResult = Literal["allowed", "denied", "completed", "failed"]
LifecycleAction = Literal["memory.delete", "memory.export"]
LifecycleRequestStatus = Literal["pending", "in_progress", "completed", "incomplete", "failed"]


def _require_identifier(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name}_required")
    if len(normalized) > 255:
        raise ValueError(f"{field_name}_too_long")
    return normalized


def _require_aware_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}_timezone_required")
    return value


class FamilyRequester(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    person_id: str | None = None
    platform_role: PlatformRole
    session_id: str | None = None
    device_id: str | None = None

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        return _require_identifier(value, field_name="user_id")

    @field_validator("person_id", "session_id", "device_id")
    @classmethod
    def _validate_optional_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name=str(info.field_name))


class FamilyParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: str | None = None
    identity_state: IdentityState
    evidence_id: str | None = None

    @field_validator("person_id", "evidence_id")
    @classmethod
    def _validate_optional_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def _validate_identity(self) -> "FamilyParticipant":
        if self.identity_state in {"authenticated", "verified", "confirmed", "probable"} and self.person_id is None:
            raise ValueError("participant_person_id_required")
        if self.identity_state in {"unknown", "conflicted"} and self.person_id is not None:
            raise ValueError("uncertain_participant_person_id_forbidden")
        return self


class FamilyRoomContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str | None = None
    endpoint_id: str | None = None
    audience_mode: AudienceMode

    @field_validator("room_id", "endpoint_id")
    @classmethod
    def _validate_optional_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name=str(info.field_name))


class FamilyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryAction
    risk: MemoryRisk
    requested_visibility: list[MemoryVisibility] = Field(min_length=1)

    @field_validator("requested_visibility")
    @classmethod
    def _deduplicate_visibility(cls, value: list[MemoryVisibility]) -> list[MemoryVisibility]:
        return list(dict.fromkeys(value))


class FamilyAuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect: AuthorizationEffect
    allowed_person_ids: list[str] = Field(default_factory=list)
    allowed_visibility: list[MemoryVisibility] = Field(default_factory=list)
    allowed_actions: list[MemoryAction] = Field(default_factory=list)
    consent_ids: list[str] = Field(default_factory=list)
    policy_version: str

    @field_validator("allowed_person_ids", "consent_ids")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("allowed_visibility", "allowed_actions")
    @classmethod
    def _deduplicate_enum_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("policy_version")
    @classmethod
    def _validate_policy_version(cls, value: str) -> str:
        return _require_identifier(value, field_name="policy_version")


class FamilyAuthorizationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["hexe.family-identity-authorization.v1"]
    authorization_id: str
    core_id: str
    household_id: str
    requester: FamilyRequester
    participants: list[FamilyParticipant] = Field(default_factory=list)
    context: FamilyRoomContext
    operation: FamilyOperation
    decision: FamilyAuthorizationDecision
    issued_at: datetime
    expires_at: datetime
    jti: str

    @field_validator("authorization_id", "core_id", "household_id", "jti")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _validate_datetime(cls, value: datetime, info) -> datetime:
        return _require_aware_datetime(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def _validate_lifetime(self) -> "FamilyAuthorizationContext":
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization_expiry_invalid")
        if self.expires_at - self.issued_at > timedelta(seconds=120):
            raise ValueError("authorization_lifetime_exceeds_limit")
        return self


class FamilyInteractionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    interaction_id: str
    core_id: str
    household_id: str
    room_id: str | None = None
    endpoint_id: str | None = None
    participant_person_ids: list[str] = Field(default_factory=list)
    unknown_person_present: bool = False
    audience_mode: AudienceMode
    authorization_id: str
    created_at: datetime

    @field_validator("interaction_id", "core_id", "household_id", "authorization_id")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("room_id", "endpoint_id")
    @classmethod
    def _validate_optional_identifier(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("participant_person_ids")
    @classmethod
    def _validate_participants(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(_require_identifier(item, field_name="participant_person_ids") for item in value))

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field_name="created_at")


class FamilyMemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    memory_id: str
    core_id: str
    household_id: str
    subject_person_ids: list[str] = Field(min_length=1)
    visibility: MemoryVisibility
    audience_person_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=4096)
    sensitivity: MemoryRisk
    consent_ids: list[str] = Field(min_length=1)
    source_interaction_id: str
    source_room_id: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    status: MemoryLifecycleStatus = "active"

    @field_validator("memory_id", "core_id", "household_id", "source_interaction_id")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("source_room_id")
    @classmethod
    def _validate_optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name="source_room_id")

    @field_validator("subject_person_ids", "audience_person_ids", "consent_ids")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("created_at", "updated_at", "expires_at")
    @classmethod
    def _validate_datetime(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _require_aware_datetime(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def _validate_scope_and_lifecycle(self) -> "FamilyMemoryRecord":
        if self.visibility == "private" and (len(self.subject_person_ids) != 1 or self.audience_person_ids):
            raise ValueError("private_memory_scope_invalid")
        if self.visibility == "explicit" and not self.audience_person_ids:
            raise ValueError("explicit_memory_audience_required")
        if self.updated_at < self.created_at:
            raise ValueError("memory_updated_at_before_created_at")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("memory_expiry_invalid")
        return self


class FamilyMemoryAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    event_id: str
    authorization_id: str
    action: MemoryAction
    result: AuditResult
    reason: str
    subject_person_ids: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime

    @field_validator("event_id", "authorization_id", "reason")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("subject_person_ids", "memory_ids")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field_name="occurred_at")


class FamilyMemoryLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str
    authorization_id: str
    core_id: str
    household_id: str
    action: LifecycleAction
    subject_person_ids: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    requested_at: datetime
    expires_at: datetime

    @field_validator("request_id", "authorization_id", "core_id", "household_id")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("subject_person_ids", "categories")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("requested_at", "expires_at")
    @classmethod
    def _validate_datetime(cls, value: datetime, info) -> datetime:
        return _require_aware_datetime(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def _validate_expiry(self) -> "FamilyMemoryLifecycleRequest":
        if self.expires_at <= self.requested_at:
            raise ValueError("lifecycle_request_expiry_invalid")
        return self


class FamilyMemoryDeletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str
    request_id: str
    authorization_id: str
    core_id: str
    household_id: str
    subject_person_ids: list[str] = Field(min_length=1)
    categories_deleted: list[str] = Field(default_factory=list)
    categories_retained: list[str] = Field(default_factory=list)
    retention_reason: str | None = None
    status: LifecycleRequestStatus
    completed_at: datetime

    @field_validator("receipt_id", "request_id", "authorization_id", "core_id", "household_id")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("subject_person_ids", "categories_deleted", "categories_retained")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("retention_reason")
    @classmethod
    def _validate_retention_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_identifier(value, field_name="retention_reason")

    @field_validator("completed_at")
    @classmethod
    def _validate_completed_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field_name="completed_at")

    @model_validator(mode="after")
    def _validate_result(self) -> "FamilyMemoryDeletionReceipt":
        overlap = set(self.categories_deleted) & set(self.categories_retained)
        if overlap:
            raise ValueError("deletion_receipt_category_overlap")
        if self.categories_retained and self.retention_reason is None:
            raise ValueError("deletion_receipt_retention_reason_required")
        if self.status == "completed" and self.categories_retained:
            raise ValueError("deletion_receipt_completed_with_retained_categories")
        return self


class FamilyMemoryExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    export_id: str
    request_id: str
    authorization_id: str
    core_id: str
    household_id: str
    subject_person_ids: list[str] = Field(min_length=1)
    categories_exported: list[str] = Field(default_factory=list)
    record_count: int = Field(ge=0)
    generated_at: datetime

    @field_validator("export_id", "request_id", "authorization_id", "core_id", "household_id")
    @classmethod
    def _validate_identifier(cls, value: str, info) -> str:
        return _require_identifier(value, field_name=str(info.field_name))

    @field_validator("subject_person_ids", "categories_exported")
    @classmethod
    def _validate_identifier_list(cls, value: list[str], info) -> list[str]:
        normalized = [_require_identifier(item, field_name=str(info.field_name)) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field_name="generated_at")
