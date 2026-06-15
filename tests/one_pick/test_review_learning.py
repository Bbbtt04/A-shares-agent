from __future__ import annotations

from trading_agent_system.agents.one_pick_agent.review_learning import ReviewLearningAgent
from trading_agent_system.agents.one_pick_agent.schemas import (
    LearningState,
    OnePickExecutionRecord,
    OnePickSelection,
)
from trading_agent_system.core.strategy_learning import LearningStateStore
from trading_agent_system.schemas import MarketBar
from datetime import datetime, timezone


def _selection() -> OnePickSelection:
    return OnePickSelection(
        selected_symbol="688981.SH",
        selected_name="SMIC",
        score=0.7,
        confidence=0.7,
        risk_reward_ratio=2.0,
        threshold_passed=True,
        reasons=["official catalyst"],
        evidence_ids=["evt_1"],
        risk_flags=[],
        feature_scores={"catalyst_strength": 0.8, "source_quality": 0.6},
        strategy_tags=["semiconductor"],
    )


def _execution(side: str, price: float) -> OnePickExecutionRecord:
    return OnePickExecutionRecord(
        symbol="688981.SH",
        side=side,
        quantity=100,
        price=price,
        intent_id=f"intent_{side}",
        order_id=f"order_{side}",
        fill_id=f"fill_{side}",
    )


def _bar(high: float, low: float, close: float) -> MarketBar:
    return MarketBar(
        symbol="688981.SH",
        ts=datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc),
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def test_review_learning_computes_outcome_and_capped_positive_update():
    agent = ReviewLearningAgent(learning_rate=0.5, max_weight_step=0.02)

    outcome, update = agent.review(
        selection=_selection(),
        entry_execution=_execution("buy", 100.0),
        exit_execution=_execution("sell", 104.0),
        market_bars=[_bar(high=105.0, low=99.0, close=104.0)],
        current_state=LearningState(strategy_id="one_pick_two_day_v1", version="v1"),
    )

    assert outcome.pnl_pct == 0.04
    assert outcome.hit_take_profit is True
    assert update.weight_deltas["catalyst_strength"] == 0.02
    assert update.next_state.feature_weights["catalyst_strength"] == 0.02


def test_review_learning_decreases_weights_for_losing_outcome_and_adds_risk_penalty():
    selection = _selection().model_copy(update={"risk_flags": ["high_open_chase"]})
    agent = ReviewLearningAgent(learning_rate=0.5, max_weight_step=0.02)

    outcome, update = agent.review(
        selection=selection,
        entry_execution=_execution("buy", 100.0),
        exit_execution=_execution("sell", 97.0),
        market_bars=[_bar(high=101.0, low=97.0, close=97.0)],
        current_state=LearningState(strategy_id="one_pick_two_day_v1", version="v1"),
    )

    assert outcome.hit_stop_loss is True
    assert update.weight_deltas["catalyst_strength"] == -0.02
    assert update.risk_penalty_deltas["high_open_chase"] > 0


def test_review_learning_can_persist_next_m15_learning_version(tmp_path):
    store = LearningStateStore(tmp_path / "learning")
    first = store.create_next_version(scoring_weights={"catalyst_strength": 0.1})
    agent = ReviewLearningAgent(learning_rate=0.5, max_weight_step=0.02)

    outcome, update, version = agent.review_and_persist(
        selection=_selection(),
        entry_execution=_execution("buy", 100.0),
        exit_execution=_execution("sell", 104.0),
        market_bars=[_bar(high=105.0, low=99.0, close=104.0)],
        learning_store=store,
    )

    assert outcome.pnl_pct == 0.04
    assert update.previous_version == first.version_id
    assert version.previous_version_id == first.version_id
    assert store.get_current().version_id == version.version_id
    assert version.scoring_weights["catalyst_strength"] == update.next_state.feature_weights["catalyst_strength"]
