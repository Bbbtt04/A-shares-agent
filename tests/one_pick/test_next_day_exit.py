from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_agent_system.agents.one_pick_agent.next_day_exit import NextDayExitAgent
from trading_agent_system.agents.one_pick_agent.schemas import OnePickExecutionRecord
from trading_agent_system.schemas import MarketBar


def _execution() -> OnePickExecutionRecord:
    return OnePickExecutionRecord(
        symbol="688981.SH",
        side="buy",
        quantity=100,
        price=100.0,
        intent_id="intent_1",
        order_id="order_1",
        fill_id="fill_1",
    )


def _bar(high: float, low: float, close: float, minute: int = 0) -> MarketBar:
    ts = datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return MarketBar(symbol="688981.SH", ts=ts, open=100.0, high=high, low=low, close=close, volume=1000)


def test_next_day_exit_uses_take_profit_before_time_exit():
    plan = NextDayExitAgent(take_profit_pct=0.04, stop_loss_pct=0.02).plan_exit(
        _execution(),
        [_bar(high=105.0, low=99.0, close=104.5)],
    )

    assert plan.reason == "take_profit"
    assert plan.exit_price == 104.0
    assert plan.remaining_quantity_after_exit == 0


def test_next_day_exit_uses_stop_loss_before_time_exit():
    plan = NextDayExitAgent(take_profit_pct=0.04, stop_loss_pct=0.02).plan_exit(
        _execution(),
        [_bar(high=101.0, low=97.0, close=98.0)],
    )

    assert plan.reason == "stop_loss"
    assert plan.exit_price == 98.0
    assert plan.remaining_quantity_after_exit == 0


def test_next_day_exit_forces_time_exit_at_last_close():
    plan = NextDayExitAgent(take_profit_pct=0.04, stop_loss_pct=0.02).plan_exit(
        _execution(),
        [_bar(high=102.0, low=99.0, close=101.0, minute=0), _bar(high=103.0, low=99.5, close=102.0, minute=1)],
    )

    assert plan.reason == "time_exit"
    assert plan.exit_price == 102.0
    assert plan.remaining_quantity_after_exit == 0
