from __future__ import annotations

from datetime import datetime, timezone

from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.risk_gateway import RiskGateway, RiskGatewayState
from trading_agent_system.core.risk_gateway.checks import PremarketConstraintCheck
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.schemas import AccountSnapshot, MarketBar, TradeIntent


def _intent(symbol: str = "510300.SH", confidence: float = 0.7) -> TradeIntent:
    return TradeIntent(
        strategy_id="breakout_v1",
        strategy_version="1.0.0",
        symbol=symbol,
        side="buy",
        quantity=100,
        order_type="limit",
        limit_price=3.11,
        confidence=confidence,
        entry_reason=["demo breakout"],
        evidence_ids=["evt_theme"],
        feature_snapshot_id="feat_1",
    )


def _state(context: PremarketContext) -> RiskGatewayState:
    state = RiskGatewayState(
        {
            "global": {"trading_enabled": True, "require_human_approval": False},
            "limits": {"max_market_data_delay_ms": 1000},
        }
    )
    state.update_premarket_context(context)
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
    return state


def test_premarket_constraint_check_rejects_avoid_new_entry():
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "instruction": {
                "items": [
                    {
                        "instruction_type": "avoid_new_entry",
                        "target": "510300.SH",
                        "reason": "盘前监管风险未解除",
                        "evidence_event_ids": ["evt_risk"],
                        "source_ids": ["src_1"],
                        "expires_at": "2026-06-10T09:30:00+08:00",
                    }
                ]
            },
        }
    )

    result = PremarketConstraintCheck().run(_intent(), _state(context))

    assert result.status == "hard_reject"
    assert result.reason == "premarket_avoid_new_entry"
    assert result.details["evidence_ids"] == ["evt_risk"]


def test_gateway_queues_require_confirmation_for_manual_review(tmp_path):
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "instruction": {
                "items": [
                    {
                        "instruction_type": "require_confirmation",
                        "target": "ALL",
                        "reason": "消息源不足",
                        "source_ids": ["src_system"],
                        "expires_at": "2026-06-10T09:30:00+08:00",
                        "requires_manual_review": True,
                    }
                ]
            },
        }
    )
    bus = MemoryEventBus()
    state = _state(context)
    gateway = RiskGateway(
        state=state,
        event_bus=bus,
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        checks=[PremarketConstraintCheck()],
    )

    decision = gateway.on_trade_intent(_intent())

    assert decision.decision == "needs_human_approval"
    assert decision.reason == "premarket_requires_confirmation"
    assert state.approval_queue[0]["decision"]["decision_id"] == decision.decision_id
    assert bus.events("risk.approval_queue")[0]["decision"]["decision_id"] == decision.decision_id
