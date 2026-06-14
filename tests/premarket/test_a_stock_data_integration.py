from datetime import date, datetime, timezone

from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.news_provider import AStockDataPremarketProvider, NewsProviderResult
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.market_data.a_stock_data import AStockCandidate
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.schemas import PremarketNewsItem


class SemiconductorProvider:
    source = "local"

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        return NewsProviderResult(
            self.source,
            [
                PremarketNewsItem(
                    source="local official",
                    source_tier="official",
                    title="证监会支持半导体融资",
                    summary="政策支持半导体企业扩产增长。",
                    published_at=datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc),
                    category="official_policy",
                    sectors=["半导体"],
                    credibility=0.94,
                )
            ],
            "ok",
        )


class FakeStockDataAdapter:
    def __init__(self) -> None:
        self.themes: list[str] = []

    def candidates_for_theme(self, theme: str, limit: int = 3) -> list[AStockCandidate]:
        self.themes.append(theme)
        return [
            AStockCandidate(
                symbol="688981.SH",
                name="中芯国际",
                theme="半导体",
                reference_price=90.0,
                entry_low=89.1,
                entry_high=91.8,
                target_price=94.5,
                stop_loss=87.3,
                data_source="a-stock-data/tencent",
                score=1.0,
            )
        ][:limit]


def test_premarket_agent_uses_a_stock_data_candidates_for_bullish_theme(tmp_path):
    bus = DurableEventBus(repository=JsonlEventRepository(tmp_path / "events"))
    stock_data_adapter = FakeStockDataAdapter()
    agent = PremarketAgent(
        event_bus=bus,
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        providers=[SemiconductorProvider()],
        calendar=TradingCalendarService(),
        stock_data_adapter=stock_data_adapter,
    )

    report = agent.run(date(2026, 6, 9), limit_per_source=5)

    assert "半导体" in stock_data_adapter.themes
    assert report.watchlist
    assert report.watchlist[0].symbol == "688981.SH"
    assert report.watchlist[0].name == "中芯国际"
    assert report.watchlist[0].theme == "半导体"
    assert report.watchlist[0].reference_price == 90.0
    assert report.watchlist[0].target_price == 94.5
    assert report.watchlist[0].data_source == "a-stock-data/tencent"
    assert all(not item.symbol.startswith("板块:") for item in report.watchlist)


def test_premarket_agent_uses_a_stock_data_news_provider(tmp_path):
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
        stock_news_fetcher=lambda symbols, limit: [],
        announcement_fetcher=lambda symbols, limit: [],
        quote_candidate_fetcher=lambda symbols, limit: [],
        symbols=["688981.SH"],
    )
    agent = PremarketAgent(
        event_bus=DurableEventBus(repository=JsonlEventRepository(tmp_path / "events")),
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        providers=[provider],
        calendar=TradingCalendarService(),
    )

    report = agent.run(date(2026, 6, 9), limit_per_source=5)

    assert report.source_status[0].source == "a-stock-data/premarket"
    assert report.source_status[0].status == "ok"
    assert report.news_items[0].category == "theme_hotspot"
    assert any(catalyst.sectors == ["半导体"] for catalyst in report.catalysts)


def test_premarket_agent_keeps_a_stock_data_quote_candidates_in_watchlist(tmp_path):
    published_at = datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    provider = AStockDataPremarketProvider(
        hotspot_fetcher=lambda limit: [],
        stock_news_fetcher=lambda symbols, limit: [],
        announcement_fetcher=lambda symbols, limit: [],
        quote_candidate_fetcher=lambda symbols, limit: [
            {
                "title": "SMIC(688981.SH) premarket observation candidate",
                "summary": "reference price 90.0, target 94.5, stop 87.3",
                "symbol": "688981.SH",
                "theme": "semiconductor",
                "published_at": published_at,
            }
        ],
        symbols=["688981.SH"],
    )
    agent = PremarketAgent(
        event_bus=DurableEventBus(repository=JsonlEventRepository(tmp_path / "events")),
        audit=AuditLedger(tmp_path / "audit.jsonl"),
        providers=[provider],
        calendar=TradingCalendarService(),
    )

    report = agent.run(date(2026, 6, 9), limit_per_source=5)

    assert any(catalyst.category == "quote_candidate" and catalyst.bias == "neutral" for catalyst in report.catalysts)
    assert [item.symbol for item in report.watchlist] == ["688981.SH"]
    assert report.watchlist[0].reason == "SMIC(688981.SH) premarket observation candidate"
