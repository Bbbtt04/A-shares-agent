from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.run_daily_premarket_recommendation import run_daily_recommendation


class FakeRuns:
    def __init__(self) -> None:
        self.started: list[tuple[str, date, str, dict[str, object]]] = []
        self.finished: list[tuple[str, str, str | None]] = []

    def start(self, run_id: str, trading_day: date, run_type: str, *, metadata: dict[str, object]) -> None:
        self.started.append((run_id, trading_day, run_type, metadata))

    def finish(self, run_id: str, status: str, error_message: str | None = None) -> None:
        self.finished.append((run_id, status, error_message))


class FakeRecommendations:
    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []

    def save(self, payload: dict[str, object]) -> None:
        self.saved.append(payload)


class FakeAudits:
    def __init__(self) -> None:
        self.logged: list[dict[str, object]] = []

    def log(self, payload: dict[str, object]) -> None:
        self.logged.append(payload)


class FakeLedgerStore:
    def __init__(self) -> None:
        self.runs = FakeRuns()
        self.recommendations = FakeRecommendations()
        self.audits = FakeAudits()


def _pipeline_result(*recommendations: SimpleNamespace) -> dict[str, object]:
    generated_at = datetime(2026, 6, 19, 1, 10, tzinfo=timezone.utc)
    return {
        "semantic_reviews": SimpleNamespace(
            review_id="review_20260619",
            trading_day=date(2026, 6, 19),
            reviews=[{"symbol": "600519.SH", "semantic_verdict": "candidate"}],
        ),
        "factor_scores": SimpleNamespace(
            score_id="scores_20260619",
            trading_day=date(2026, 6, 19),
            scores=[{"symbol": "600519.SH", "signal_score": 0.71}],
        ),
        "recommendations": SimpleNamespace(
            recommendation_id="recommendations_20260619",
            trading_day=date(2026, 6, 19),
            generated_at=generated_at,
            recommendations=list(recommendations),
        ),
    }


def test_run_daily_recommendation_saves_pipeline_recommendations(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run_pipeline(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return _pipeline_result(
            SimpleNamespace(
                symbol="600519.SH",
                action="candidate",
                priority=1,
                confidence=0.82,
                signal_score=0.71,
                entry_conditions=["open confirms theme"],
                avoid_conditions=["fresh negative filing"],
                risk_notes=["crowding medium"],
                evidence_ids=["ev_1"],
                handoff_payload_version="premarket_strategy_handoff.v1",
            )
        )

    monkeypatch.setattr("scripts.run_daily_premarket_recommendation.run_pipeline", fake_run_pipeline)
    ledger = FakeLedgerStore()
    generated_at = datetime(2026, 6, 19, 1, 0, tzinfo=timezone.utc)

    result = run_daily_recommendation(
        tmp_path / "2026-06-19.json",
        ledger,
        event_dir=tmp_path / "events",
        learning_dir=tmp_path / "learning",
        generated_at=generated_at,
        run_id="daily_20260619",
        top_n=3,
        llm_gateway=object(),
    )

    assert captured["report_path"] == tmp_path / "2026-06-19.json"
    assert captured["run_id"] == "daily_20260619"
    assert captured["top_n"] == 3
    assert ledger.runs.started == [
        (
            "daily_20260619",
            date(2026, 6, 19),
            "premarket_recommend",
            {"report_path": str(tmp_path / "2026-06-19.json"), "top_n": 3},
        )
    ]
    assert ledger.runs.finished == [("daily_20260619", "success", None)]
    assert ledger.recommendations.saved[0]["recommendation_id"] == "daily_20260619_600519.SH_1"
    assert ledger.recommendations.saved[0]["symbol"] == "600519.SH"
    assert ledger.recommendations.saved[0]["expected_risk_reward"] is None
    assert ledger.recommendations.saved[0]["handoff_payload"]["version"] == "premarket_strategy_handoff.v1"
    assert ledger.recommendations.saved[0]["handoff_payload"]["evidence_ids"] == ["ev_1"]
    assert [item["stage"] for item in ledger.audits.logged] == [
        "semantic_review",
        "factor_scoring",
        "recommendation",
    ]
    assert result["run_id"] == "daily_20260619"
    assert result["saved_recommendation_count"] == 1


def test_run_daily_recommendation_saves_no_trade_when_pipeline_has_no_recommendations(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "scripts.run_daily_premarket_recommendation.run_pipeline",
        lambda **_: _pipeline_result(),
    )
    ledger = FakeLedgerStore()

    result = run_daily_recommendation(
        tmp_path / "2026-06-19.json",
        ledger,
        run_id="daily_empty",
    )

    saved = ledger.recommendations.saved[0]
    assert saved["recommendation_id"] == "daily_empty_no_trade"
    assert saved["action"] == "no_trade"
    assert saved["symbol"] == "NO_TRADE"
    assert saved["priority"] == 1
    assert saved["handoff_payload"]["reason"] == "pipeline returned no recommendations"
    assert ledger.runs.finished == [("daily_empty", "success", None)]
    assert result["saved_recommendation_count"] == 1


def test_run_daily_recommendation_marks_run_failed_when_pipeline_raises(monkeypatch, tmp_path) -> None:
    def fake_run_pipeline(**_: object) -> dict[str, object]:
        raise RuntimeError("semantic review unavailable")

    monkeypatch.setattr("scripts.run_daily_premarket_recommendation.run_pipeline", fake_run_pipeline)
    ledger = FakeLedgerStore()

    with pytest.raises(RuntimeError, match="semantic review unavailable"):
        run_daily_recommendation(
            tmp_path / "2026-06-19.json",
            ledger,
            run_id="daily_failed",
        )

    assert ledger.runs.finished == [("daily_failed", "failed", "semantic review unavailable")]
    assert ledger.recommendations.saved == []
    assert ledger.audits.logged == []
