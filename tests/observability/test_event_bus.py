from datetime import date

from trading_agent_system.core.event_bus import DurableEventBus, MemoryEventBus
from trading_agent_system.core.storage import JsonlEventRepository


def test_memory_event_bus_wraps_events_in_envelopes():
    bus = MemoryEventBus()

    envelope = bus.publish(
        "premarket.instructions",
        {"items": [{"target": "板块:机器人"}]},
        producer="premarket_agent",
        trading_day=date(2026, 6, 10),
        run_id="run_1",
        evidence_ids=["evt_1"],
    )

    assert envelope.topic == "premarket.instructions"
    assert envelope.producer == "premarket_agent"
    assert envelope.trading_day == date(2026, 6, 10)
    assert envelope.run_id == "run_1"
    assert envelope.payload["items"][0]["target"] == "板块:机器人"
    assert envelope.evidence_ids == ["evt_1"]
    assert bus.events("premarket.instructions")[0] == envelope.payload
    assert bus.envelopes("premarket.instructions")[0] == envelope


def test_durable_event_bus_persists_and_filters_events(tmp_path):
    repository = JsonlEventRepository(tmp_path / "events")
    bus = DurableEventBus(repository=repository)

    first = bus.publish(
        "premarket.morning_brief",
        {"summary": "机器人进入观察"},
        producer="premarket_agent",
        trading_day=date(2026, 6, 10),
        run_id="run_1",
    )
    bus.publish(
        "premarket.morning_brief",
        {"summary": "半导体进入观察"},
        producer="premarket_agent",
        trading_day=date(2026, 6, 11),
        run_id="run_2",
    )

    loaded = repository.load_envelopes("premarket.morning_brief", trading_day=date(2026, 6, 10))

    assert len(loaded) == 1
    assert loaded[0].event_id == first.event_id
    assert loaded[0].payload["summary"] == "机器人进入观察"
    assert repository.load_envelopes("premarket.morning_brief", run_id="run_2")[0].payload["summary"] == "半导体进入观察"
