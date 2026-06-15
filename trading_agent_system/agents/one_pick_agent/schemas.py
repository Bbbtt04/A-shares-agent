from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from trading_agent_system.schemas import StrictBaseModel, make_id, utc_now


class OnePickSelectionConfig(StrictBaseModel):
    force_pick_one: bool = True
    min_confidence_to_buy: float = Field(default=0.60, ge=0, le=1)
    min_risk_reward_ratio: float = Field(default=1.80, gt=0)
    max_candidates: int = Field(default=20, gt=0)


class OnePickCandidate(StrictBaseModel):
    candidate_id: str = Field(default_factory=lambda: make_id("onepick_candidate"))
    symbol: str
    name: str | None = None
    feature_scores: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    strategy_tags: list[str] = Field(default_factory=list)
    source_rank: int = Field(default=99, gt=0)
    confidence: float = Field(ge=0, le=1)
    expected_upside_pct: float = Field(gt=0)
    expected_downside_pct: float = Field(gt=0)
    risk_reward_ratio: float = Field(gt=0)

    @field_validator("symbol")
    @classmethod
    def require_symbol(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("symbol is required")
        return value.strip()


class OnePickSelection(StrictBaseModel):
    selection_id: str = Field(default_factory=lambda: make_id("onepick_selection"))
    selected_symbol: str
    selected_name: str | None = None
    score: float
    confidence: float = Field(ge=0, le=1)
    risk_reward_ratio: float = Field(gt=0)
    threshold_passed: bool
    threshold_reasons: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    strategy_tags: list[str] = Field(default_factory=list)

    @field_validator("selected_symbol")
    @classmethod
    def require_selected_symbol(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selected_symbol is required")
        return value.strip()


class OnePickTradePlan(StrictBaseModel):
    plan_id: str = Field(default_factory=lambda: make_id("onepick_plan"))
    symbol: str
    name: str | None = None
    side: Literal["buy"] = "buy"
    quantity: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    expected_upside_pct: float = Field(gt=0)
    expected_downside_pct: float = Field(gt=0)
    risk_reward_ratio: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss_price: float = Field(gt=0)
    take_profit_price: float = Field(gt=0)
    buy_reasons: list[str]
    risk_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    strategy_tags: list[str] = Field(default_factory=list)
    threshold_passed: bool = True

    @field_validator("buy_reasons")
    @classmethod
    def require_buy_reason(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("trade plan must have at least one buy reason")
        return value


class OnePickExecutionRecord(StrictBaseModel):
    execution_id: str = Field(default_factory=lambda: make_id("onepick_exec"))
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    intent_id: str
    order_id: str | None = None
    fill_id: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnePickExitPlan(StrictBaseModel):
    exit_plan_id: str = Field(default_factory=lambda: make_id("onepick_exit"))
    symbol: str
    side: Literal["sell"] = "sell"
    quantity: int = Field(gt=0)
    exit_price: float = Field(gt=0)
    reason: Literal["take_profit", "stop_loss", "time_exit"]
    remaining_quantity_after_exit: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)


class OnePickOutcome(StrictBaseModel):
    outcome_id: str = Field(default_factory=lambda: make_id("onepick_outcome"))
    symbol: str
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    pnl_pct: float
    max_favorable_excursion_pct: float
    max_adverse_excursion_pct: float
    hit_take_profit: bool
    hit_stop_loss: bool
    direction_correct: bool
    selected_feature_scores: dict[str, float] = Field(default_factory=dict)
    tag_performance: dict[str, float] = Field(default_factory=dict)


class LearningState(StrictBaseModel):
    strategy_id: str
    version: str
    feature_weights: dict[str, float] = Field(default_factory=dict)
    risk_penalties: dict[str, float] = Field(default_factory=dict)
    tag_adjustments: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningUpdate(StrictBaseModel):
    update_id: str = Field(default_factory=lambda: make_id("onepick_learning_update"))
    strategy_id: str
    previous_version: str
    next_state: LearningState
    outcome_id: str
    weight_deltas: dict[str, float] = Field(default_factory=dict)
    risk_penalty_deltas: dict[str, float] = Field(default_factory=dict)
    tag_adjustment_deltas: dict[str, float] = Field(default_factory=dict)


class EffectiveOnePickStrategy(StrictBaseModel):
    strategy_id: str
    strategy_version: str
    selection: OnePickSelectionConfig = Field(default_factory=OnePickSelectionConfig)
    scoring_weights: dict[str, float] = Field(default_factory=dict)
    risk_penalties: dict[str, float] = Field(default_factory=dict)
    blocked_risk_flags: list[str] = Field(default_factory=list)
    tag_adjustments: dict[str, float] = Field(default_factory=dict)
    entry_rule: dict[str, Any] = Field(default_factory=dict)
    exit_rule: dict[str, Any] = Field(default_factory=dict)
    learning: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_strategy_identity(self) -> "EffectiveOnePickStrategy":
        if not self.strategy_id.strip():
            raise ValueError("strategy_id is required")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version is required")
        return self


class OnePickPremarketResult(StrictBaseModel):
    strategy: EffectiveOnePickStrategy
    candidates: list[OnePickCandidate]
    selection: OnePickSelection
    trade_plan: OnePickTradePlan
    buy_submission: dict[str, Any] | None = None
