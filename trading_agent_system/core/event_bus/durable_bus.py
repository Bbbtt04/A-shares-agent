from __future__ import annotations

from datetime import date

from trading_agent_system.core.events import EventEnvelope
from trading_agent_system.core.storage import JsonlEventRepository

from .memory_bus import MemoryEventBus


class DurableEventBus(MemoryEventBus):
    def __init__(self, repository: JsonlEventRepository | None = None) -> None:
        super().__init__()
        self.repository = repository or JsonlEventRepository()

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
        envelope = super().publish(
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
        self.repository.append_envelope(envelope)
        return envelope
