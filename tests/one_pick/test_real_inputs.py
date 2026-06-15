from __future__ import annotations

from datetime import date

from trading_agent_system.agents.one_pick_agent.real_inputs import (
    RealOnePickInputBuilder,
    UniverseConfig,
    expand_events_with_theme_symbols,
)
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.storage import JsonlEventRepository


def test_expand_events_uses_theme_map_but_keeps_symbols_inside_universe():
    events = [
        {
            "event_id": "evt_robot",
            "symbols": [],
            "title": "机器人产业政策加码",
            "related_themes": ["机器人"],
            "importance": "A",
            "bias": "bullish",
            "confidence": 0.8,
            "source_rank": "official",
        }
    ]

    expanded = expand_events_with_theme_symbols(
        events,
        universe_symbols={"300024.SZ"},
        theme_symbol_map={"机器人": ["300024.SZ", "688256.SH"]},
    )

    assert expanded[0]["symbols"] == ["300024.SZ"]
    assert expanded[0]["symbol_source"] == "theme_map"


def test_real_input_builder_loads_latest_premarket_events_and_market_quotes(tmp_path):
    event_dir = tmp_path / "events"
    repository = JsonlEventRepository(event_dir)
    trading_day = date(2026, 6, 15)
    repository.append_envelope(
        make_envelope(
            "premarket.normalized_events",
            {
                "items": [
                    {
                        "event_id": "evt_robot",
                        "symbols": [],
                        "title": "机器人产业政策加码",
                        "related_themes": ["机器人"],
                        "importance": "A",
                        "bias": "bullish",
                        "confidence": 0.8,
                        "source_rank": "official",
                    }
                ]
            },
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="pre_1",
        )
    )
    repository.append_envelope(
        make_envelope(
            "premarket.rag_evidence_packs",
            {"packs": [{"evidence_id": "rag_robot", "symbols": ["300024.SZ"], "score": 0.9}]},
            producer="premarket_agent",
            trading_day=trading_day,
            run_id="pre_1",
        )
    )

    class FakeMarketProvider:
        def fetch_quotes(self, symbols):
            assert symbols == ["300024.SZ"]
            return [
                {
                    "symbol": "300024.SZ",
                    "name": "机器人",
                    "price": 12.3,
                    "change_pct": 1.2,
                }
            ]

    builder = RealOnePickInputBuilder(
        event_dir=event_dir,
        universe=UniverseConfig(symbols=["300024.SZ"], source="test_csi1000"),
        theme_symbol_map={"机器人": ["300024.SZ"]},
        market_provider=FakeMarketProvider(),
    )

    inputs = builder.build(trading_day=trading_day)

    assert inputs.events[0]["symbols"] == ["300024.SZ"]
    assert inputs.evidence_packs[0]["evidence_id"] == "rag_robot"
    assert inputs.market_snapshots["300024.SZ"]["last_price"] == 12.3
    assert inputs.metadata["universe"] == "csi1000"
    assert inputs.metadata["source"] == "real"
