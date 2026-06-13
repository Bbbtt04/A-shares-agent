from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for package_path in (
    ROOT / "packages" / "premarket-contracts",
    ROOT / "packages" / "premarket-crawler-mcp",
):
    package_path_str = str(package_path)
    if package_path.exists() and package_path_str not in sys.path:
        sys.path.insert(0, package_path_str)

from premarket_crawler_mcp.registry import build_rss_provider_factory, default_provider_factories
from premarket_crawler_mcp.service import PremarketCrawlerService
from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.crawler_adapter import LocalPremarketCrawlerProvider
from trading_agent_system.agents.premarket_agent.news_provider import (
    CailianpressTelegraphProvider,
    CsrcNewsProvider,
    DemoPremarketNewsProvider,
    EastMoneyNewsProvider,
    KaipanlaNewsProvider,
    RssNewsProvider,
    SinaFinanceRollProvider,
    TonghuashunNewsProvider,
    XueqiuHotProvider,
)
from trading_agent_system.agents.premarket_agent.rag.rag_service import PreMarketRAGService
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.knowledge import KnowledgeStore, RagIndexer
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService


DEFAULT_PREMARKET_SOURCES = [
    "csrc",
    "eastmoney",
    "sina_finance",
    "sina_stock",
    "sina_global",
    "tonghuashun",
    "cailianpress",
    "kaipanla",
    "xueqiu",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config", default="configs/app.yaml")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    app_config = load_yaml_config(args.config)
    report_date = date.fromisoformat(args.date)
    providers = [DemoPremarketNewsProvider()] if args.demo else build_providers(app_config)
    calendar_config = load_calendar_config(app_config)
    calendar = TradingCalendarService.from_config(calendar_config)
    audit = AuditLedger(app_config["paths"]["audit_log"])
    event_repository = JsonlEventRepository()
    knowledge_store = KnowledgeStore()
    premarket_rag_service = build_rag_service(app_config)
    agent = PremarketAgent(
        event_bus=DurableEventBus(repository=event_repository),
        audit=audit,
        providers=providers,
        calendar=calendar,
        trace_logger=TraceLogger(),
        metrics=MetricsRecorder(),
        knowledge_indexer=RagIndexer(knowledge_store),
        premarket_rag_service=premarket_rag_service,
    )
    report = agent.run(report_date=report_date, limit_per_source=resolve_limit_per_source(app_config, args.limit))
    write_report(report, app_config)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


def build_providers(app_config: dict[str, object]) -> list[object]:
    premarket = app_config.get("premarket", {})
    crawler = premarket.get("crawler", {}) if isinstance(premarket, dict) else {}
    mode = str(crawler.get("mode", "local")) if isinstance(crawler, dict) else "local"
    if mode != "legacy":
        return [build_crawler_provider(premarket if isinstance(premarket, dict) else {})]
    return build_legacy_providers(premarket if isinstance(premarket, dict) else {})


def build_crawler_provider(premarket_config: dict[str, object]) -> LocalPremarketCrawlerProvider:
    provider_names = premarket_config.get("providers", [])
    sources = [str(name) for name in provider_names] if isinstance(provider_names, list) else []
    if not sources:
        sources = list(DEFAULT_PREMARKET_SOURCES)

    factories = default_provider_factories()
    feeds = premarket_config.get("news_feeds", [])
    if isinstance(feeds, list):
        for index, feed in enumerate(feeds, start=1):
            if not isinstance(feed, dict) or not feed.get("url") or not feed.get("source"):
                continue
            name = f"rss_{index}_{str(feed['source']).lower().replace(' ', '_')}"
            factories[name] = build_rss_provider_factory(
                source=str(feed["source"]),
                url=str(feed["url"]),
                tier=str(feed.get("tier", "professional")),
            )
            sources.append(name)

    return LocalPremarketCrawlerProvider(
        service=PremarketCrawlerService(provider_factories=factories),
        sources=sources,
    )


def build_legacy_providers(premarket: dict[str, object]) -> list[object]:
    provider_names = premarket.get("providers", []) if isinstance(premarket, dict) else []
    providers: list[object] = []
    for name in provider_names if isinstance(provider_names, list) else []:
        if name == "csrc":
            providers.append(CsrcNewsProvider())
        elif name == "eastmoney":
            providers.append(EastMoneyNewsProvider())
        elif name == "sina":
            providers.append(SinaFinanceRollProvider())
        elif name == "sina_finance":
            providers.append(SinaFinanceRollProvider(source="新浪财经滚动", lid="2516", category="sina_finance"))
        elif name == "sina_stock":
            providers.append(SinaFinanceRollProvider(source="新浪股票滚动", lid="2517", category="sina_stock"))
        elif name == "sina_global":
            providers.append(SinaFinanceRollProvider(source="新浪全球财经", lid="2518", category="sina_global"))
        elif name == "cailianpress":
            providers.append(CailianpressTelegraphProvider())
        elif name == "kaipanla":
            providers.append(KaipanlaNewsProvider())
        elif name == "tonghuashun":
            providers.append(TonghuashunNewsProvider())
        elif name == "xueqiu":
            providers.append(XueqiuHotProvider())
    if not providers:
        providers = [
            CsrcNewsProvider(),
            EastMoneyNewsProvider(),
            SinaFinanceRollProvider(),
            CailianpressTelegraphProvider(),
            KaipanlaNewsProvider(),
            XueqiuHotProvider(),
        ]
    feeds = premarket.get("news_feeds", []) if isinstance(premarket, dict) else []
    if isinstance(feeds, list):
        for feed in feeds:
            if not isinstance(feed, dict) or not feed.get("url") or not feed.get("source"):
                continue
            providers.append(
                RssNewsProvider(
                    source=str(feed["source"]),
                    url=str(feed["url"]),
                    tier=str(feed.get("tier", "professional")),
                )
            )
    return providers


def resolve_limit_per_source(app_config: dict[str, object], cli_limit: int | None = None) -> int:
    if cli_limit is not None:
        return cli_limit
    premarket = app_config.get("premarket", {})
    if isinstance(premarket, dict):
        configured = premarket.get("limit_per_source")
        if isinstance(configured, int) and configured > 0:
            return configured
    return 30


def load_calendar_config(app_config: dict[str, object]) -> dict[str, object]:
    configs = app_config.get("configs", {})
    premarket_path = configs.get("premarket") if isinstance(configs, dict) else None
    if premarket_path:
        return load_yaml_config(str(premarket_path))
    premarket = app_config.get("premarket", {})
    return premarket if isinstance(premarket, dict) else {}


def build_rag_service(app_config: dict[str, object]) -> PreMarketRAGService | None:
    configs = app_config.get("configs", {})
    rag_path = configs.get("rag_premarket") if isinstance(configs, dict) else None
    path = Path(str(rag_path or "configs/rag.premarket.yaml"))
    if not path.exists():
        return None
    return PreMarketRAGService.from_config(load_yaml_config(path))


def write_report(report: object, app_config: dict[str, object]) -> None:
    base = Path(str(app_config["paths"]["reports"])).parent / "premarket"
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{report.date.isoformat()}.json"
    md_path = base / f"{report.date.isoformat()}.md"
    json_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report.markdown_report, encoding="utf-8")


if __name__ == "__main__":
    main()
