from datetime import date, datetime, timezone

from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.news_provider import NewsProviderResult
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.knowledge import KnowledgeStore, RagIndexer, RagRetriever
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.schemas import PremarketNewsItem


class LocalProvider:
    source = "local"

    def fetch(self, limit: int = 30) -> NewsProviderResult:
        return NewsProviderResult(
            self.source,
            [
                PremarketNewsItem(
                    source="local official",
                    source_tier="official",
                    title="证监会支持并购重组与半导体融资",
                    summary="政策支持半导体企业并购重组。",
                    published_at=datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc),
                    category="official_policy",
                    sectors=["半导体"],
                    credibility=0.94,
                ),
                PremarketNewsItem(
                    source="local professional",
                    source_tier="professional",
                    title="机器人公司收到监管函",
                    summary="相关标的存在监管函风险，盘前需要回避新开仓。",
                    published_at=datetime(2026, 6, 8, 17, 0, tzinfo=timezone.utc),
                    category="regulatory_inquiry",
                    sectors=["机器人"],
                    credibility=0.8,
                    risk_flags=["监管函"],
                ),
                PremarketNewsItem(
                    source="local stale",
                    source_tier="professional",
                    title="过期盘前消息",
                    summary="这条消息应当被窗口过滤，但仍要出现在全部爬取数据里。",
                    published_at=datetime(2026, 6, 7, 8, 0, tzinfo=timezone.utc),
                    category="stale_news",
                    credibility=0.5,
                )
            ],
            "ok",
        )


def test_premarket_agent_builds_spec_outputs(tmp_path):
    repository = JsonlEventRepository(tmp_path / "events")
    bus = DurableEventBus(repository=repository)
    audit = AuditLedger(tmp_path / "audit.jsonl")
    trace_logger = TraceLogger(tmp_path / "traces")
    metrics = MetricsRecorder(tmp_path / "metrics")
    knowledge_store = KnowledgeStore(tmp_path / "knowledge.sqlite")
    agent = PremarketAgent(
        event_bus=bus,
        audit=audit,
        providers=[LocalProvider()],
        calendar=TradingCalendarService(),
        trace_logger=trace_logger,
        metrics=metrics,
        knowledge_indexer=RagIndexer(knowledge_store),
    )

    report = agent.run(date(2026, 6, 9), limit_per_source=5)

    assert report.window_end.isoformat() == "2026-06-09T09:25:00+08:00"
    assert report.post_close_digest is not None
    assert report.morning_brief is not None
    assert report.opening_radar is not None
    assert report.instruction is not None
    assert report.instruction["items"]
    assert report.post_close_digest["theme_seeds"]
    assert report.post_close_digest["avoid_candidates"]
    assert report.morning_brief["top_themes"]
    assert report.morning_brief["avoid_list"]
    assert report.opening_radar["watch_items"] or report.opening_radar["risk_alerts"]
    crawled_documents = bus.events("premarket.crawled_documents")
    assert crawled_documents
    assert crawled_documents[0]["total_count"] == 3
    assert {item["title"] for item in crawled_documents[0]["items"]} >= {
        "证监会支持并购重组与半导体融资",
        "机器人公司收到监管函",
        "过期盘前消息",
    }
    assert {item["provider_name"] for item in crawled_documents[0]["items"]} == {"local"}
    assert any(item["title"] == "过期盘前消息" and not item["in_premarket_window"] for item in crawled_documents[0]["items"])
    assert report.source_status[0].provider_name == "local"
    assert "premarket.raw_documents" in bus.all_events()
    assert len(bus.events("premarket.raw_documents")[0]["value"]) == 2
    assert "premarket.normalized_events" in bus.all_events()
    assert "premarket.event_clusters" in bus.all_events()
    assert "premarket.morning_brief" in bus.all_events()
    assert "premarket.opening_radar" in bus.all_events()
    assert "premarket.instructions" in bus.all_events()
    assert repository.load_envelopes("premarket.instructions", trading_day=date(2026, 6, 9))
    assert trace_logger.load(agent="premarket_agent")
    assert metrics.load(name="agent_run_total")
    assert RagRetriever(knowledge_store).search(query="半导体", trading_day=date(2026, 6, 9), themes=["半导体"])
