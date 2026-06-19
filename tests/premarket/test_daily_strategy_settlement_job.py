from __future__ import annotations

from datetime import date

import pytest

from scripts.run_daily_strategy_settlement import StaticOpenPriceProvider, run_daily_settlement
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


def test_run_daily_settlement_persists_outcome_and_learning_version(tmp_path) -> None:
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")
    store.recommendations.save(
        {
            "recommendation_id": "rec_20260618",
            "run_id": "recommend_20260618",
            "trading_day": "2026-06-18",
            "symbol": "600001.SH",
            "action": "buy",
            "priority": 1,
            "confidence": 0.8,
            "signal_score": 0.7,
            "expected_risk_reward": 1.8,
            "entry_conditions": [],
            "avoid_conditions": [],
            "risk_notes": ["crowding"],
            "handoff_payload": {"factor_scores": {"catalyst_strength": 0.8}},
        }
    )
    store.prices.save(
        {
            "trading_day": "2026-06-18",
            "symbol": "600001.SH",
            "price_type": "buy_open",
            "price_time": "09:30",
            "price": 10.0,
            "source": "fixture",
            "raw_payload": {},
        }
    )
    price_provider = StaticOpenPriceProvider({("2026-06-19", "600001.SH"): 10.5})

    result = run_daily_settlement(
        date(2026, 6, 19),
        store,
        price_provider=price_provider,
        calendar=TradingCalendarService(trading_days=["2026-06-18", "2026-06-19"]),
    )

    assert result["status"] == "success"
    assert result["outcome"]["return_pct"] == pytest.approx(0.05)
    assert store.outcomes.by_recommendation("rec_20260618")[0]["hit_result"] == "win"
    assert store.weights.active()["version"] == "pfl_20260619_000001"
    assert store.weights.active()["weights"]["catalyst_strength"] > 0


def test_run_daily_settlement_skips_without_buy_recommendation(tmp_path) -> None:
    store = StrategyLedgerStore(tmp_path / "ledger.sqlite")

    result = run_daily_settlement(
        date(2026, 6, 19),
        store,
        price_provider=StaticOpenPriceProvider({}),
        calendar=TradingCalendarService(trading_days=["2026-06-18", "2026-06-19"]),
    )

    assert result["status"] == "skipped"
    assert store.outcomes.latest() is None
