from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class EventEnvelope(StrictBaseModel):
    event_id: str = Field(default_factory=lambda: make_id("evt"))
    topic: str
    producer: str = "system"
    trading_day: date | None = None
    run_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    schema_version: str = "1.0"
    payload: dict[str, Any]
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


def payload_to_dict(event: BaseModel | dict[str, Any] | object) -> dict[str, Any]:
    if isinstance(event, EventEnvelope):
        return event.payload
    if isinstance(event, BaseModel):
        return event.model_dump(mode="json")
    if isinstance(event, dict):
        return event
    return {"value": event}


def make_envelope(
    topic: str,
    event: BaseModel | dict[str, Any] | object,
    *,
    producer: str = "system",
    trading_day: date | None = None,
    run_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    schema_version: str = "1.0",
    evidence_ids: list[str] | None = None,
) -> EventEnvelope:
    if isinstance(event, EventEnvelope):
        return event
    return EventEnvelope(
        topic=topic,
        producer=producer,
        trading_day=trading_day,
        run_id=run_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        schema_version=schema_version,
        payload=payload_to_dict(event),
        evidence_ids=evidence_ids or [],
    )
