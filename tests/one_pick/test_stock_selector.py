from __future__ import annotations

from trading_agent_system.agents.one_pick_agent.schemas import (
    EffectiveOnePickStrategy,
    OnePickCandidate,
    OnePickSelectionConfig,
)
from trading_agent_system.agents.one_pick_agent.stock_selector import StockSelector


def _strategy(min_confidence: float = 0.6, min_rr: float = 1.8) -> EffectiveOnePickStrategy:
    return EffectiveOnePickStrategy(
        strategy_id="one_pick_two_day_v1",
        strategy_version="1.0.0",
        selection=OnePickSelectionConfig(
            force_pick_one=True,
            min_confidence_to_buy=min_confidence,
            min_risk_reward_ratio=min_rr,
            max_candidates=20,
        ),
        scoring_weights={"catalyst_strength": 0.7, "source_quality": 0.3},
        risk_penalties={"rumor": 0.4},
        blocked_risk_flags=["delisting_risk"],
        tag_adjustments={"semiconductor": 0.1},
        entry_rule={"default_quantity": 100},
        exit_rule={"take_profit_pct": 0.04, "stop_loss_pct": 0.02},
        learning={"learning_rate": 0.1},
    )


def _candidate(symbol: str, catalyst: float, source: float, *, risk_flags: list[str] | None = None) -> OnePickCandidate:
    return OnePickCandidate(
        symbol=symbol,
        name=symbol,
        feature_scores={"catalyst_strength": catalyst, "source_quality": source},
        evidence_ids=[f"evt_{symbol}"],
        risk_flags=risk_flags or [],
        strategy_tags=["semiconductor"] if symbol.startswith("688") else [],
        source_rank=1,
        confidence=0.65,
        expected_upside_pct=0.04,
        expected_downside_pct=0.02,
        risk_reward_ratio=2.0,
    )


def test_selector_returns_exactly_one_top_ranked_pick():
    selection = StockSelector().select(
        [_candidate("000001.SZ", 0.7, 0.5), _candidate("688981.SH", 0.7, 0.7)],
        _strategy(),
    )

    assert selection.selected_symbol == "688981.SH"
    assert selection.threshold_passed is True
    assert selection.score > 0


def test_selector_forces_one_pick_but_marks_threshold_failure():
    weak = _candidate("000001.SZ", 0.2, 0.2)
    weak = weak.model_copy(update={"confidence": 0.45, "risk_reward_ratio": 1.2})

    selection = StockSelector().select([weak], _strategy())

    assert selection.selected_symbol == "000001.SZ"
    assert selection.threshold_passed is False
    assert "confidence_below_minimum" in selection.threshold_reasons
    assert "risk_reward_below_minimum" in selection.threshold_reasons
