from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class DataQualitySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DataQualityCheck(StrictBaseModel):
    name: str
    passed: bool
    severity: DataQualitySeverity = DataQualitySeverity.WARNING
    penalty: float = Field(default=0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataLineageRecord(StrictBaseModel):
    lineage_id: str = Field(default_factory=lambda: make_id("lineage"))
    source: str
    source_record_id: str
    processing_steps: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityResult(StrictBaseModel):
    result_id: str = Field(default_factory=lambda: make_id("dq"))
    score: float = Field(ge=0, le=1)
    observed_at: datetime = Field(default_factory=utc_now)
    source: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    checks: list[DataQualityCheck] = Field(default_factory=list)
    lineage: DataLineageRecord | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityScorer:
    def __init__(self, *, missing_field_penalty: float = 0.15) -> None:
        if missing_field_penalty < 0 or missing_field_penalty > 1:
            raise ValueError("missing_field_penalty must be between 0 and 1")
        self.missing_field_penalty = missing_field_penalty

    def score(
        self,
        *,
        record: dict[str, Any],
        required_fields: list[str],
        source: str | None = None,
        observed_at: datetime | None = None,
        checks: list[DataQualityCheck] | None = None,
        lineage: DataLineageRecord | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataQualityResult:
        observed = observed_at or utc_now()
        quality_checks = checks or []
        missing_fields = [
            field
            for field in required_fields
            if field not in record or record[field] is None or record[field] == ""
        ]
        failed_checks = [check for check in quality_checks if not check.passed]
        missing_penalty = len(missing_fields) * self.missing_field_penalty
        check_penalty = sum(check.penalty for check in failed_checks)
        total_penalty = min(1.0, missing_penalty + check_penalty)
        result_metadata = {
            "required_fields": list(required_fields),
            "failed_checks": [check.name for check in failed_checks],
            "missing_field_penalty": self.missing_field_penalty,
            "total_penalty": total_penalty,
            "record_fields": sorted(record.keys()),
        }
        if metadata:
            result_metadata.update(metadata)
        return DataQualityResult(
            score=max(0.0, round(1.0 - total_penalty, 10)),
            observed_at=observed,
            source=source,
            missing_fields=missing_fields,
            checks=quality_checks,
            lineage=lineage,
            metadata=result_metadata,
        )
