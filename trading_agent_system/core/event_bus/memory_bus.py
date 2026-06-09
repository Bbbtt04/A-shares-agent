from __future__ import annotations

from collections import defaultdict
from datetime import date

from .bus import EventHandler
from trading_agent_system.core.events import EventEnvelope, make_envelope


class MemoryEventBus:
    def __init__(self) -> None:
        self._events: dict[str, list[object]] = defaultdict(list)
        self._envelopes: dict[str, list[EventEnvelope]] = defaultdict(list)
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

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
        envelope = make_envelope(
            topic,
            event,
            producer=producer,
            trading_day=trading_day,
            run_id=run_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            schema_version=schema_version,
            evidence_ids=evidence_ids,
        )
        self._events[topic].append(envelope.payload)
        self._envelopes[topic].append(envelope)
        for handler in list(self._handlers.get(topic, [])):
            handler(envelope.payload)
        return envelope

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._handlers[topic].append(handler)

    def events(self, topic: str) -> list[object]:
        return list(self._events.get(topic, []))

    def envelopes(self, topic: str) -> list[EventEnvelope]:
        return list(self._envelopes.get(topic, []))

    def all_events(self) -> dict[str, list[object]]:
        return {topic: list(events) for topic, events in self._events.items()}
