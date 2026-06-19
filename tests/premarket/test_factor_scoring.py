from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from trading_agent_system.agents.premarket_agent.factor_scoring import PremarketFactorScorer
from trading_agent_system.agents.premarket_agent.schemas import Actionability, Bias, Importance, PreMarketEvent, SourceRank
from trading_agent_system.agents.premarket_agent.semantic_review import PremarketSemanticReview
from trading_agent_system.agents.premarket_agent.strategy_recommendation import (
    PremarketStrategyRecommendationAgent,
)


def _event(
    *,
    event_id: str,
    symbol: str,
    theme: str = "AI",
    source_rank: SourceRank = SourceRank.OFFICIAL,
    importance: Importance = Importance.A,
    confidence: float = 0.8,
    actionability: Actionability = Actionability.CANDIDATE,
    risk_flags: list[str] | None = None,
    first_seen_at: datetime | None = None,
    evidence: list[dict[str, str]] | None = None,
) -> PreMarketEvent:
    now = datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc)
    return PreMarketEvent(
        event_id=event_id,
        source_ids=[f"src-{event_id}"],
        source_rank=source_rank,
        title=f"{symbol} catalyst",
        summary="Confirmed catalyst with premarket relevance.",
        published_at=now,
        first_seen_at=first_seen_at or now,
        last_updated_at=now,
        symbols=[symbol],
        companies=[symbol],
        event_type="major_contract",
        related_themes=[theme],
        importance=importance,
        bias=Bias.BULLISH,
        confidence=confidence,
        actionability=actionability,
        evidence=evidence or [{"id": f"ev-{event_id}", "title": "official filing"}],
        risk_flags=risk_flags or [],
    )


def test_factor_scorer_calculates_weighted_score_and_contributions() -> None:
    scorer = PremarketFactorScorer(generated_at=datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc))

    score_set = scorer.score(
        [
            _event(event_id="e1", symbol="600001", evidence=[{"id": "doc-1"}, {"id": "doc-2"}]),
            _event(event_id="e2", symbol="600002", theme="AI", source_rank=SourceRank.AUTHORIZED_NEWS),
        ],
        trading_day=date(2026, 6, 19),
    )

    score = next(item for item in score_set.scores if item.symbol == "600001")

    assert score_set.score_id == "premarket-factor-scores-2026-06-19"
    assert score.theme == "AI"
    assert score.recommendation == "candidate"
    assert score.factor_scores["source_quality"] == pytest.approx(0.95)
    assert score.factor_scores["catalyst_strength"] == pytest.approx(0.8)
    assert score.factor_scores["theme_heat"] == pytest.approx(1.0)
    assert score.factor_scores["crowding_risk"] == pytest.approx(0.0)
    assert score.factor_contributions["source_quality"] == pytest.approx(0.1425)
    assert score.signal_score == pytest.approx(0.655)
    assert score.confidence == pytest.approx(0.8)
    assert score.evidence_ids == ["e1", "doc-1", "doc-2"]
    assert any("source_quality" in reason for reason in score.reasons)


def test_learning_state_adjusts_weights_and_theme_source_influence() -> None:
    scorer = PremarketFactorScorer(generated_at=datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc))
    event = _event(
        event_id="e1",
        symbol="600001",
        theme="Robotics",
        source_rank=SourceRank.AUTHORIZED_NEWS,
        importance=Importance.B,
        confidence=0.6,
    )

    baseline = scorer.score([event], trading_day=date(2026, 6, 19)).scores[0]
    adjusted = scorer.score(
        [event],
        learning_state={
            "factor_weights": {"catalyst_strength": 0.2, "hype_risk": -2.0},
            "theme_adjustments": {"Robotics": 0.1},
            "source_adjustments": {"authorized_news": 0.1},
        },
        trading_day=date(2026, 6, 19),
    ).scores[0]

    assert adjusted.factor_contributions["catalyst_strength"] > baseline.factor_contributions["catalyst_strength"]
    assert adjusted.factor_scores["theme_heat"] > baseline.factor_scores["theme_heat"]
    assert adjusted.factor_scores["source_quality"] > baseline.factor_scores["source_quality"]
    assert adjusted.signal_score > baseline.signal_score


def test_semantic_reject_overrides_numeric_recommendation() -> None:
    scorer = PremarketFactorScorer(generated_at=datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc))

    score = scorer.score(
        [_event(event_id="e1", symbol="600001")],
        semantic_reviews={"600001": {"semantic_verdict": "reject", "reasons": ["company mismatch"]}},
        trading_day=date(2026, 6, 19),
    ).scores[0]

    assert score.signal_score >= 0.65
    assert score.recommendation == "reject"
    assert "semantic reject: company mismatch" in score.reasons


def test_semantic_review_scores_override_matching_factor_values() -> None:
    scorer = PremarketFactorScorer(generated_at=datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc))
    event = _event(event_id="e1", symbol="600001")
    review = PremarketSemanticReview(
        symbol="600001",
        theme="AI application",
        catalyst_relevance=0.2,
        company_fit=0.1,
        event_novelty=0.3,
        evidence_consistency=0.4,
        source_reliability=0.5,
        crowding_risk=0.9,
        stale_news_risk=0.8,
        hype_risk=0.7,
        semantic_verdict="watch",
        positive_reasons=["weak but related"],
        negative_reasons=["crowded theme"],
        evidence_ids=["llm-ev"],
    )

    score = scorer.score([event], semantic_reviews=[review], trading_day=date(2026, 6, 19)).scores[0]

    assert score.theme == "AI application"
    assert score.factor_scores["company_fit"] == pytest.approx(0.1)
    assert score.factor_scores["evidence_consistency"] == pytest.approx(0.4)
    assert score.factor_scores["event_novelty"] == pytest.approx(0.3)
    assert score.factor_scores["source_quality"] == pytest.approx(0.5)
    assert score.factor_scores["crowding_risk"] == pytest.approx(0.9)
    assert score.evidence_ids == ["e1", "ev-e1", "llm-ev"]
    assert any("semantic review" in reason for reason in score.reasons)


def test_strategy_recommendation_ranks_scores_and_builds_handoff_payload() -> None:
    scorer = PremarketFactorScorer(generated_at=datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc))
    score_set = scorer.score(
        [
            _event(event_id="low", symbol="600002", importance=Importance.C, confidence=0.45),
            _event(event_id="high", symbol="600001", importance=Importance.S, confidence=0.9),
        ],
        trading_day=date(2026, 6, 19),
    )

    recommendation_set = PremarketStrategyRecommendationAgent(
        generated_at=datetime(2026, 6, 19, 8, 35, tzinfo=timezone.utc)
    ).build(score_set)

    assert recommendation_set.recommendation_id == "premarket-strategy-recommendations-2026-06-19"
    assert [item.symbol for item in recommendation_set.recommendations] == ["600001", "600002"]
    top = recommendation_set.recommendations[0]
    assert top.action == "candidate"
    assert top.priority == 1
    assert top.handoff_payload_version == "premarket_strategy_handoff.v1"
    assert top.entry_conditions
    assert top.avoid_conditions
    assert top.risk_notes == []
    assert top.evidence_ids == ["high", "ev-high"]
    assert "buy" not in top.action
    assert "sell" not in top.action
