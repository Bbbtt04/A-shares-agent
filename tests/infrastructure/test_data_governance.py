from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_agent_system.core.data_quality import (
    DataQualityCheck,
    DataLineageRecord,
    DataQualityScorer,
    DataQualitySeverity,
)
from trading_agent_system.core.data_sources import (
    DataSourceRegistry,
    SourceHealth,
    SourceKind,
)
from trading_agent_system.core.entities import EntityResolver, SecurityEntity


def test_source_registry_orders_healthy_candidates_before_degraded_fallbacks():
    registry = DataSourceRegistry()
    registry.register(name="eastmoney", kind=SourceKind.MARKET, priority=100)
    registry.register(name="tencent", kind=SourceKind.MARKET, priority=80)

    registry.record_success("tencent")
    registry.record_failure("eastmoney", "timeout from provider")

    candidates = registry.candidates(SourceKind.MARKET)

    assert [source.name for source in candidates] == ["tencent", "eastmoney"]
    assert candidates[0].health == SourceHealth.HEALTHY
    assert candidates[0].success_count == 1
    assert candidates[1].health == SourceHealth.DEGRADED
    assert candidates[1].failure_count == 1
    assert candidates[1].last_error == "timeout from provider"


def test_entity_resolver_resolves_code_symbol_name_and_alias_to_full_symbol():
    resolver = EntityResolver()
    resolver.register(
        SecurityEntity(
            symbol="510300.SH",
            name="CSI 300 ETF",
            aliases=["HS300 ETF", "300ETF"],
            kind="fund",
        )
    )

    assert resolver.resolve("510300").symbol == "510300.SH"
    assert resolver.resolve("510300.SH").symbol == "510300.SH"
    assert resolver.resolve("CSI 300 ETF").symbol == "510300.SH"
    assert resolver.resolve("300ETF").symbol == "510300.SH"


def test_data_quality_scorer_penalizes_missing_required_fields_and_failed_checks():
    observed_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    scorer = DataQualityScorer(missing_field_penalty=0.2)
    checks = [
        DataQualityCheck(
            name="source",
            passed=False,
            severity=DataQualitySeverity.WARNING,
            penalty=0.1,
            metadata={"source": "eastmoney"},
        ),
        DataQualityCheck(
            name="freshness",
            passed=False,
            severity=DataQualitySeverity.ERROR,
            penalty=0.25,
            metadata={"max_age_seconds": 60},
        ),
    ]

    result = scorer.score(
        record={"symbol": "510300.SH", "price": None},
        required_fields=["symbol", "price", "volume"],
        source="eastmoney",
        observed_at=observed_at,
        checks=checks,
    )

    assert result.score == pytest.approx(0.25)
    assert result.observed_at == observed_at
    assert result.source == "eastmoney"
    assert result.missing_fields == ["price", "volume"]
    assert [check.name for check in result.checks] == ["source", "freshness"]
    assert result.metadata["failed_checks"] == ["source", "freshness"]
    assert result.metadata["required_fields"] == ["symbol", "price", "volume"]


def test_data_quality_result_keeps_lineage_for_source_records():
    observed_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    lineage = DataLineageRecord(
        source="eastmoney",
        source_record_id="quote-510300-20260614",
        processing_steps=["normalize_symbol", "align_timestamp"],
        observed_at=observed_at,
    )
    result = DataQualityScorer().score(
        record={"symbol": "510300.SH", "price": 3.15},
        required_fields=["symbol", "price"],
        source="eastmoney",
        observed_at=observed_at,
        lineage=lineage,
    )

    assert result.lineage == lineage
    assert result.lineage.processing_steps == ["normalize_symbol", "align_timestamp"]
