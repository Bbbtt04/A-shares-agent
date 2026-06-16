from scripts.run_premarket_agent import build_providers, resolve_limit_per_source
from trading_agent_system.agents.premarket_agent.news_provider import AStockDataPremarketProvider, TonghuashunNewsProvider


def test_build_providers_registers_social_platform_sources():
    providers = build_providers({"premarket": {"providers": ["kaipanla", "xueqiu"]}})

    assert [provider.source for provider in providers] == ["开盘啦最新资讯", "雪球热议"]


def test_build_providers_registers_sina_channel_sources():
    providers = build_providers({"premarket": {"providers": ["sina_finance", "sina_stock", "sina_global"]}})

    assert [provider.source for provider in providers] == ["新浪财经滚动", "新浪股票滚动", "新浪全球财经"]
    assert [provider.lid for provider in providers] == ["2516", "2517", "2518"]


def test_build_providers_registers_tonghuashun_source():
    providers = build_providers({"premarket": {"providers": ["tonghuashun"]}})

    assert [provider.source for provider in providers] == ["同花顺7x24"]


def test_build_providers_defaults_to_only_tonghuashun_7x24_source():
    providers = build_providers({"premarket": {}})

    assert len(providers) == 1
    assert isinstance(providers[0], TonghuashunNewsProvider)


def test_build_providers_adds_a_stock_data_provider_when_enabled():
    providers = build_providers(
        {
            "premarket": {
                "providers": [],
                "a_stock_data": {
                    "enabled": True,
                    "symbols": ["688981.SH", "002371.SZ"],
                },
            }
        }
    )

    assert any(isinstance(provider, AStockDataPremarketProvider) for provider in providers)


def test_resolve_limit_per_source_prefers_cli_then_config_then_default():
    assert resolve_limit_per_source({"premarket": {"limit_per_source": 80}}, cli_limit=120) == 120
    assert resolve_limit_per_source({"premarket": {"limit_per_source": 80}}, cli_limit=None) == 80
    assert resolve_limit_per_source({"premarket": {}}, cli_limit=None) is None
