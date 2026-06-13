from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import FetchWindowContract, PremarketNewsItemContract
from premarket_crawler_mcp.service import PremarketCrawlerService


class StaticProvider:
    source = "测试源"
    provider_name = "static"

    def fetch(self, limit=30, window=None):
        from premarket_contracts import CrawlerProviderResultContract

        return CrawlerProviderResultContract(
            source=self.source,
            provider_name=self.provider_name,
            items=[
                PremarketNewsItemContract(
                    source=self.source,
                    source_tier="professional",
                    title="窗口内",
                    published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )
            ][:limit],
        )


class FailingProvider:
    source = "失败源"
    provider_name = "failing"

    def fetch(self, limit=30, window=None):
        raise RuntimeError("boom")


def test_service_fetches_sources_and_keeps_failed_source_status():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    service = PremarketCrawlerService(provider_factories={"static": StaticProvider, "failing": FailingProvider})

    response = service.fetch_premarket_news(["static", "failing"], limit_per_source=10, window=window)

    assert response.status == "partial"
    assert [item.title for item in response.items] == ["窗口内"]
    assert [(status.provider_name, status.status) for status in response.source_status] == [
        ("static", "ok"),
        ("failing", "failed"),
    ]
    assert response.warnings == ["failing: boom"]
