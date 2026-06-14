import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trading_agent_system.agents.premarket_agent.news_provider import (
    AStockDataPremarketProvider,
    FetchWindow,
)


def _window() -> FetchWindow:
    china_tz = ZoneInfo("Asia/Shanghai")
    return FetchWindow(
        mode="premarket",
        trading_day=date(2026, 6, 9),
        previous_trading_day=date(2026, 6, 8),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 8, 15, 0, tzinfo=china_tz),
        window_end=datetime(2026, 6, 9, 9, 30, tzinfo=china_tz),
    )


def test_a_stock_data_provider_maps_rows_to_news_items():
    published_at = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [
            {
                "title": "半导体强势股活跃",
                "theme": "半导体",
                "symbol": "688981.SH",
                "summary": "国产替代与政策催化",
                "published_at": published_at,
            }
        ],
        stock_news_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际获得设备采购订单",
                "summary": "订单扩张，需等待公告确认。",
                "symbol": "688981.SH",
                "url": "https://example.test/news",
                "published_at": published_at,
            }
        ],
        announcement_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际关于设备采购合同的公告",
                "summary": "临时公告",
                "symbol": "688981.SH",
                "url": "https://example.test/ann",
                "published_at": published_at,
            }
        ],
        quote_candidate_fetcher=lambda symbols, limit: [
            {
                "title": "中芯国际盘前观察候选",
                "summary": "参考价 90.0，目标价 94.5，止损 87.3。",
                "symbol": "688981.SH",
                "theme": "半导体",
                "published_at": published_at,
            }
        ],
        symbols=["688981.SH"],
    )

    result = provider.fetch(limit=10, window=_window())

    assert result.source == "a-stock-data/premarket"
    assert result.status == "ok"
    assert [item.category for item in result.items] == [
        "theme_hotspot",
        "stock_news",
        "announcement",
        "quote_candidate",
    ]
    assert result.items[0].sectors == ["半导体"]
    assert result.items[0].symbols == ["688981.SH"]
    assert result.items[2].source_tier == "official"


def test_a_stock_data_provider_returns_failed_result_when_fetcher_raises():
    def boom(limit):
        raise RuntimeError("upstream timeout")

    provider = AStockDataPremarketProvider(
        hotspot_fetcher=boom,
        symbols=["688981.SH"],
    )

    result = provider.fetch(limit=5)

    assert result.source == "a-stock-data/premarket"
    assert result.status == "failed"
    assert result.items == []
    assert "upstream timeout" in (result.error or "")


def test_a_stock_data_provider_filters_items_outside_premarket_window():
    inside = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    outside = datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc)
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [
            {"title": "窗口内热点", "theme": "半导体", "published_at": inside},
            {"title": "窗口外热点", "theme": "半导体", "published_at": outside},
        ],
    )

    result = provider.fetch(limit=10, window=_window())

    assert [item.title for item in result.items] == ["窗口内热点"]


def test_a_stock_data_provider_builds_quote_candidate_rows_from_adapter():
    class FakeAdapter:
        def candidates_for_theme(self, theme: str, limit: int = 3):
            class Candidate:
                symbol = "688981.SH"
                name = "中芯国际"
                theme = "半导体"
                reference_price = 90.0
                target_price = 94.5
                stop_loss = 87.3
                data_source = "a-stock-data/tencent"

            return [Candidate()]

    provider = AStockDataPremarketProvider(
        symbols=["688981.SH"],
        theme_symbols={"半导体": ["688981.SH"]},
        stock_data_adapter=FakeAdapter(),
    )

    rows = provider._fetch_quote_candidates(["688981.SH"], limit=5)

    assert rows[0]["published_at"] is not None
    assert {key: value for key, value in rows[0].items() if key != "published_at"} == (
        {
            "title": "中芯国际(688981.SH) 盘前观察候选",
            "summary": "半导体候选，参考价 90.0，目标价 94.5，止损 87.3，来源 a-stock-data/tencent。",
            "symbol": "688981.SH",
            "theme": "半导体",
        }
    )


def test_a_stock_data_provider_keeps_generated_quote_candidates_inside_window():
    class FakeAdapter:
        def candidates_for_theme(self, theme: str, limit: int = 3):
            class Candidate:
                symbol = "688981.SH"
                name = "中芯国际"
                theme = "半导体"
                reference_price = 90.0
                target_price = 94.5
                stop_loss = 87.3
                data_source = "a-stock-data/tencent"

            return [Candidate()]

    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [],
        stock_news_fetcher=lambda symbols, limit: [],
        announcement_fetcher=lambda symbols, limit: [],
        symbols=["688981.SH"],
        theme_symbols={"半导体": ["688981.SH"]},
        stock_data_adapter=FakeAdapter(),
    )

    result = provider.fetch(limit=5, window=_window())

    assert result.status == "ok"
    assert result.items[0].category == "quote_candidate"
    assert result.items[0].published_at is not None


def test_a_stock_data_quote_candidates_are_not_capped_at_twenty_when_limit_is_none():
    class FakeAdapter:
        def candidates_for_theme(self, theme: str, limit: int = 3):
            return [
                SimpleNamespace(
                    symbol=f"{index:06d}.SZ",
                    name=f"{theme}-{index}",
                    theme=theme,
                    reference_price=10.0,
                    target_price=10.5,
                    stop_loss=9.7,
                    data_source="a-stock-data/test",
                )
                for index in range(limit)
            ]

    provider = AStockDataPremarketProvider(
        theme_symbols={f"theme-{index}": [f"{index:06d}.SZ"] for index in range(8)},
        stock_data_adapter=FakeAdapter(),
    )

    rows = provider._fetch_quote_candidates([], limit=None)

    assert len(rows) == 24


def test_a_stock_data_stock_news_fetcher_requests_fifty_rows_by_default(monkeypatch):
    captured_payload = {}
    provider = AStockDataPremarketProvider(symbols=["688981.SH"], eastmoney_delay_seconds=0)

    def fake_get_text(url, params=None, **kwargs):
        captured_payload.update(json.loads(params["param"]))
        return 'jQuery_news({"result":{"cmsArticleWebOld":[]}})'

    monkeypatch.setattr(provider, "_get_text", fake_get_text)

    provider._fetch_stock_news(["688981.SH"], limit=None)

    assert captured_payload["param"]["cmsArticleWebOld"]["pageSize"] == 50


def test_a_stock_data_hotspot_fetcher_maps_tonghuashun_rows(monkeypatch):
    provider = AStockDataPremarketProvider(
        stock_news_fetcher=lambda symbols, limit: [],
        announcement_fetcher=lambda symbols, limit: [],
        quote_candidate_fetcher=lambda symbols, limit: [],
    )
    monkeypatch.setattr(
        provider,
        "_get_text",
        lambda *args, **kwargs: '{"errocode":0,"data":[{"code":"688981","name":"中芯国际","reason":"芯片+国产替代","zhangfu":"5.2"}]}',
    )

    result = provider.fetch(limit=5, window=_window())

    assert result.status == "ok"
    assert result.items[0].category == "theme_hotspot"
    assert result.items[0].title == "中芯国际(688981.SH) 同花顺强势股"
    assert result.items[0].symbols == ["688981.SH"]
    assert result.items[0].sectors == ["芯片"]


def test_a_stock_data_stock_news_fetcher_maps_eastmoney_jsonp(monkeypatch):
    provider = AStockDataPremarketProvider(symbols=["688981.SH"])
    monkeypatch.setattr(
        provider,
        "_get_text",
        lambda *args, **kwargs: (
            'jQuery_news({"result":{"cmsArticleWebOld":[{'
            '"title":"<em>中芯国际</em>扩产进展",'
            '"content":"设备采购进入新阶段",'
            '"date":"2026-06-08 16:30:00",'
            '"mediaName":"东方财富",'
            '"url":"https://example.test/em"}]}})'
        ),
    )

    rows = provider._fetch_stock_news(["688981.SH"], limit=2)

    assert rows == [
        {
            "title": "中芯国际扩产进展",
            "summary": "设备采购进入新阶段",
            "symbol": "688981.SH",
            "theme": None,
            "url": "https://example.test/em",
            "published_at": datetime(2026, 6, 8, 8, 30, tzinfo=timezone.utc),
        }
    ]


def test_a_stock_data_announcement_fetcher_maps_cninfo_rows(monkeypatch):
    provider = AStockDataPremarketProvider(symbols=["688981.SH"])
    monkeypatch.setattr(provider, "_cninfo_orgid", lambda code: "9900041602")
    monkeypatch.setattr(
        provider,
        "_post_form_json",
        lambda *args, **kwargs: {
            "announcements": [
                    {
                        "announcementTitle": "中芯国际关于设备采购合同的公告",
                        "announcementTypeName": "临时公告",
                        "announcementTime": 1780905600000,
                        "announcementId": "12345",
                    }
                ]
        },
    )

    rows = provider._fetch_announcements(["688981.SH"], limit=2)

    assert rows == [
        {
            "title": "中芯国际关于设备采购合同的公告",
            "summary": "临时公告",
            "symbol": "688981.SH",
            "theme": None,
            "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=12345",
            "published_at": datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc),
        }
    ]
