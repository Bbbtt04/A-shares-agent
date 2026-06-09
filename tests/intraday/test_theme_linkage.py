from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_agent_system.agents.intraday_agent.feature_builder import FeatureBuilder
from trading_agent_system.agents.intraday_agent.trade_planner import TradePlanner
from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.reference import ThemeRegistry
from trading_agent_system.schemas import FeatureSnapshot, MarketBar, MarketState, SignalCandidate


def _bars(symbol: str, closes: list[float]) -> list[MarketBar]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return [
        MarketBar(
            symbol=symbol,
            ts=now + timedelta(minutes=idx),
            open=close - 0.01,
            high=close + 0.02,
            low=close - 0.02,
            close=close,
            volume=1000 + idx * 100,
        )
        for idx, close in enumerate(closes)
    ]


def _state() -> MarketState:
    return MarketState(
        ts=datetime.now(timezone.utc),
        regime="normal",
        volatility_level="normal",
        liquidity_level="normal",
        data_quality="ok",
        risk_mode="normal",
    )


def test_theme_registry_resolves_aliases_and_symbols():
    registry = ThemeRegistry.default()

    assert registry.resolve_theme("芯片") == "半导体"
    assert "半导体" in registry.themes_for_symbol("688981.SH")
    assert "688981.SH" in registry.symbols_for_theme("半导体")


def test_feature_builder_adds_theme_linkage_features():
    registry = ThemeRegistry.default()
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "morning_brief": {"key_themes": ["半导体"]},
            "opening_radar": {"confirmed_themes": ["半导体"]},
        }
    )
    builder = FeatureBuilder(theme_registry=registry)

    snapshot = builder.build(
        "688981.SH",
        _bars("688981.SH", [50.0, 50.2, 50.4, 50.8, 51.0, 51.5]),
        [],
        _state(),
        premarket_context=context,
        peer_bars={
            "002371.SZ": _bars("002371.SZ", [300.0, 301.0, 302.0, 304.0, 305.0, 309.0]),
            "688256.SH": _bars("688256.SH", [600.0, 598.0, 599.0, 601.0, 604.0, 606.0]),
        },
    )

    assert snapshot.features["primary_theme"] == "半导体"
    assert snapshot.features["theme_confirmation"] is True
    assert snapshot.features["theme_peer_count"] == 2
    assert float(snapshot.features["theme_strength"]) > 0


def test_trade_planner_carries_theme_linkage_metadata():
    snapshot = FeatureSnapshot(
        symbol="688981.SH",
        ts=datetime.now(timezone.utc),
        features={
            "spread_bps": 0.0,
            "primary_theme": "半导体",
            "theme_strength": 0.023,
            "theme_confirmation": True,
            "theme_peer_count": 2.0,
        },
    )
    candidate = SignalCandidate(
        strategy_id="breakout_v1",
        strategy_version="1.0.0",
        symbol="688981.SH",
        side="buy",
        raw_score=0.72,
        confidence=0.65,
        reasons=["突破日内高点"],
        feature_snapshot_id=snapshot.snapshot_id,
        suggested_quantity=100,
        suggested_limit_price=51.5,
    )

    intent = TradePlanner().plan(candidate, snapshot, _state(), [])

    assert intent is not None
    assert intent.metadata["theme"]["primary_theme"] == "半导体"
    assert intent.metadata["theme"]["theme_confirmation"] is True
    assert any("板块联动" in reason for reason in intent.entry_reason)
