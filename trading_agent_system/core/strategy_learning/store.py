from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel, utc_now


DEFAULT_STRATEGY_ID = "one_pick_two_day_v1"


class LearningStateVersion(StrictBaseModel):
    version_id: str
    strategy_id: str = DEFAULT_STRATEGY_ID
    version: int = Field(ge=1)
    scoring_weights: dict[str, float] = Field(default_factory=dict)
    risk_penalties: dict[str, float] = Field(default_factory=dict)
    confidence_penalties: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_version_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class LearningCurrentPointer(StrictBaseModel):
    strategy_id: str = DEFAULT_STRATEGY_ID
    version_id: str
    updated_at: datetime = Field(default_factory=utc_now)


class LearningRollbackAuditPayload(StrictBaseModel):
    event_type: Literal["strategy_learning.rollback"] = "strategy_learning.rollback"
    strategy_id: str = DEFAULT_STRATEGY_ID
    from_version_id: str
    to_version_id: str
    reason: str
    actor: str
    payload: dict[str, Any]


class LearningStateStore:
    def __init__(self, base_dir: str | Path = "data/strategy_learning", strategy_id: str = DEFAULT_STRATEGY_ID) -> None:
        self.base_dir = Path(base_dir)
        self.strategy_id = strategy_id
        self.versions_path = self.base_dir / "one_pick_versions.jsonl"
        self.current_pointer_path = self.base_dir / "one_pick_current.json"

    def list_versions(self) -> list[LearningStateVersion]:
        if not self.versions_path.exists():
            return []
        versions: list[LearningStateVersion] = []
        with self.versions_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    versions.append(LearningStateVersion.model_validate_json(line))
        return versions

    def get_version(self, version_id: str) -> LearningStateVersion | None:
        for version in self.list_versions():
            if version.version_id == version_id:
                return version
        return None

    def get_current(self) -> LearningStateVersion | None:
        if not self.current_pointer_path.exists():
            return None
        pointer = LearningCurrentPointer.model_validate_json(
            self.current_pointer_path.read_text(encoding="utf-8")
        )
        return self.get_version(pointer.version_id)

    def create_next_version(
        self,
        *,
        scoring_weights: dict[str, float] | None = None,
        risk_penalties: dict[str, float] | None = None,
        confidence_penalties: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LearningStateVersion:
        versions = self.list_versions()
        current = self.get_current()
        next_number = max((version.version for version in versions), default=0) + 1
        version_id = f"{self.strategy_id}-v{next_number:06d}"
        if any(version.version_id == version_id for version in versions):
            raise ValueError(f"learning state version already exists: {version_id}")

        created = LearningStateVersion(
            version_id=version_id,
            strategy_id=self.strategy_id,
            version=next_number,
            scoring_weights=scoring_weights or {},
            risk_penalties=risk_penalties or {},
            confidence_penalties=confidence_penalties or {},
            metadata=metadata or {},
            previous_version_id=current.version_id if current else None,
        )
        self._append_version(created)
        self._write_current_pointer(created.version_id)
        return created

    def rollback_current(self, *, target_version_id: str, reason: str, actor: str = "system") -> dict[str, Any]:
        current = self.get_current()
        target = self.get_version(target_version_id)
        if current is None:
            raise ValueError("cannot rollback without a current learning version")
        if target is None:
            raise ValueError(f"unknown learning state version: {target_version_id}")

        self._write_current_pointer(target.version_id)
        audit = LearningRollbackAuditPayload(
            strategy_id=self.strategy_id,
            from_version_id=current.version_id,
            to_version_id=target.version_id,
            reason=reason,
            actor=actor,
            payload={
                "from_version": current.version,
                "to_version": target.version,
                "from_created_at": current.created_at.isoformat(),
                "to_created_at": target.created_at.isoformat(),
            },
        )
        return audit.model_dump(mode="json")

    def _append_version(self, version: LearningStateVersion) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with self.versions_path.open("a", encoding="utf-8") as fh:
            fh.write(version.model_dump_json())
            fh.write("\n")

    def _write_current_pointer(self, version_id: str) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        pointer = LearningCurrentPointer(strategy_id=self.strategy_id, version_id=version_id)
        self.current_pointer_path.write_text(
            json.dumps(pointer.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
