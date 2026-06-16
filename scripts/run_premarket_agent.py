from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import TextIO

from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.news_provider import (
    AStockDataPremarketProvider,
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
from trading_agent_system.core.market_data import AStockDataAdapter
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.reference import ThemeRegistry
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService


DEFAULT_PROVIDER_NAMES = [
    "tonghuashun",
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
        stock_data_adapter=AStockDataAdapter(),
    )
    report = agent.run(report_date=report_date, limit_per_source=resolve_limit_per_source(app_config, args.limit))
    write_report(report, app_config)
    write_json_stdout(report.model_dump(mode="json"))


def build_providers(app_config: dict[str, object]) -> list[object]:
    premarket = app_config.get("premarket", {})
    provider_names = premarket.get("providers", []) if isinstance(premarket, dict) else []
    names = provider_names if isinstance(provider_names, list) and provider_names else DEFAULT_PROVIDER_NAMES
    providers: list[object] = []
    for name in names:
        provider = make_provider(str(name))
        if provider is not None:
            providers.append(provider)
    if not providers:
        providers = [provider for name in DEFAULT_PROVIDER_NAMES if (provider := make_provider(name)) is not None]
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
    a_stock_data_provider = build_a_stock_data_provider(app_config)
    if a_stock_data_provider is not None:
        providers.append(a_stock_data_provider)
    return providers


def build_a_stock_data_provider(app_config: dict[str, object]) -> object | None:
    premarket = app_config.get("premarket", {})
    config = premarket.get("a_stock_data", {}) if isinstance(premarket, dict) else {}
    if not isinstance(config, dict) or not config.get("enabled", False):
        return None
    symbols = [str(symbol) for symbol in config.get("symbols", []) if symbol]
    registry = ThemeRegistry.default()
    return AStockDataPremarketProvider(
        symbols=symbols,
        theme_symbols=registry.theme_symbols,
        stock_data_adapter=AStockDataAdapter(),
    )


def make_provider(name: str) -> object | None:
    if name == "csrc":
        return CsrcNewsProvider()
    if name == "eastmoney":
        return EastMoneyNewsProvider()
    if name == "sina":
        return SinaFinanceRollProvider()
    if name == "sina_finance":
        return SinaFinanceRollProvider(source="新浪财经滚动", lid="2516", category="sina_finance")
    if name == "sina_stock":
        return SinaFinanceRollProvider(source="新浪股票滚动", lid="2517", category="sina_stock")
    if name == "sina_global":
        return SinaFinanceRollProvider(source="新浪全球财经", lid="2518", category="sina_global")
    if name == "cailianpress":
        return CailianpressTelegraphProvider()
    if name == "kaipanla":
        return KaipanlaNewsProvider()
    if name == "tonghuashun":
        return TonghuashunNewsProvider()
    if name == "xueqiu":
        return XueqiuHotProvider()
    return None


def resolve_limit_per_source(app_config: dict[str, object], cli_limit: int | None = None) -> int | None:
    if cli_limit is not None:
        return cli_limit if cli_limit > 0 else None
    premarket = app_config.get("premarket", {})
    if isinstance(premarket, dict):
        configured = premarket.get("limit_per_source")
        if isinstance(configured, int):
            return configured if configured > 0 else None
    return None


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


def write_json_stdout(payload: object, stdout: TextIO | None = None) -> None:
    stream = stdout or sys.stdout
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    if encoding and encoding != "utf8":
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            buffer.write(text.encode("utf-8"))
            buffer.flush()
            return
    stream.write(text)
    stream.flush()


if __name__ == "__main__":
    main()
