from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import (
    CrawlerProviderResultContract,
    FetchWindowContract,
    PremarketNewsItemContract,
)


def test_fetch_window_filters_items_by_china_time_window():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    inside = PremarketNewsItemContract(
        source="同花顺7x24",
        source_tier="professional",
        title="窗口内新闻",
        published_at=datetime(2026, 6, 15, 8, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    outside = PremarketNewsItemContract(
        source="同花顺7x24",
        source_tier="professional",
        title="窗口外新闻",
        published_at=datetime(2026, 6, 15, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert window.filter_items([inside, outside]) == [inside]


def test_provider_result_builds_source_status():
    result = CrawlerProviderResultContract(
        source="同花顺7x24",
        provider_name="tonghuashun",
        items=[
            PremarketNewsItemContract(
                source="同花顺7x24",
                source_tier="professional",
                title="新闻",
            )
        ],
    )

    status = result.source_status(used_count=1)

    assert status.source == "同花顺7x24"
    assert status.provider_name == "tonghuashun"
    assert status.fetched_count == 1
    assert status.used_count == 1
