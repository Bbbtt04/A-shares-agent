from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol

from trading_agent_system.core.events import EventEnvelope


EventHandler = Callable[[object], None]


class EventBus(Protocol):
    def publish(
        self,
        topic: str,
        event: object,
        *,
        producer: str = "system",
        trading_day: date | None = None,
        run_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        schema_version: str = "1.0",
        evidence_ids: list[str] | None = None,
    ) -> EventEnvelope:
        ...

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        ...

    def events(self, topic: str) -> list[object]:
        ...

    def envelopes(self, topic: str) -> list[EventEnvelope]:
        ...
