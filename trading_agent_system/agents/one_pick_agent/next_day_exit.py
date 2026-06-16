from __future__ import annotations

from trading_agent_system.schemas import MarketBar, TradeIntent

from .schemas import EffectiveOnePickStrategy, OnePickExecutionRecord, OnePickExitPlan


class NextDayExitAgent:
    def __init__(self, take_profit_pct: float = 0.04, stop_loss_pct: float = 0.02) -> None:
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct

    @classmethod
    def from_strategy(cls, strategy: EffectiveOnePickStrategy) -> "NextDayExitAgent":
        return cls(
            take_profit_pct=float(strategy.exit_rule.get("take_profit_pct", 0.04)),
            stop_loss_pct=float(strategy.exit_rule.get("stop_loss_pct", 0.02)),
        )

    def plan_exit(self, entry_execution: OnePickExecutionRecord, market_bars: list[MarketBar]) -> OnePickExitPlan:
        if not market_bars:
            raise ValueError("market_bars are required for next-day exit")
        take_profit_price = round(entry_execution.price * (1 + self.take_profit_pct), 6)
        stop_loss_price = round(entry_execution.price * (1 - self.stop_loss_pct), 6)
        for bar in market_bars:
            if bar.high >= take_profit_price:
                return self._exit(entry_execution, take_profit_price, "take_profit")
            if bar.low <= stop_loss_price:
                return self._exit(entry_execution, stop_loss_price, "stop_loss")
        return self._exit(entry_execution, market_bars[-1].close, "time_exit")

    def to_trade_intent(
        self,
        exit_plan: OnePickExitPlan,
        strategy: EffectiveOnePickStrategy,
        *,
        feature_snapshot_id: str,
    ) -> TradeIntent:
        return TradeIntent(
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            symbol=exit_plan.symbol,
            side="sell",
            quantity=exit_plan.quantity,
            order_type="marketable_limit",
            limit_price=exit_plan.exit_price,
            ttl_seconds=int(strategy.exit_rule.get("ttl_seconds", 30)),
            confidence=1.0,
            entry_reason=[f"one-pick next-day exit: {exit_plan.reason}"],
            evidence_ids=exit_plan.evidence_ids,
            feature_snapshot_id=feature_snapshot_id,
            metadata={"one_pick": {"exit_plan_id": exit_plan.exit_plan_id, "reason": exit_plan.reason}},
        )

    def _exit(self, entry_execution: OnePickExecutionRecord, price: float, reason: str) -> OnePickExitPlan:
        return OnePickExitPlan(
            symbol=entry_execution.symbol,
            quantity=entry_execution.quantity,
            exit_price=price,
            reason=reason,  # type: ignore[arg-type]
            remaining_quantity_after_exit=0,
        )
