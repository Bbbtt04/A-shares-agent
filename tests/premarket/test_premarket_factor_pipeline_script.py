from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.run_premarket_factor_pipeline import build_llm_gateway_from_config, run_pipeline
from trading_agent_system.core.storage import JsonlEventRepository


def test_run_pipeline_builds_factor_recommendations_from_saved_premarket_report(tmp_path) -> None:
    report_path = tmp_path / "premarket" / "2026-06-19.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "date": "2026-06-19",
                "normalized_events": [
                    {
                        "event_id": "pmevt_1",
                        "source_ids": ["src_1"],
                        "source_rank": "official",
                        "title": "AI policy catalyst",
                        "summary": "AI policy catalyst maps to the company.",
                        "first_seen_at": "2026-06-19T00:30:00+00:00",
                        "last_updated_at": "2026-06-19T00:35:00+00:00",
                        "symbols": ["300229.SZ"],
                        "companies": ["拓尔思"],
                        "event_type": "policy",
                        "related_themes": ["AI"],
                        "importance": "A",
                        "bias": "bullish",
                        "confidence": 0.86,
                        "actionability": "candidate",
                        "evidence": [{"id": "ev_1"}],
                        "risk_flags": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_pipeline(
        report_path=report_path,
        event_dir=tmp_path / "events",
        generated_at=datetime(2026, 6, 19, 1, 0, tzinfo=timezone.utc),
        run_id="premarket_factor_20260619",
    )

    assert result["recommendations"].recommendations[0].symbol == "300229.SZ"
    repository = JsonlEventRepository(tmp_path / "events")
    envelopes = repository.load_envelopes("premarket.strategy_recommendations")
    assert envelopes[0].run_id == "premarket_factor_20260619"
    assert envelopes[0].payload["recommendations"][0]["symbol"] == "300229.SZ"


def test_build_llm_gateway_from_config_uses_agent_route(tmp_path) -> None:
    config_path = tmp_path / "llm_runtime.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "api_key": "sk-test",
                        "base_url": "https://api.deepseek.com",
                        "default_model": "deepseek-chat",
                    }
                },
                "agent_routes": {
                    "premarket_agent": {
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "budget": {"max_llm_calls": 1},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    gateway, route = build_llm_gateway_from_config(config_path, agent="premarket_agent")

    assert route["provider"] == "deepseek"
    assert route["model"] == "deepseek-chat"
    assert list(gateway.clients) == ["deepseek"]
