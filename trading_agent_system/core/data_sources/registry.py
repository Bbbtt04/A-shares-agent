from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class SourceKind(str, Enum):
    MARKET = "market"
    FUNDAMENTAL = "fundamental"
    NEWS = "news"
    RESEARCH = "research"
    ANNOUNCEMENT = "announcement"


class SourceHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class DataSource(StrictBaseModel):
    source_id: str = Field(default_factory=lambda: make_id("source"))
    name: str
    kind: SourceKind
    priority: int = 0
    health: SourceHealth = SourceHealth.HEALTHY
    success_count: int = 0
    failure_count: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class DataSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, DataSource] = {}

    def register(
        self,
        *,
        name: str,
        kind: SourceKind,
        priority: int = 0,
        health: SourceHealth = SourceHealth.HEALTHY,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> DataSource:
        source = DataSource(
            name=name,
            kind=kind,
            priority=priority,
            health=health,
            metadata=metadata or {},
        )
        self._sources[name] = source
        return source

    def get(self, name: str) -> DataSource | None:
        return self._sources.get(name)

    def record_success(self, name: str) -> DataSource:
        source = self._require_source(name)
        updated = source.model_copy(
            update={
                "health": SourceHealth.HEALTHY,
                "success_count": source.success_count + 1,
                "last_success_at": utc_now(),
                "last_error": None,
            }
        )
        self._sources[name] = updated
        return updated

    def record_failure(self, name: str, error: str) -> DataSource:
        source = self._require_source(name)
        updated = source.model_copy(
            update={
                "health": SourceHealth.DEGRADED,
                "failure_count": source.failure_count + 1,
                "last_failure_at": utc_now(),
                "last_error": error,
            }
        )
        self._sources[name] = updated
        return updated

    def candidates(self, kind: SourceKind) -> list[DataSource]:
        candidates = [
            source
            for source in self._sources.values()
            if source.kind == kind and source.health != SourceHealth.DISABLED
        ]
        return sorted(candidates, key=self._candidate_sort_key)

    def _require_source(self, name: str) -> DataSource:
        source = self.get(name)
        if source is None:
            raise KeyError(f"unknown data source: {name}")
        return source

    @staticmethod
    def _candidate_sort_key(source: DataSource) -> tuple[int, int, str]:
        health_rank = 0 if source.health == SourceHealth.HEALTHY else 1
        return health_rank, -source.priority, source.name
