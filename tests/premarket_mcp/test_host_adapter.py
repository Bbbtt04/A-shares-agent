from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import CrawlerResponseContract, FetchWindowContract, PremarketNewsItemContract
from trading_agent_system.agents.premarket_agent.crawler_adapter import LocalPremarketCrawlerProvider


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
