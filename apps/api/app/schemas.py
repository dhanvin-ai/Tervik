from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4
import json
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from .db import utc_now


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)
    user_id: str | None = Field(default=None, max_length=200)
    role: Literal["user", "assistant", "tool", "system"]
    content: str = Field(max_length=32_000)
    timestamp: AwareDatetime = Field(default_factory=utc_now)
    trace_id: str | None = Field(default=None, max_length=200)
    span_id: str | None = Field(default=None, max_length=200)
    parent_span_id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    status: Literal["success", "error"] = "success"
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    tokens: int | None = Field(default=None, ge=0, strict=True)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model: str | None = Field(default=None, max_length=200)
    metadata: dict = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def no_future_timestamp(cls, value: datetime):
        if value > utc_now() + timedelta(minutes=5):
            raise ValueError("timestamp cannot be more than five minutes in the future")
        return value

    @field_validator("id", "conversation_id")
    @classmethod
    def nonblank_identifiers(cls, value: str):
        if not value.strip():
            raise ValueError("identifier cannot be blank")
        return value

    @field_validator("metadata")
    @classmethod
    def valid_json_metadata(cls, value: dict):
        try:
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as error:
            raise ValueError("metadata must contain finite JSON values") from error
        return value


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EventInput] = Field(min_length=1, max_length=100)


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class ClusterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "resolved"]


class SignupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=120)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class OrgInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    role: Literal["owner", "admin", "member", "viewer"] = "member"


class MemberPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["owner", "admin", "member", "viewer"]


class OrgProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="production", min_length=1, max_length=80)


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="default", min_length=1, max_length=120)
    environment: str | None = Field(default=None, max_length=80)


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_content: bool | None = None
    redact_keys: list[str] | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["forbidden_phrase", "required_tool"]
    pattern: str | None = Field(default=None, max_length=500)
    tool: str | None = Field(default=None, max_length=200)
    severity: Literal["critical", "high", "medium", "low"] = "high"

    @field_validator("name")
    @classmethod
    def clean_rule_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    severity: Literal["critical", "high", "medium", "low"] | None = None


class IntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    examples: list[str] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def clean_intent_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("examples")
    @classmethod
    def clean_examples(cls, value):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("at least one non-blank example is required")
        if any(len(item) > 500 for item in cleaned):
            raise ValueError("examples cannot exceed 500 characters")
        return cleaned[:20]


class IntentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=1000)


class DiscoveryRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)


class DiscoveryStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "dismissed"]


class DiscoveryMembers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)
    member_conversation_ids: list[str] = Field(min_length=1, max_length=500)


class DiscoveryMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[str] = Field(min_length=2, max_length=50)
    label: str = Field(min_length=1, max_length=200)


class AlertChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["webhook", "email"]
    target: str = Field(min_length=1, max_length=500)


class AlertRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["threshold", "trend", "summary"]
    signal_kind: str | None = Field(default=None, max_length=40)
    threshold: float = Field(default=1, ge=0, le=1000000)
    window_hours: int = Field(default=24, ge=1, le=720)
    min_samples: int = Field(default=10, ge=1, le=1000000)
    cooldown_hours: int = Field(default=24, ge=1, le=720)
    channels: list[AlertChannel] = Field(min_length=1, max_length=5)


class AlertRulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    threshold: float | None = Field(default=None, ge=0, le=1000000)
    cooldown_hours: int | None = Field(default=None, ge=1, le=720)
