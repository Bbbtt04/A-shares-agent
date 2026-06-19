from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from trading_agent_system.agents.premarket_agent.factor_learning import (
    PremarketFactorLearningAgent,
    PremarketFactorLearningStore,
    PremarketFactorLearningState,
)
from trading_agent_system.agents.premarket_agent.factor_scoring import PremarketFactorScore, PremarketFactorScoreSet
from trading_agent_system.agents.premarket_agent.outcome_evaluator import PremarketSignalOutcomeEvaluator


def _recommendation(
    symbol: str,
    score_breakdown: dict[str, float],
    risk_flags: list[str] | None = None,
    theme: str | None = "robotics",
    mode: str = "opportunity",
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        theme=theme,
        mode=mode,
        risk_flags=risk_flags or [],
        decision_trace={
            "score_breakdown": score_breakdown,
            "source_adjustments": {"official": 0.4},
            "llm_reliability": {"news_reasoning": 0.7},
        },
    )


def _score_set(*recommendations: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        signal_date=date(2026, 6, 18),
        conservative=list(recommendations),
        opportunity=[],
        watch=[],
    )


def test_outcome_evaluator_computes_returns_and_formula_score_from_prices() -> None:
    score_set = _score_set(
        _recommendation(
            "600001.SH",
            {"catalyst_strength": 0.8, "source_confirmation": 0.6},
            risk_flags=["rumor"],
        )
    )

    outcome_set = PremarketSignalOutcomeEvaluator().evaluate(
        score_set,
        {
            "600001.SH": {
                "reference": 10.0,
                "open": 10.2,
                "high": 10.8,
                "low": 9.7,
                "close": 10.4,
            }
        },
        index_return=0.01,
        evaluation_date=date(2026, 6, 19),
    )

    assert outcome_set.signal_date == date(2026, 6, 18)
    assert outcome_set.evaluation_date == date(2026, 6, 19)
    assert outcome_set.outcome_id == "pso_20260618_20260619"
    assert len(outcome_set.outcomes) == 1

    outcome = outcome_set.outcomes[0]
    assert outcome.symbol == "600001.SH"
    assert outcome.next_day_open_return == pytest.approx(0.02)
    assert outcome.next_day_high_return == pytest.approx(0.08)
    assert outcome.next_day_close_return == pytest.approx(0.04)
    assert outcome.max_favorable_excursion == pytest.approx(0.08)
    assert outcome.max_adverse_excursion == pytest.approx(-0.03)
    assert outcome.relative_return_vs_index == pytest.approx(0.03)
    assert outcome.outcome_score == pytest.approx(0.0405)
    assert outcome.factor_scores == {"catalyst_strength": 0.8, "source_confirmation": 0.6}
    assert outcome.risk_flags == ["rumor"]


def test_outcome_evaluator_uses_explicit_returns_and_manual_review_blend() -> None:
    recommendation = _recommendation("300001.SZ", {"theme_heat": 0.5})
    recommendation.manual_review_score = 75.0

    outcome = PremarketSignalOutcomeEvaluator().evaluate(
        _score_set(recommendation),
        {
            "300001.SZ": {
                "open_return": -0.01,
                "high_return": 0.03,
                "close_return": 0.02,
                "low_return": -0.04,
            }
        },
        index_return=-0.01,
        evaluation_date=date(2026, 6, 19),
    ).outcomes[0]

    formula_score = 0.35 * 0.02 + 0.35 * 0.03 - 0.25 * 0.04 + 0.20 * 0.03
    manual_normalized = 0.5
    assert outcome.manual_review_score == 75.0
    assert outcome.outcome_score == pytest.approx(0.8 * formula_score + 0.2 * manual_normalized)


def test_outcome_evaluator_accepts_new_factor_score_sets() -> None:
    score_set = PremarketFactorScoreSet(
        score_id="scores-1",
        trading_day=date(2026, 6, 18),
        generated_at=datetime(2026, 6, 18, 8, 30, tzinfo=timezone.utc),
        scores=[
            PremarketFactorScore(
                symbol="600001.SH",
                theme="robotics",
                signal_score=0.7,
                confidence=0.8,
                recommendation="candidate",
                factor_scores={"company_fit": 0.9},
                factor_contributions={"company_fit": 0.135},
                risk_flags=["crowding_high"],
                evidence_ids=["ev_1"],
                reasons=["semantic review supports company fit"],
            )
        ],
    )

    outcome_set = PremarketSignalOutcomeEvaluator().evaluate(
        score_set,
        {"600001.SH": {"open_return": 0.01, "high_return": 0.04, "close_return": 0.03, "low_return": -0.01}},
        evaluation_date=date(2026, 6, 19),
    )

    assert outcome_set.signal_date == date(2026, 6, 18)
    assert outcome_set.outcomes[0].factor_scores == {"company_fit": 0.9}
    assert outcome_set.outcomes[0].risk_flags == ["crowding_high"]


def test_factor_learning_update_adjusts_weights_penalties_and_version() -> None:
    state = PremarketFactorLearningState(
        version="pfl_20260618_000001",
        factor_weights={"catalyst_strength": 1.0, "source_confirmation": 0.5},
        risk_penalties={"rumor": 0.2, "regulatory": 0.5},
        source_adjustments={},
        theme_adjustments={},
        llm_reliability={},
        sample_count=10,
    )
    outcome_set = PremarketSignalOutcomeEvaluator().evaluate(
        _score_set(
            _recommendation(
                "600001.SH",
                {"catalyst_strength": 0.8, "source_confirmation": 0.4},
                risk_flags=["rumor"],
            ),
            _recommendation("300001.SZ", {"catalyst_strength": 0.6}, risk_flags=["regulatory"]),
        ),
        {
            "600001.SH": {"open_return": 0.01, "high_return": 0.03, "close_return": 0.02, "low_return": 0.0},
            "300001.SZ": {"open_return": -0.02, "high_return": 0.0, "close_return": -0.05, "low_return": -0.08},
        },
        evaluation_date=date(2026, 6, 19),
    )

    update = PremarketFactorLearningAgent(learning_rate=0.5, max_weight_step=0.01).update(state, outcome_set)

    assert update.previous_version == "pfl_20260618_000001"
    assert update.next_state.version == "pfl_20260619_000012"
    assert update.next_state.sample_count == 12
    assert update.outcome_count == 2
    assert update.weight_deltas["catalyst_strength"] == pytest.approx(-0.0014)
    assert update.weight_deltas["source_confirmation"] == pytest.approx(0.0043)
    assert update.next_state.factor_weights["catalyst_strength"] == pytest.approx(0.9986)
    assert update.next_state.factor_weights["source_confirmation"] == pytest.approx(0.5043)
    assert update.risk_penalty_deltas["rumor"] == pytest.approx(-0.005375)
    assert update.risk_penalty_deltas["regulatory"] == pytest.approx(0.01)
    assert update.next_state.risk_penalties["rumor"] == pytest.approx(0.194625)
    assert update.next_state.risk_penalties["regulatory"] == pytest.approx(0.51)


def test_factor_learning_store_saves_versions_and_rolls_back_current(tmp_path) -> None:
    store = PremarketFactorLearningStore(tmp_path / "premarket_learning")
    first = PremarketFactorLearningState(
        version="pfl_20260618_000001",
        factor_weights={"catalyst_strength": 1.0},
        risk_penalties={},
        source_adjustments={},
        theme_adjustments={},
        llm_reliability={},
        sample_count=1,
    )
    second = PremarketFactorLearningState(
        version="pfl_20260619_000002",
        factor_weights={"catalyst_strength": 1.1},
        risk_penalties={"rumor": 0.2},
        source_adjustments={"official": 0.1},
        theme_adjustments={"robotics": 0.05},
        llm_reliability={"news_reasoning": 0.9},
        sample_count=2,
    )

    store.save_version(first)
    store.save_version(second)

    assert store.list_versions() == ["pfl_20260618_000001", "pfl_20260619_000002"]
    assert store.get_current() == second
    assert store.rollback_current("pfl_20260618_000001") == first
    assert store.get_current() == first
