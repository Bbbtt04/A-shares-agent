from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from trading_agent_system.core.events import EventEnvelope
from trading_agent_system.schemas import EVENT_MODEL_BY_TOPIC


class JsonlEventRepository:
    def __init__(self, base_dir: str | Path = "data/events") -> None:
        self.base_dir = Path(base_dir)

    def append(self, topic: str, event: BaseModel | dict[str, Any]) -> None:
        data = event.model_dump(mode="json") if isinstance(event, BaseModel) else event
        path = self._topic_path(topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")

    def append_envelope(self, envelope: EventEnvelope) -> None:
        path = self._topic_path(envelope.topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, default=str) + "\n")

    def load(self, topic: str) -> list[object]:
        path = self._topic_path(topic)
        if not path.exists():
            return []
        model = EVENT_MODEL_BY_TOPIC.get(topic)
        loaded: list[object] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                loaded.append(model.model_validate(data) if model else data)
        return loaded

    def load_envelopes(
        self,
        topic: str,
        *,
        trading_day: object | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        path = self._topic_path(topic)
        if not path.exists():
            return []
        loaded: list[EventEnvelope] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                envelope = EventEnvelope.model_validate(data)
                if trading_day is not None and envelope.trading_day != trading_day:
                    continue
                if run_id is not None and envelope.run_id != run_id:
                    continue
                loaded.append(envelope)
        if limit is not None and limit >= 0:
            return loaded[-limit:]
        return loaded

    def list_topics(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(path.stem.replace("_", ".") for path in self.base_dir.glob("*.jsonl"))

    def _topic_path(self, topic: str) -> Path:
        return self.base_dir / f"{topic.replace('.', '_')}.jsonl"
