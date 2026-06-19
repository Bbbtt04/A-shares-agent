from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import Field

from .factor_scoring import PremarketFactorScore, PremarketFactorScoreSet, Recommendation
from .schemas import StrictModel


class PremarketStrategyRecommendation(StrictModel):
    symbol: str
    action: Recommendation
    priority: int
    confidence: float = Field(ge=0, le=1)
    signal_score: float = Field(ge=0, le=1)
    reason: str
    entry_conditions: list[str] = Field(default_factory=list)
    avoid_conditions: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    handoff_payload_version: Literal["premarket_strategy_handoff.v1"] = "premarket_strategy_handoff.v1"


class PremarketStrategyRecommendationSet(StrictModel):
    recommendation_id: str
    trading_day: date
    generated_at: datetime
    recommendations: list[PremarketStrategyRecommendation] = Field(default_factory=list)


class PremarketStrategyRecommendationAgent:
    def __init__(self, generated_at: datetime | None = None) -> None:
        self.generated_at = generated_at

    def build(self, score_set: PremarketFactorScoreSet) -> PremarketStrategyRecommendationSet:
        generated_at = self.generated_at or datetime.now(timezone.utc)
        ranked_scores = sorted(score_set.scores, key=lambda item: item.signal_score, reverse=True)
        return PremarketStrategyRecommendationSet(
            recommendation_id=f"premarket-strategy-recommendations-{score_set.trading_day.isoformat()}",
            trading_day=score_set.trading_day,
            generated_at=generated_at,
            recommendations=[
                self._recommendation(score, priority=index + 1) for index, score in enumerate(ranked_scores)
            ],
        )

    def _recommendation(self, score: PremarketFactorScore, priority: int) -> PremarketStrategyRecommendation:
        return PremarketStrategyRecommendation(
            symbol=score.symbol,
            action=score.recommendation,
            priority=priority,
            confidence=score.confidence,
            signal_score=score.signal_score,
            reason=self._reason(score),
            entry_conditions=self._entry_conditions(score),
            avoid_conditions=self._avoid_conditions(score),
            risk_notes=score.risk_flags,
            evidence_ids=score.evidence_ids,
        )

    def _reason(self, score: PremarketFactorScore) -> str:
        return f"{score.theme} factor score {score.signal_score:.3f}: {score.reasons[0] if score.reasons else 'no dominant factor'}"

    def _entry_conditions(self, score: PremarketFactorScore) -> list[str]:
        return [
            f"{score.symbol} remains aligned with {score.theme}",
            "Opening confirmation supports the premarket factor signal",
            "No new avoid condition appears before handoff",
        ]

    def _avoid_conditions(self, score: PremarketFactorScore) -> list[str]:
        conditions = [
            "Semantic review or fresh evidence rejects the catalyst",
            "Opening confirmation fails or reverses the theme signal",
        ]
        conditions.extend(f"Risk flag persists: {flag}" for flag in score.risk_flags)
        return conditions
