from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class RuntimeCheckpoint(StrictBaseModel):
    checkpoint_id: str = Field(default_factory=lambda: make_id("checkpoint"))
    run_id: str
    trading_day: date | None
    agent: str
    step: str
    status: Literal["pending", "running", "success", "failed", "invalidated"]
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CheckpointStore:
    def __init__(self, base_dir: str | Path = "data/runtime/checkpoints") -> None:
        self.base_dir = Path(base_dir)
        self._by_step: dict[tuple[str, str], RuntimeCheckpoint] = {}
        self._by_run: dict[str, list[RuntimeCheckpoint]] = {}
        self._load_index()

    def save(self, checkpoint: RuntimeCheckpoint) -> RuntimeCheckpoint:
        checkpoint.updated_at = utc_now()
        self._append(checkpoint)
        self._index(checkpoint)
        return checkpoint

    def save_success(
        self,
        *,
        run_id: str,
        trading_day: date | None,
        agent: str,
        step: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeCheckpoint:
        return self.save(
            RuntimeCheckpoint(
                run_id=run_id,
                trading_day=trading_day,
                agent=agent,
                step=step,
                status="success",
                input_refs=input_refs or [],
                output_refs=output_refs or [],
                payload=payload or {},
            )
        )

    def save_failed(
        self,
        *,
        run_id: str,
        trading_day: date | None,
        agent: str,
        step: str,
        error: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeCheckpoint:
        return self.save(
            RuntimeCheckpoint(
                run_id=run_id,
                trading_day=trading_day,
                agent=agent,
                step=step,
                status="failed",
                input_refs=input_refs or [],
                output_refs=output_refs or [],
                payload=payload or {},
                error=error,
            )
        )

    def invalidate(self, *, run_id: str, step: str, reason: str) -> RuntimeCheckpoint:
        existing = self.load(run_id=run_id, step=step)
        if existing is None:
            raise KeyError(f"checkpoint not found for run_id={run_id!r} step={step!r}")
        return self.save(
            RuntimeCheckpoint(
                run_id=existing.run_id,
                trading_day=existing.trading_day,
                agent=existing.agent,
                step=existing.step,
                status="invalidated",
                input_refs=existing.input_refs,
                output_refs=existing.output_refs,
                payload=existing.payload,
                error=reason,
            )
        )

    def load(self, *, run_id: str, step: str) -> RuntimeCheckpoint | None:
        return self._by_step.get((run_id, step))

    def load_latest(self, run_id: str) -> RuntimeCheckpoint | None:
        checkpoints = self._by_run.get(run_id, [])
        if not checkpoints:
            return None
        return checkpoints[-1]

    def is_completed(self, *, run_id: str, step: str) -> bool:
        checkpoint = self.load(run_id=run_id, step=step)
        return checkpoint is not None and checkpoint.status == "success"

    def _load_index(self) -> None:
        if not self.base_dir.exists():
            return
        for path in sorted(self.base_dir.glob("*.jsonl")):
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    self._index(RuntimeCheckpoint.model_validate(json.loads(line)))

    def _append(self, checkpoint: RuntimeCheckpoint) -> None:
        path = self.base_dir / f"{checkpoint.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, default=str) + "\n")

    def _index(self, checkpoint: RuntimeCheckpoint) -> None:
        self._by_step[(checkpoint.run_id, checkpoint.step)] = checkpoint
        self._by_run.setdefault(checkpoint.run_id, []).append(checkpoint)
