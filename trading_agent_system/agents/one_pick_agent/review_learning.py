from __future__ import annotations

from .schemas import (
    LearningState,
    LearningUpdate,
    OnePickExecutionRecord,
    OnePickOutcome,
    OnePickSelection,
)
from trading_agent_system.schemas import MarketBar


class ReviewLearningAgent:
    def __init__(
        self,
        *,
        learning_rate: float = 0.10,
        max_weight_step: float = 0.03,
        max_abs_weight: float = 2.0,
    ) -> None:
        self.learning_rate = learning_rate
        self.max_weight_step = max_weight_step
        self.max_abs_weight = max_abs_weight

    def review(
        self,
        *,
        selection: OnePickSelection,
        entry_execution: OnePickExecutionRecord,
        exit_execution: OnePickExecutionRecord,
        market_bars: list[MarketBar],
        current_state: LearningState,
    ) -> tuple[OnePickOutcome, LearningUpdate]:
        if entry_execution.side != "buy" or exit_execution.side != "sell":
            raise ValueError("review requires buy entry execution and sell exit execution")
        entry_price = entry_execution.price
        exit_price = exit_execution.price
        highs = [bar.high for bar in market_bars] or [max(entry_price, exit_price)]
        lows = [bar.low for bar in market_bars] or [min(entry_price, exit_price)]
        mfe = (max(highs) - entry_price) / entry_price
        mae = (min(lows) - entry_price) / entry_price
        pnl_pct = (exit_price - entry_price) / entry_price
        hit_take_profit = exit_price >= entry_price * 1.039999
        hit_stop_loss = exit_price <= entry_price * 0.980001

        outcome = OnePickOutcome(
            symbol=selection.selected_symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=min(entry_execution.quantity, exit_execution.quantity),
            pnl_pct=round(pnl_pct, 6),
            max_favorable_excursion_pct=round(mfe, 6),
            max_adverse_excursion_pct=round(mae, 6),
            hit_take_profit=hit_take_profit,
            hit_stop_loss=hit_stop_loss,
            direction_correct=pnl_pct > 0,
            selected_feature_scores=selection.feature_scores,
            tag_performance={tag: round(pnl_pct, 6) for tag in selection.strategy_tags},
        )
        update = self._learning_update(selection, outcome, current_state)
        return outcome, update

    def review_and_persist(
        self,
        *,
        selection: OnePickSelection,
        entry_execution: OnePickExecutionRecord,
        exit_execution: OnePickExecutionRecord,
        market_bars: list[MarketBar],
        learning_store,
    ):
        current_version = learning_store.get_current()
        current_state = _state_from_store_version(selection, current_version)
        outcome, update = self.review(
            selection=selection,
            entry_execution=entry_execution,
            exit_execution=exit_execution,
            market_bars=market_bars,
            current_state=current_state,
        )
        next_version = learning_store.create_next_version(
            scoring_weights=update.next_state.feature_weights,
            risk_penalties=update.next_state.risk_penalties,
            metadata={
                **update.next_state.metadata,
                "outcome_id": outcome.outcome_id,
                "update_id": update.update_id,
                "tag_adjustments": update.next_state.tag_adjustments,
                "weight_deltas": update.weight_deltas,
                "risk_penalty_deltas": update.risk_penalty_deltas,
            },
        )
        return outcome, update, next_version

    def _learning_update(
        self,
        selection: OnePickSelection,
        outcome: OnePickOutcome,
        current_state: LearningState,
    ) -> LearningUpdate:
        outcome_score = (
            outcome.pnl_pct
            + 0.5 * max(0.0, outcome.max_favorable_excursion_pct)
            - 0.7 * abs(min(0.0, outcome.max_adverse_excursion_pct))
            + (0.02 if outcome.hit_take_profit else 0.0)
            - (0.03 if outcome.hit_stop_loss else 0.0)
        )
        weight_deltas: dict[str, float] = {}
        next_weights = dict(current_state.feature_weights)
        for feature, feature_score in selection.feature_scores.items():
            raw_delta = self.learning_rate * outcome_score * float(feature_score)
            delta = _clamp(raw_delta, -self.max_weight_step, self.max_weight_step)
            weight_deltas[feature] = round(delta, 6)
            next_weights[feature] = round(
                _clamp(next_weights.get(feature, 0.0) + delta, -self.max_abs_weight, self.max_abs_weight),
                6,
            )

        risk_penalty_deltas: dict[str, float] = {}
        next_penalties = dict(current_state.risk_penalties)
        for risk_flag in selection.risk_flags:
            if outcome.pnl_pct < 0 or risk_flag == "high_open_chase":
                delta = min(self.max_weight_step, abs(outcome_score) * self.learning_rate + 0.005)
                risk_penalty_deltas[risk_flag] = round(delta, 6)
                next_penalties[risk_flag] = round(next_penalties.get(risk_flag, 0.0) + delta, 6)

        tag_adjustment_deltas: dict[str, float] = {}
        next_tags = dict(current_state.tag_adjustments)
        for tag in selection.strategy_tags:
            delta = _clamp(self.learning_rate * outcome_score, -self.max_weight_step, self.max_weight_step)
            tag_adjustment_deltas[tag] = round(delta, 6)
            next_tags[tag] = round(next_tags.get(tag, 0.0) + delta, 6)

        next_state = LearningState(
            strategy_id=current_state.strategy_id,
            version=f"{current_state.version}+1",
            feature_weights=next_weights,
            risk_penalties=next_penalties,
            tag_adjustments=next_tags,
            metadata={"last_outcome_id": outcome.outcome_id},
        )
        return LearningUpdate(
            strategy_id=current_state.strategy_id,
            previous_version=current_state.version,
            next_state=next_state,
            outcome_id=outcome.outcome_id,
            weight_deltas=weight_deltas,
            risk_penalty_deltas=risk_penalty_deltas,
            tag_adjustment_deltas=tag_adjustment_deltas,
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _state_from_store_version(selection: OnePickSelection, version) -> LearningState:
    if version is None:
        return LearningState(strategy_id="one_pick_two_day_v1", version="initial")
    return LearningState(
        strategy_id=getattr(version, "strategy_id", "one_pick_two_day_v1"),
        version=getattr(version, "version_id", str(getattr(version, "version", "current"))),
        feature_weights=dict(getattr(version, "scoring_weights", {})),
        risk_penalties=dict(getattr(version, "risk_penalties", {})),
        tag_adjustments=dict(getattr(version, "metadata", {}).get("tag_adjustments", {})),
        metadata={"selected_symbol": selection.selected_symbol},
    )
