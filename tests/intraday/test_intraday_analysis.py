from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_agent_system.agents.intraday_agent import IntradayAgent
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.strategy_registry import StrategyConfig, StrategyRegistry
from trading_agent_system.schemas import AccountSnapshot, IntelBrief, MarketBar, PositionSnapshot


def _bars(symbol: str, closes: list[float] | None = None) -> list[MarketBar]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    closes = closes or [3.00, 3.01, 3.02, 3.03, 3.04, 3.11]
    return [
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
        for idx, close in enumerate(closes)
    ]


def _agent(tmp_path, symbols: list[str], context: PremarketContext | None = None) -> tuple[IntradayAgent, MemoryEventBus]:
    bus = MemoryEventBus()
    agent = IntradayAgent(
        watchlist=symbols,
        strategy_registry=StrategyRegistry(
            [
                StrategyConfig(
                    strategy_id="breakout_v1",
                    version="1.0.0",
                    allowed_symbols=symbols,
                    max_confidence_cap=0.8,
                )
            ]
        ),
        event_bus=bus,
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        premarket_context=context,
    )
    agent.ingest_positions(PositionSnapshot())
    agent.ingest_account(AccountSnapshot(cash=1_000_000, nav=1_000_000))
    return agent, bus


def _intel(symbol: str, event_id: str = "intel_1") -> IntelBrief:
    return IntelBrief(
        event_id=event_id,
        first_seen_at=datetime.now(timezone.utc),
        published_at=datetime.now(timezone.utc),
        symbols=[symbol],
        event_type="official_policy",
        importance="A",
        bias="bullish",
        confidence=0.72,
        actionability="candidate",
        summary="政策催化",
        evidence=[{"source": "demo"}],
    )


def test_intraday_agent_publishes_analysis_report_with_symbol_scores(tmp_path):
    agent, bus = _agent(tmp_path, ["688981.SH", "000001.SZ"])
    agent.ingest_intel(_intel("688981.SH"))
    for bar in _bars("688981.SH"):
        agent.ingest_bar(bar, delay_ms=0)
    for bar in _bars("000001.SZ", [10.00, 10.00, 10.01, 10.01, 10.02, 10.02]):
        agent.ingest_bar(bar, delay_ms=0)

    intents = agent.scan()

    assert len(intents) == 1
    assert agent.latest_analysis_report is not None
    report = agent.latest_analysis_report
    assert report.trade_intent_count == 1
    assert report.market_state.data_quality == "ok"
    assert [item.symbol for item in report.symbols] == ["688981.SH", "000001.SZ"]
    assert report.symbols[0].status == "tradable"
    assert report.symbols[0].score > report.symbols[1].score
    assert report.symbols[1].status == "no_signal"
    assert bus.events("intraday.analysis")[0]["report_id"] == report.report_id


def test_intraday_analysis_explains_premarket_filter_reason(tmp_path):
    context = PremarketContext.from_report(
        {
            "date": "2026-06-10",
            "instruction": {
                "items": [
                    {
                        "instruction_type": "avoid_new_entry",
                        "target": "688981.SH",
                        "reason": "盘前监管风险未解除",
                        "evidence_event_ids": ["evt_risk"],
                        "source_ids": ["src_1"],
                    }
                ]
            },
        }
    )
    agent, _ = _agent(tmp_path, ["688981.SH"], context)
    agent.ingest_intel(_intel("688981.SH"))
    for bar in _bars("688981.SH"):
        agent.ingest_bar(bar, delay_ms=0)

    intents = agent.scan()

    assert intents == []
    assert agent.latest_analysis_report is not None
    symbol_report = agent.latest_analysis_report.symbols[0]
    assert symbol_report.status == "blocked"
    assert symbol_report.signals[0].status == "filtered"
    assert symbol_report.signals[0].filter_reason == "premarket_blocks_new_entry"
    assert any("盘前" in reason for reason in symbol_report.reasons)
