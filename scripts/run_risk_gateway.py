from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.risk_gateway import RiskGateway, RiskGatewayState
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.schemas import AccountSnapshot, MarketBar, TradeIntent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/risk.paper.yaml")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    risk_config = load_yaml_config(args.config)
    bus = DurableEventBus(JsonlEventRepository(Path("data/events")))
    audit = AuditLedger("data/audit/risk_gateway.jsonl")
    state = RiskGatewayState(risk_config)
    gateway = RiskGateway(state=state, event_bus=bus, audit=audit)
    if args.demo:
        state.update_account(AccountSnapshot(cash=1_000_000, nav=1_000_000))
        state.update_bar(
            MarketBar(
                symbol="510300.SH",
                ts=datetime.now(timezone.utc),
                open=3.1,
                high=3.12,
                low=3.08,
                close=3.11,
                volume=6000,
            ),
            delay_ms=0,
        )
        intent = TradeIntent(
            strategy_id="breakout_v1",
            strategy_version="1.0.0",
            symbol="510300.SH",
            side="buy",
            quantity=100,
            order_type="limit",
            limit_price=3.11,
            confidence=0.65,
            entry_reason=["demo breakout"],
            feature_snapshot_id="demo_feature",
        )
        decision = gateway.on_trade_intent(intent)
        print(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print(f"orders.instructions={len(bus.events('orders.instructions'))}")
    else:
        print("RiskGateway initialized. Use --demo for a local smoke run.")


if __name__ == "__main__":
    main()
