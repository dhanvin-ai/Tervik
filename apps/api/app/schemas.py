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
