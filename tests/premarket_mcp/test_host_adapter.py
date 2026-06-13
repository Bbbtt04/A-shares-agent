from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import CrawlerResponseContract, FetchWindowContract, PremarketNewsItemContract
from trading_agent_system.agents.premarket_agent.crawler_adapter import (
    LocalPremarketCrawlerProvider,
    McpPremarketCrawlerProvider,
)
from trading_agent_system.agents.premarket_agent.news_provider import NewsProviderResult
from trading_agent_system.schemas import PremarketNewsItem


class StaticCrawlerService:
    def fetch_premarket_news(self, sources, limit_per_source, window):
        return CrawlerResponseContract(
            status="ok",
            window=window,
            items=[
                PremarketNewsItemContract(
                    source="同花顺7x24",
                    provider_name="tonghuashun",
                    source_tier="professional",
                    title="适配器新闻",
                    published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )
            ],
            source_status=[],
            warnings=[],
        )


class FakeMcpToolClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.response


class RaisingMcpToolClient:
    def call_tool(self, name, arguments):
        raise RuntimeError("stdio unavailable")


class FallbackProvider:
    source = "fallback"

    def fetch(self, limit=30, window=None):
        return NewsProviderResult(
            self.source,
            [
                PremarketNewsItem(
                    source="fallback",
                    source_tier="professional",
                    title="本地降级新闻",
                    published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )
            ],
            "ok",
        )


def test_mcp_crawler_provider_calls_fetch_tool_and_maps_response():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    response = CrawlerResponseContract(
        status="ok",
        window=window,
        items=[
            PremarketNewsItemContract(
                source="同花顺7x24",
                provider_name="tonghuashun",
                source_tier="professional",
                title="MCP新闻",
                published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        ],
        source_status=[],
    ).model_dump(mode="json")
    client = FakeMcpToolClient(response)
    provider = McpPremarketCrawlerProvider(client=client, sources=["tonghuashun"])

    result = provider.fetch(limit=80, window=window)

    assert client.calls[0][0] == "fetch_premarket_news"
    assert client.calls[0][1]["sources"] == ["tonghuashun"]
    assert client.calls[0][1]["limit_per_source"] == 80
    assert client.calls[0][1]["window"]["trading_day"] == "2026-06-15"
    assert result.source == "premarket-crawler-mcp"
    assert result.items[0].title == "MCP新闻"
    assert result.items[0].provider_name == "tonghuashun"


def test_mcp_crawler_provider_falls_back_to_local_provider_when_client_fails():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    provider = McpPremarketCrawlerProvider(
        client=RaisingMcpToolClient(),
        sources=["tonghuashun"],
        fallback_provider=FallbackProvider(),
    )

    result = provider.fetch(limit=80, window=window)

    assert result.source == "fallback"
    assert result.items[0].title == "本地降级新闻"


def test_local_crawler_provider_maps_contract_items_to_host_news_items():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    provider = LocalPremarketCrawlerProvider(service=StaticCrawlerService(), sources=["tonghuashun"])

    result = provider.fetch(limit=80, window=window)

    assert result.source == "premarket-crawler-mcp"
    assert result.items[0].title == "适配器新闻"
    assert result.items[0].provider_name == "tonghuashun"
