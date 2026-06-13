from pathlib import Path


def test_infrastructure_packages_are_importable():
    import trading_agent_system.core.contracts as contracts
    import trading_agent_system.core.data_sources as data_sources
    import trading_agent_system.core.llm_gateway as llm_gateway
    import trading_agent_system.core.sandbox as sandbox
    import trading_agent_system.core.tools as tools

    assert contracts.AgentOutputEnvelope
    assert data_sources.DataSourceRegistry
    assert llm_gateway.LLMGateway
    assert sandbox.PermissionProfile
    assert tools.ToolExecutor


def test_implementation_plan_marks_m0_m3_in_progress_or_done():
    doc = Path("docs/architecture/implementation-breakdown.md").read_text(encoding="utf-8")

    assert "M0-M3 基建层执行状态" in doc
    assert "LLM Gateway" in doc
    assert "Tool Registry" in doc
    assert "DataSourceRegistry" in doc
