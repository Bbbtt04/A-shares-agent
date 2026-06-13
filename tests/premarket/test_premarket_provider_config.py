from scripts.run_premarket_agent import build_providers, resolve_limit_per_source
from trading_agent_system.agents.premarket_agent.crawler_adapter import (
    LocalPremarketCrawlerProvider,
    McpPremarketCrawlerProvider,
    StdioMcpToolClient,
)


def test_build_providers_uses_crawler_adapter_for_social_platform_sources():
    providers = build_providers({"premarket": {"providers": ["kaipanla", "xueqiu"]}})

    assert len(providers) == 1
    assert isinstance(providers[0], LocalPremarketCrawlerProvider)
    assert providers[0].sources == ["kaipanla", "xueqiu"]


def test_build_providers_uses_crawler_adapter_for_sina_channel_sources():
    providers = build_providers({"premarket": {"providers": ["sina_finance", "sina_stock", "sina_global"]}})

    assert len(providers) == 1
    assert isinstance(providers[0], LocalPremarketCrawlerProvider)
    assert providers[0].sources == ["sina_finance", "sina_stock", "sina_global"]


def test_build_providers_uses_crawler_adapter_for_tonghuashun_source():
    providers = build_providers({"premarket": {"providers": ["tonghuashun"]}})

    assert len(providers) == 1
    assert isinstance(providers[0], LocalPremarketCrawlerProvider)
    assert providers[0].sources == ["tonghuashun"]


def test_build_providers_uses_stdio_mcp_adapter_when_configured():
    providers = build_providers(
        {
            "premarket": {
                "crawler": {
                    "mode": "mcp",
                    "command": ".venv/bin/python",
                    "args": ["-m", "premarket_crawler_mcp.server"],
                    "timeout_seconds": 12,
                },
                "providers": ["tonghuashun"],
            }
        }
    )

    assert len(providers) == 1
    assert isinstance(providers[0], McpPremarketCrawlerProvider)
    assert providers[0].sources == ["tonghuashun"]
    assert isinstance(providers[0].client, StdioMcpToolClient)
    assert providers[0].client.command == ".venv/bin/python"
    assert providers[0].client.args == ["-m", "premarket_crawler_mcp.server"]
    assert providers[0].client.timeout_seconds == 12


def test_resolve_limit_per_source_prefers_cli_then_config_then_default():
    assert resolve_limit_per_source({"premarket": {"limit_per_source": 80}}, cli_limit=120) == 120
    assert resolve_limit_per_source({"premarket": {"limit_per_source": 80}}, cli_limit=None) == 80
    assert resolve_limit_per_source({"premarket": {}}, cli_limit=None) == 30
