"""WebhookTarget and WebhookLog Pydantic v2 validation schemas."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WebhookTargetCreate(BaseModel):
    """Payload to register a new webhook destination."""

    name: str = Field(..., min_length=1, max_length=100, description="Descriptive target name")
    target_url: str = Field(..., max_length=500, description="HTTPS or HTTP subscriber endpoint URL")
    secret_token: str | None = Field(
        default=None,
        min_length=8,
        max_length=255,
        description="Optional shared secret key for HMAC signatures. Auto-generated if omitted.",
    )
    subscribed_events: list[str] = Field(
        default=["*"],
        description="List of event topics to subscribe to. Use ['*'] for all events.",
    )
    is_active: bool = Field(default=True, description="Whether this endpoint is active")


class WebhookTargetUpdate(BaseModel):
    """Payload to update an existing webhook destination."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    target_url: str | None = Field(default=None, max_length=500)
    secret_token: str | None = Field(default=None, min_length=8, max_length=255)
    subscribed_events: list[str] | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class WebhookTargetResponse(BaseModel):
    """Public schema for a registered webhook endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    target_url: str
    secret_token: str
    subscribed_events: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WebhookEventTrigger(BaseModel):
    """Payload to trigger an asynchronous event dispatch."""

    event_type: str = Field(..., min_length=1, max_length=100, description="Event identifier (e.g. 'order.created')")
    payload: dict[str, Any] = Field(..., description="JSON payload data sent to subscribers")


class WebhookLogResponse(BaseModel):
    """Delivery log record for a dispatch attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    webhook_id: int
    event_type: str
    payload: dict[str, Any]
    response_status_code: int | None = None
    response_body: str | None = None
    execution_duration_ms: float | None = None
    attempt_count: int
    status: str
    error_message: str | None = None
    created_at: datetime


class WebhookDispatchResult(BaseModel):
    """Response returned when an event is queued for dispatch."""

    event_type: str
    dispatched_targets_count: int
    task_ids: list[str]
    message: str
