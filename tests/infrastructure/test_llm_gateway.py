from __future__ import annotations

import pytest

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.llm_gateway import (
    LLMGateway,
    MockModelClient,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PromptTemplateRegistry,
    StructuredOutputValidationError,
    StructuredOutputValidator,
    TokenUsage,
)
from trading_agent_system.core.llm_gateway.clients import OpenAICompatibleClient


def test_prompt_template_renders_required_variables() -> None:
    registry = PromptTemplateRegistry()
    registry.register(
        "stock-brief",
        "Analyze {symbol} during the {session} session.",
        required_variables=["symbol", "session"],
    )

    rendered = registry.render("stock-brief", symbol="600000", session="open")

    assert rendered == "Analyze 600000 during the open session."
    with pytest.raises(ValueError, match="session"):
        registry.render("stock-brief", symbol="600000")


def test_gateway_validates_json_structured_output_records_usage_and_audit(tmp_path) -> None:
    audit = AuditLedger(tmp_path / "audit.jsonl")
    client = MockModelClient(
        provider_name="mock-primary",
        outputs=[
            ModelResponse(
                content='{"action": "watch", "confidence": 0.72}',
                usage=TokenUsage(prompt_tokens=11, completion_tokens=7),
            )
        ],
    )
    gateway = LLMGateway(clients={"mock-primary": client}, audit_ledger=audit)

    response = gateway.complete(
        messages=[ModelMessage(role="user", content="Classify this catalyst.")],
        route_order=["mock-primary"],
        response_schema={"required": ["action", "confidence"]},
    )

    assert response.provider_name == "mock-primary"
    assert response.usage.total_tokens == 18
    assert response.structured_output == {"action": "watch", "confidence": 0.72}
    assert response.elapsed_ms >= 0
    assert audit.records[-1]["event_type"] == "llm.call"
    assert audit.records[-1]["payload"]["provider_name"] == "mock-primary"
    assert audit.records[-1]["payload"]["usage_total"] == 18


def test_gateway_falls_back_from_failing_primary_client(tmp_path) -> None:
    audit = AuditLedger(tmp_path / "audit.jsonl")
    primary = MockModelClient(
        provider_name="primary",
        outputs=[RuntimeError("primary down"), RuntimeError("primary still down")],
    )
    fallback = MockModelClient(
        provider_name="fallback",
        outputs=[
            ModelResponse(
                content='{"decision": "hold"}',
                usage=TokenUsage(prompt_tokens=3, completion_tokens=2),
            )
        ],
    )
    gateway = LLMGateway(
        clients={"primary": primary, "fallback": fallback},
        audit_ledger=audit,
    )

    response = gateway.complete(
        messages=[ModelMessage(role="user", content="Pick a decision.")],
        route_order=["primary", "fallback"],
        response_schema={"required": ["decision"]},
    )

    assert primary.call_count == 2
    assert fallback.call_count == 1
    assert response.provider_name == "fallback"
    assert response.structured_output == {"decision": "hold"}
    assert audit.records[-1]["payload"]["provider_name"] == "fallback"


def test_structured_output_validation_rejects_missing_required_fields() -> None:
    validator = StructuredOutputValidator()

    with pytest.raises(StructuredOutputValidationError, match="confidence"):
        validator.validate(
            '{"action": "watch"}',
            {"required": ["action", "confidence"]},
        )


def test_gateway_caches_requests_and_records_estimated_cost(tmp_path) -> None:
    audit = AuditLedger(tmp_path / "audit.jsonl")
    client = MockModelClient(
        provider_name="mock-primary",
        outputs=[
            ModelResponse(
                content='{"summary": "cached"}',
                usage=TokenUsage(prompt_tokens=100, completion_tokens=50),
            )
        ],
    )
    gateway = LLMGateway(
        clients={"mock-primary": client},
        audit_ledger=audit,
        pricing={
            "mock-primary": {"prompt_per_1k": 0.001, "completion_per_1k": 0.002},
        },
    )

    first = gateway.complete(
        messages=[ModelMessage(role="user", content="Summarize")],
        route_order=["mock-primary"],
        response_schema={"required": ["summary"]},
        cache_key="summary:510300",
    )
    second = gateway.complete(
        messages=[ModelMessage(role="user", content="Summarize")],
        route_order=["mock-primary"],
        response_schema={"required": ["summary"]},
        cache_key="summary:510300",
    )

    assert client.call_count == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.usage.estimated_cost == pytest.approx(0.0002)
    assert audit.records[-1]["payload"]["cache_hit"] is True


def test_openai_compatible_client_posts_chat_completion_payload() -> None:
    captured: dict[str, object] = {}

    def fake_transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout: float) -> dict[str, object]:
        captured.update({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {
            "choices": [{"message": {"content": "{\"ok\": true}"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            "model": "deepseek-chat",
        }

    client = OpenAICompatibleClient(
        provider_name="deepseek",
        api_key="sk-test",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        transport=fake_transport,
    )

    response = client.complete(
        ModelRequest(
            messages=[ModelMessage(role="user", content="Return JSON")],
            temperature=0,
            response_schema={"type": "object"},
        )
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "Return JSON"}]
    assert response.content == "{\"ok\": true}"
    assert response.usage.total_tokens == 7
