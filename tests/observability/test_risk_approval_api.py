from __future__ import annotations

from datetime import date

from trading_agent_system.api import app as api_module
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.storage import JsonlEventRepository


def test_risk_approval_queue_reads_persisted_events(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "EVENT_DIR", tmp_path / "events")
    JsonlEventRepository(api_module.EVENT_DIR).append_envelope(
        make_envelope(
            "risk.approval_queue",
            {
                "intent": {"intent_id": "intent_1", "symbol": "510300.SH", "side": "buy"},
                "decision": {"decision_id": "risk_1", "decision": "needs_human_approval", "reason": "premarket_requires_confirmation"},
                "premarket": {"matched_instruction_types": ["require_confirmation"]},
            },
            producer="risk_gateway",
            trading_day=date(2026, 6, 10),
            run_id="risk_run_1",
            evidence_ids=["evt_theme"],
        )
    )

    response = api_module.risk_approval_queue(limit=20)

    assert response["queue"][0]["decision"]["decision_id"] == "risk_1"
    assert response["queue"][0]["intent"]["symbol"] == "510300.SH"
    assert response["queue"][0]["evidence_ids"] == ["evt_theme"]
