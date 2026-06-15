from __future__ import annotations

from trading_agent_system.agents.one_pick_agent.schemas import (
    EffectiveOnePickStrategy,
    OnePickSelection,
    OnePickSelectionConfig,
)
from trading_agent_system.agents.one_pick_agent.trade_plan import TradePlanAgent
from trading_agent_system.schemas import TradeIntent


def _strategy() -> EffectiveOnePickStrategy:
    return EffectiveOnePickStrategy(
        strategy_id="one_pick_two_day_v1",
        strategy_version="1.0.0",
        selection=OnePickSelectionConfig(),
        scoring_weights={},
        risk_penalties={},
        blocked_risk_flags=[],
        tag_adjustments={},
        entry_rule={"default_quantity": 200},
        exit_rule={"take_profit_pct": 0.04, "stop_loss_pct": 0.02},
        learning={},
    )


def _selection() -> OnePickSelection:
    return OnePickSelection(
        selected_symbol="688981.SH",
        selected_name="SMIC",
        score=0.72,
        confidence=0.68,
        risk_reward_ratio=2.0,
        threshold_passed=True,
        reasons=["official catalyst"],
        evidence_ids=["evt_1"],
        risk_flags=["valuation"],
        feature_scores={"catalyst_strength": 0.8},
    )


def test_trade_plan_is_deterministic_and_does_not_call_llm_gateway():
    class ExplodingLLM:
        def complete(self, *args, **kwargs):
            raise AssertionError("LLM must not be called by deterministic planner")

    plan = TradePlanAgent(llm_gateway=ExplodingLLM()).create_plan(_selection(), _strategy(), last_price=100.0)

    assert plan.symbol == "688981.SH"
    assert plan.quantity == 200
    assert plan.entry_price == 100.0
    assert plan.stop_loss_price == 98.0
    assert plan.take_profit_price == 104.0
    assert plan.buy_reasons == ["official catalyst"]
    assert plan.risk_reasons == ["valuation"]


def test_trade_plan_converts_to_trade_intent_for_injected_risk_gateway():
    plan = TradePlanAgent().create_plan(_selection(), _strategy(), last_price=100.0)

    intent = TradePlanAgent().to_trade_intent(plan, _strategy())

    assert isinstance(intent, TradeIntent)
    assert intent.strategy_id == "one_pick_two_day_v1"
    assert intent.side == "buy"
    assert intent.quantity == 200
    assert intent.limit_price == 100.0
    assert intent.metadata["one_pick"]["risk_reward_ratio"] == 2.0
