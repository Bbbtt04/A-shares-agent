from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_agent_system.agents.intel_agent import IntelAgent
from trading_agent_system.agents.intraday_agent import IntradayAgent
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.premarket import PremarketContextLoader
from trading_agent_system.core.strategy_registry import StrategyRegistry
from trading_agent_system.schemas import AccountSnapshot, MarketBar, PositionSnapshot


def build_demo_bars(symbol: str) -> list[MarketBar]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    closes = [3.00, 3.01, 3.02, 3.03, 3.04, 3.11]
    bars = []
    for idx, close in enumerate(closes):
        bars.append(
            MarketBar(
                symbol=symbol,
                ts=now + timedelta(minutes=idx),
                open=close - 0.01,
                high=close + 0.02,
                low=close - 0.02,
                close=close,
                volume=1000 if idx < len(closes) - 1 else 6000,
                amount=close * 1000,
            )
        )
    return bars


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/app.yaml")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    app_config = load_yaml_config(args.config)
    strategy_config = load_yaml_config(app_config["configs"]["strategy_registry"])
    bus = MemoryEventBus()
    audit = AuditLedger(app_config["paths"]["audit_log"])
    registry = StrategyRegistry.from_config(strategy_config)
    watchlist = app_config["watchlist"]
    premarket_context = PremarketContextLoader(Path("reports/premarket")).load_latest()
    agent = IntradayAgent(
        watchlist=watchlist,
        strategy_registry=registry,
        event_bus=bus,
        audit=audit,
        max_market_data_delay_ms=app_config["market"]["max_market_data_delay_ms"],
        premarket_context=premarket_context,
    )
    if args.demo:
        intel = IntelAgent(bus, audit)
        intel.publish_brief(
            symbols=[watchlist[0]],
            event_type="official_policy",
            importance="A",
            bias="bullish",
            confidence=0.72,
            actionability="candidate",
            summary="Demo policy catalyst for paper-trading scan.",
            evidence=[{"source": "demo"}],
        )
        for brief in bus.events("intel.briefs"):
            agent.ingest_intel(brief)
        agent.ingest_positions(PositionSnapshot())
        agent.ingest_account(AccountSnapshot(cash=1_000_000, nav=1_000_000))
        for bar in build_demo_bars(watchlist[0]):
            agent.ingest_bar(bar, delay_ms=0)
        intents = agent.scan()
        print(json.dumps([intent.model_dump(mode="json") for intent in intents], ensure_ascii=False, indent=2))
    else:
        print("IntradayAgent initialized. Use --demo for a local smoke run.")


if __name__ == "__main__":
    main()
