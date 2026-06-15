from __future__ import annotations

from trading_agent_system.core.strategy_learning.store import LearningStateVersion
from trading_agent_system.core.strategy_learning.updater import (
    LearningOutcome,
    LearningUpdateConfig,
    LearningUpdater,
)


def _state() -> LearningStateVersion:
    return LearningStateVersion(
        version_id="one_pick_two_day_v1-v000001",
        version=1,
        scoring_weights={"news_strength": 0.4, "theme_heat": 0.3},
        risk_penalties={"high_open_chase": 0.1},
        confidence_penalties={},
    )


def test_profitable_outcome_increases_positive_contributing_weights():
    updater = LearningUpdater(LearningUpdateConfig(learning_rate=0.5, max_weight_step=0.1))

    update = updater.apply(
        _state(),
        LearningOutcome(
            pnl_pct=0.04,
            max_favorable_excursion_pct=0.06,
            max_adverse_excursion_pct=-0.01,
            hit_take_profit=True,
            selected_feature_scores={"news_strength": 0.8, "theme_heat": 0.5},
        ),
    )

    assert update.updated_scoring_weights["news_strength"] > 0.4
    assert update.updated_scoring_weights["theme_heat"] > 0.3
    assert update.weight_deltas["news_strength"] > update.weight_deltas["theme_heat"]


def test_losing_outcome_decreases_positive_contributing_weights():
    updater = LearningUpdater(LearningUpdateConfig(learning_rate=0.5, max_weight_step=0.1))

    update = updater.apply(
        _state(),
        LearningOutcome(
            pnl_pct=-0.05,
            max_favorable_excursion_pct=0.01,
            max_adverse_excursion_pct=-0.06,
            hit_stop_loss=True,
            selected_feature_scores={"news_strength": 0.8},
        ),
    )

    assert update.updated_scoring_weights["news_strength"] < 0.4
    assert update.weight_deltas["news_strength"] < 0


def test_high_open_chase_losing_tag_increases_risk_penalty():
    updater = LearningUpdater(LearningUpdateConfig(learning_rate=0.5, max_weight_step=0.1))

    update = updater.apply(
        _state(),
        LearningOutcome(
            pnl_pct=-0.04,
            max_favorable_excursion_pct=0,
            max_adverse_excursion_pct=-0.05,
            selected_feature_scores={"news_strength": 0.5},
            tags=["high_open_chase"],
        ),
    )

    assert update.updated_risk_penalties["high_open_chase"] > 0.1
    assert update.risk_penalty_deltas["high_open_chase"] > 0


def test_single_weight_update_is_capped_by_max_step():
    updater = LearningUpdater(LearningUpdateConfig(learning_rate=10, max_weight_step=0.03))

    update = updater.apply(
        _state(),
        LearningOutcome(
            pnl_pct=0.2,
            max_favorable_excursion_pct=0.2,
            max_adverse_excursion_pct=0,
            selected_feature_scores={"news_strength": 1.0},
        ),
    )

    assert update.weight_deltas["news_strength"] == 0.03
    assert update.updated_scoring_weights["news_strength"] == 0.43


def test_weight_updates_are_clamped_to_min_and_max_bounds():
    updater = LearningUpdater(
        LearningUpdateConfig(
            learning_rate=10,
            max_weight_step=0.5,
            min_weight=0.0,
            max_weight=0.42,
        )
    )

    update = updater.apply(
        _state(),
        LearningOutcome(
            pnl_pct=0.2,
            max_favorable_excursion_pct=0.2,
            max_adverse_excursion_pct=0,
            selected_feature_scores={"news_strength": 1.0},
        ),
    )

    assert update.updated_scoring_weights["news_strength"] == 0.42
    assert update.weight_deltas["news_strength"] == 0.02
