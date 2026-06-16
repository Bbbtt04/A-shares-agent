from __future__ import annotations

import json

from trading_agent_system.api import app as api_module


def test_llm_provider_config_is_saved_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "LLM_RUNTIME_CONFIG", tmp_path / "llm_runtime.json")
    monkeypatch.setattr(api_module, "AUDIT_DIR", tmp_path / "audit")

    response = api_module.update_llm_provider(
        api_module.LlmProviderUpdateRequest(
            provider="openai",
            api_key="sk-test-secret-1234",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4.1-mini",
        )
    )

    provider = response["providers"]["openai"]
    assert provider["api_key_set"] is True
    assert provider["api_key_preview"] == "sk-...1234"
    assert "sk-test-secret-1234" not in json.dumps(response)
    assert json.loads(api_module.LLM_RUNTIME_CONFIG.read_text(encoding="utf-8"))["providers"]["openai"]["api_key"] == "sk-test-secret-1234"


def test_llm_agent_route_and_usage_are_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "LLM_RUNTIME_CONFIG", tmp_path / "llm_runtime.json")
    monkeypatch.setattr(api_module, "AUDIT_DIR", tmp_path / "audit")
    api_module.AUDIT_DIR.mkdir(parents=True)
    (api_module.AUDIT_DIR / "audit.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-06-15T01:02:03Z",
                "event_type": "llm.call",
                "payload": {
                    "provider_name": "openai",
                    "agent": "one_pick_agent",
                    "usage_total": 123,
                    "estimated_cost": 0.0123,
                    "cache_hit": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = api_module.update_llm_agent_route(
        api_module.LlmAgentRouteUpdateRequest(
            agent="one_pick_agent",
            provider="openai",
            model="gpt-4.1-mini",
            max_llm_calls=3,
            max_llm_tokens=6000,
            max_llm_cost=1.0,
        )
    )

    route = response["agent_routes"]["one_pick_agent"]
    assert route["provider"] == "openai"
    assert route["model"] == "gpt-4.1-mini"
    assert route["budget"]["max_llm_tokens"] == 6000
    assert response["usage"]["total"] == {"calls": 1, "tokens": 123, "cost": 0.0123}
    assert response["usage"]["by_agent"]["one_pick_agent"]["calls"] == 1
