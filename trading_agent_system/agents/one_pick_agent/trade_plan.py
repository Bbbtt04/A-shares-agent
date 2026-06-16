from __future__ import annotations

from typing import Any

from trading_agent_system.schemas import TradeIntent

from .schemas import EffectiveOnePickStrategy, OnePickSelection, OnePickTradePlan


class TradePlanAgent:
    def __init__(self, llm_gateway: Any | None = None) -> None:
        self.llm_gateway = llm_gateway

    def create_plan(
        self,
        selection: OnePickSelection,
        strategy: EffectiveOnePickStrategy,
        *,
        last_price: float,
    ) -> OnePickTradePlan:
        take_profit_pct = float(strategy.exit_rule.get("take_profit_pct", 0.04))
        stop_loss_pct = float(strategy.exit_rule.get("stop_loss_pct", 0.02))
        quantity = int(strategy.entry_rule.get("default_quantity", 100))
        risk_reasons = list(selection.risk_flags)
        if not selection.threshold_passed:
            risk_reasons.extend(selection.threshold_reasons)
        buy_reasons = selection.reasons or ["top ranked one-pick candidate"]
        expected_upside = max(0.000001, take_profit_pct)
        expected_downside = max(0.000001, stop_loss_pct)

        return OnePickTradePlan(
            symbol=selection.selected_symbol,
            name=selection.selected_name,
            quantity=quantity,
            confidence=selection.confidence,
            expected_upside_pct=expected_upside,
            expected_downside_pct=expected_downside,
            risk_reward_ratio=round(expected_upside / expected_downside, 6),
            entry_price=last_price,
            stop_loss_price=round(last_price * (1 - stop_loss_pct), 6),
            take_profit_price=round(last_price * (1 + take_profit_pct), 6),
            buy_reasons=buy_reasons,
            risk_reasons=risk_reasons,
            evidence_ids=selection.evidence_ids,
            feature_scores=selection.feature_scores,
            strategy_tags=selection.strategy_tags,
            threshold_passed=selection.threshold_passed,
        )

    def to_trade_intent(self, plan: OnePickTradePlan, strategy: EffectiveOnePickStrategy) -> TradeIntent:
        return TradeIntent(
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            symbol=plan.symbol,
            side="buy",
            quantity=plan.quantity,
            order_type="limit",
            limit_price=plan.entry_price,
            ttl_seconds=int(strategy.entry_rule.get("ttl_seconds", 30)),
            confidence=plan.confidence,
            entry_reason=plan.buy_reasons,
            evidence_ids=plan.evidence_ids,
            feature_snapshot_id=plan.plan_id,
            invalidation={
                "stop_loss_price": plan.stop_loss_price,
                "take_profit_price": plan.take_profit_price,
                "next_day_exit_required": True,
            },
            max_loss_amount=plan.quantity * max(0.0, plan.entry_price - plan.stop_loss_price),
            metadata={
                "one_pick": {
                    "plan_id": plan.plan_id,
                    "risk_reward_ratio": plan.risk_reward_ratio,
                    "expected_upside_pct": plan.expected_upside_pct,
                    "expected_downside_pct": plan.expected_downside_pct,
                    "threshold_passed": plan.threshold_passed,
                    "risk_reasons": plan.risk_reasons,
                    "strategy_tags": plan.strategy_tags,
                }
            },
        )
