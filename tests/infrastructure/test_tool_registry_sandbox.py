import pytest

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.sandbox import (
    Permission,
    PermissionProfile,
    ToolPermissionError,
    ToolRateLimitError,
    ToolValidationError,
)
from trading_agent_system.core.tools import ToolDefinition, ToolExecutor, ToolRegistry


def test_registry_register_get_and_list_tools():
    definition = ToolDefinition(
        name="get_market_snapshot",
        handler=lambda payload: {"symbol": payload["symbol"]},
        required_permissions={Permission.READ_MARKET},
        input_schema={"required": ["symbol"]},
        output_schema={"required": ["symbol"]},
    )
    registry = ToolRegistry()

    registry.register(definition)

    assert registry.get("get_market_snapshot") is definition
    assert registry.list() == [definition]


def test_reader_cannot_call_write_state_tool(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write_agent_event",
            handler=lambda payload: {"ok": True},
            required_permissions={Permission.WRITE_STATE},
            input_schema={"required": ["event"]},
            output_schema={"required": ["ok"]},
        )
    )
    executor = ToolExecutor(registry, AuditLedger(tmp_path / "audit.jsonl"))

    with pytest.raises(ToolPermissionError):
        executor.call(
            "write_agent_event",
            {"event": "analysis_started"},
            PermissionProfile.reader(),
        )


def test_reader_can_get_market_snapshot_and_records_audit(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    registry = ToolRegistry()

    def get_market_snapshot(payload):
        return {"symbol": payload["symbol"], "last_price": 10.5}

    registry.register(
        ToolDefinition(
            name="get_market_snapshot",
            handler=get_market_snapshot,
            required_permissions={Permission.READ_MARKET},
            input_schema={"required": ["symbol"]},
            output_schema={"required": ["symbol", "last_price"]},
        )
    )
    executor = ToolExecutor(registry, ledger)

    result = executor.call(
        "get_market_snapshot",
        {"symbol": "600000"},
        PermissionProfile.reader(),
    )

    assert result.success is True
    assert result.output == {"symbol": "600000", "last_price": 10.5}
    assert result.error is None
    assert result.attempts == 1
    assert result.elapsed_seconds >= 0
    assert ledger.records[-1]["event_type"] == "tool.call"
    assert ledger.records[-1]["payload"]["tool_name"] == "get_market_snapshot"
    assert ledger.records[-1]["payload"]["success"] is True


def test_search_news_uses_fallback_after_handler_failure(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    registry = ToolRegistry()

    def failing_search(payload):
        raise RuntimeError("news source unavailable")

    def fallback_search(payload):
        return {"items": [{"title": "fallback", "query": payload["query"]}]}

    registry.register(
        ToolDefinition(
            name="search_news",
            handler=failing_search,
            required_permissions={Permission.READ_NEWS},
            input_schema={"required": ["query"]},
            output_schema={"required": ["items"]},
            retries=0,
            fallback=fallback_search,
        )
    )
    executor = ToolExecutor(registry, ledger)

    result = executor.call("search_news", {"query": "AI"}, PermissionProfile.reader())

    assert result.success is True
    assert result.output == {"items": [{"title": "fallback", "query": "AI"}]}
    assert result.fallback_used is True
    assert result.attempts == 1
    assert ledger.records[-1]["payload"]["fallback_used"] is True


def test_validation_rejects_missing_required_input(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_market_snapshot",
            handler=lambda payload: {"symbol": payload["symbol"]},
            required_permissions={Permission.READ_MARKET},
            input_schema={"required": ["symbol"]},
            output_schema={"required": ["symbol"]},
        )
    )
    executor = ToolExecutor(registry, AuditLedger(tmp_path / "audit.jsonl"))

    with pytest.raises(ToolValidationError, match="symbol"):
        executor.call("get_market_snapshot", {}, PermissionProfile.reader())


def test_permission_profiles_track_agent_budget_and_mvp_permissions():
    reader = PermissionProfile.reader(agent="premarket_agent")
    analyst = PermissionProfile.analyst(agent="news_agent", max_tool_calls=1)

    assert reader.agent == "premarket_agent"
    assert Permission.READ_MARKET in reader.permissions
    assert Permission.READ_NEWS in reader.permissions
    assert Permission.READ_ANNOUNCEMENTS in reader.permissions
    assert Permission.READ_KNOWLEDGE in reader.permissions
    assert Permission.CALL_LLM in analyst.permissions
    assert analyst.can_call_tool() is True

    spent = analyst.record_tool_call()

    assert spent.spent_tool_calls == 1
    assert spent.can_call_tool() is False


def test_tool_executor_enforces_rate_limit_and_exports_cache_metadata(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="query_knowledge",
            handler=lambda payload: {"items": [{"id": payload["q"]}]},
            required_permissions={Permission.READ_KNOWLEDGE},
            input_schema={"required": ["q"]},
            output_schema={"required": ["items"]},
            cacheable=True,
            rate_limit_per_minute=1,
        )
    )
    executor = ToolExecutor(registry, AuditLedger(tmp_path / "audit.jsonl"))
    profile = PermissionProfile.reader()

    first = executor.call("query_knowledge", {"q": "robot"}, profile)

    assert first.success is True
    assert first.cacheable is True
    with pytest.raises(ToolRateLimitError):
        executor.call("query_knowledge", {"q": "robot"}, profile)
