from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from trading_agent_system.agents.intraday_agent import IntradayAgent
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.strategy_registry import StrategyConfig, StrategyRegistry
from trading_agent_system.schemas import AccountSnapshot, MarketBar, PositionSnapshot


def _bars(symbol: str) -> list[MarketBar]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    closes = [3.00, 3.01, 3.02, 3.03, 3.04, 3.11]
    return [
        MarketBar(
            symbol=symbol,
            ts=now + timedelta(minutes=idx),
            open=close - 0.01,
            high=close + 0.02,
            low=close - 0.02,
            close=close,
            volume=1000 if idx < 5 else 6000,
            amount=close * 1000,
        )
        for idx, close in enumerate(closes)
    ]


def _agent(tmp_path, context: PremarketContext) -> IntradayAgent:
    symbol = "510300.SH"
    agent = IntradayAgent(
        watchlist=[symbol],
        strategy_registry=StrategyRegistry(
            [
                StrategyConfig(
                    strategy_id="breakout_v1",
                    version="1.0.0",
                    allowed_symbols=[symbol],
                    max_confidence_cap=0.8,
                )
            ]
        ),
        event_bus=MemoryEventBus(),
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        premarket_context=context,
    )
    agent.ingest_positions(PositionSnapshot())
    agent.ingest_account(AccountSnapshot(cash=1_000_000, nav=1_000_000))
    for bar in _bars(symbol):
        agent.ingest_bar(bar, delay_ms=0)
    return agent


def test_intraday_skips_buy_when_premarket_avoids_symbol(tmp_path):
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "market_view": "cautious",
            "instruction": {
                "items": [
                    {
                        "instruction_type": "avoid_new_entry",
                        "target": "510300.SH",
                        "reason": "盘前监管风险未解除",
                        "evidence_event_ids": ["evt_risk"],
                        "source_ids": ["src_1"],
                        "expires_at": "2026-06-10T09:30:00+08:00",
                        "requires_manual_review": True,
                    }
                ]
            },
        }
    )

    intents = _agent(tmp_path, context).scan()

    assert intents == []


def test_intraday_intent_carries_premarket_watch_evidence(tmp_path):
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "market_view": "neutral",
            "morning_brief": {"key_themes": ["半导体"]},
            "opening_radar": {"confirmed_themes": ["半导体"], "failed_themes": []},
            "instruction": {
                "items": [
                    {
                        "instruction_type": "watch_opening_auction",
                        "target": "510300.SH",
                        "reason": "半导体主题竞价确认后可观察",
                        "evidence_event_ids": ["evt_theme"],
                        "source_ids": ["src_2"],
                        "expires_at": "2026-06-10T09:30:00+08:00",
                    }
                ]
            },
        }
    )

    intents = _agent(tmp_path, context).scan()

    assert len(intents) == 1
    assert "evt_theme" in intents[0].evidence_ids
    assert intents[0].metadata["premarket"]["matched_instruction_types"] == ["watch_opening_auction"]
    assert intents[0].metadata["premarket"]["confirmed_themes"] == ["半导体"]
    assert any("盘前" in reason for reason in intents[0].entry_reason)


def test_premarket_context_extracts_all_symbol_and_radar_constraints():
    context = PremarketContext.from_report(
        {
            "date": date(2026, 6, 10),
            "market_view": "cautious",
            "morning_brief": {"key_themes": ["机器人"], "watch_symbols": ["300750.SZ"], "avoid_symbols": ["688981.SH"]},
            "opening_radar": {
                "confirmed_themes": ["机器人"],
                "failed_themes": ["券商"],
                "watch_items": [{"symbol": "300750.SZ", "theme": "机器人", "evidence_event_ids": ["evt_watch"]}],
                "risk_alerts": [{"symbol": "688981.SH", "signal": "risk_alert", "evidence_event_ids": ["evt_risk"]}],
            },
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

    assert context.requires_confirmation("300750.SZ")
    assert context.requires_confirmation("688981.SH")
    assert context.constraints_for("300750.SZ")[0].instruction_type == "require_confirmation"
    assert context.confirmed_themes == ["机器人"]
    assert context.failed_themes == ["券商"]


def test_intraday_accepts_intel_payload_dict_from_event_bus(tmp_path):
    context = PremarketContext.from_report({"date": "2026-06-10"})
    agent = _agent(tmp_path, context)

    agent.ingest_intel(
        {
            "event_id": "intel_1",
            "first_seen_at": "2026-06-10T01:00:00+00:00",
            "published_at": "2026-06-10T01:00:00+00:00",
            "symbols": ["510300.SH"],
            "event_type": "official_policy",
            "importance": "A",
            "bias": "bullish",
            "confidence": 0.7,
            "actionability": "candidate",
            "summary": "政策催化",
            "evidence": [{"source": "demo"}],
            "risk_flags": [],
            "ttl_seconds": 21600,
        }
    )

    intents = agent.scan()

    assert len(intents) == 1
