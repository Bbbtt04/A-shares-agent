from __future__ import annotations

from pydantic import Field

from trading_agent_system.schemas import StrictBaseModel

from .store import LearningStateVersion


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _clean_float(value: float) -> float:
    return round(value, 10)


class LearningUpdateConfig(StrictBaseModel):
    learning_rate: float = Field(default=0.25, ge=0)
    max_weight_step: float = Field(default=0.05, ge=0)
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_penalty: float = 1.0


class LearningOutcome(StrictBaseModel):
    pnl_pct: float
    max_favorable_excursion_pct: float = 0
    max_adverse_excursion_pct: float = 0
    hit_take_profit: bool = False
    hit_stop_loss: bool = False
    selected_feature_scores: dict[str, float] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class LearningUpdate(StrictBaseModel):
    outcome_score: float
    weight_deltas: dict[str, float]
    risk_penalty_deltas: dict[str, float]
    confidence_penalty_deltas: dict[str, float] = Field(default_factory=dict)
    updated_scoring_weights: dict[str, float]
    updated_risk_penalties: dict[str, float]
    updated_confidence_penalties: dict[str, float]


class LearningUpdater:
    def __init__(self, config: LearningUpdateConfig | None = None) -> None:
        self.config = config or LearningUpdateConfig()

    def apply(self, state: LearningStateVersion, outcome: LearningOutcome) -> LearningUpdate:
        outcome_score = self._outcome_score(outcome)
        weights = dict(state.scoring_weights)
        weight_deltas: dict[str, float] = {}

        for feature, score in outcome.selected_feature_scores.items():
            current = weights.get(feature, 0.0)
            normalized_score = _clamp(float(score), -1.0, 1.0)
            raw_delta = self.config.learning_rate * outcome_score * normalized_score
            capped_delta = _clamp(raw_delta, -self.config.max_weight_step, self.config.max_weight_step)
            updated = _clamp(current + capped_delta, self.config.min_weight, self.config.max_weight)
            actual_delta = _clean_float(updated - current)
            weights[feature] = _clean_float(current + actual_delta)
            weight_deltas[feature] = actual_delta

        risk_penalties = dict(state.risk_penalties)
        risk_penalty_deltas = self._risk_penalty_deltas(outcome, outcome_score, risk_penalties)

        return LearningUpdate(
            outcome_score=_clean_float(outcome_score),
            weight_deltas=weight_deltas,
            risk_penalty_deltas=risk_penalty_deltas,
            updated_scoring_weights=weights,
            updated_risk_penalties=risk_penalties,
            updated_confidence_penalties=dict(state.confidence_penalties),
        )

    def _outcome_score(self, outcome: LearningOutcome) -> float:
        return (
            outcome.pnl_pct
            + 0.5 * outcome.max_favorable_excursion_pct
            - 0.7 * abs(outcome.max_adverse_excursion_pct)
            + (0.02 if outcome.hit_take_profit else 0)
            - (0.03 if outcome.hit_stop_loss else 0)
        )

    def _risk_penalty_deltas(
        self,
        outcome: LearningOutcome,
        outcome_score: float,
        risk_penalties: dict[str, float],
    ) -> dict[str, float]:
        deltas: dict[str, float] = {}
        if outcome_score >= 0:
            return deltas

        if "high_open_chase" in outcome.tags:
            current = risk_penalties.get("high_open_chase", 0.0)
            raw_delta = self.config.learning_rate * abs(outcome_score)
            capped_delta = _clamp(raw_delta, 0.0, self.config.max_weight_step)
            updated = _clamp(current + capped_delta, 0.0, self.config.max_penalty)
            actual_delta = _clean_float(updated - current)
            risk_penalties["high_open_chase"] = _clean_float(current + actual_delta)
            deltas["high_open_chase"] = actual_delta
        return deltas
