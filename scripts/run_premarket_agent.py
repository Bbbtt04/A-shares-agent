from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from trading_agent_system.agents.premarket_agent import PremarketAgent
from trading_agent_system.agents.premarket_agent.news_provider import (
    CailianpressTelegraphProvider,
    CsrcNewsProvider,
    DemoPremarketNewsProvider,
    EastMoneyNewsProvider,
    RssNewsProvider,
    SinaFinanceRollProvider,
)
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.knowledge import KnowledgeStore, RagIndexer
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.agents.premarket_agent.trading_calendar import TradingCalendarService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config", default="configs/app.yaml")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    app_config = load_yaml_config(args.config)
    report_date = date.fromisoformat(args.date)
    providers = [DemoPremarketNewsProvider()] if args.demo else build_providers(app_config)
    calendar_config = load_calendar_config(app_config)
    calendar = TradingCalendarService.from_config(calendar_config)
    audit = AuditLedger(app_config["paths"]["audit_log"])
    event_repository = JsonlEventRepository()
    knowledge_store = KnowledgeStore()
    agent = PremarketAgent(
        event_bus=DurableEventBus(repository=event_repository),
        audit=audit,
        providers=providers,
        calendar=calendar,
        trace_logger=TraceLogger(),
        metrics=MetricsRecorder(),
        knowledge_indexer=RagIndexer(knowledge_store),
    )
    report = agent.run(report_date=report_date, limit_per_source=args.limit)
    write_report(report, app_config)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


def build_providers(app_config: dict[str, object]) -> list[object]:
    premarket = app_config.get("premarket", {})
    provider_names = premarket.get("providers", []) if isinstance(premarket, dict) else []
    providers: list[object] = []
    for name in provider_names if isinstance(provider_names, list) else []:
        if name == "csrc":
            providers.append(CsrcNewsProvider())
        elif name == "eastmoney":
            providers.append(EastMoneyNewsProvider())
        elif name == "sina":
            providers.append(SinaFinanceRollProvider())
        elif name == "cailianpress":
            providers.append(CailianpressTelegraphProvider())
    if not providers:
        providers = [CsrcNewsProvider(), EastMoneyNewsProvider(), SinaFinanceRollProvider(), CailianpressTelegraphProvider()]
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


def load_calendar_config(app_config: dict[str, object]) -> dict[str, object]:
    configs = app_config.get("configs", {})
    premarket_path = configs.get("premarket") if isinstance(configs, dict) else None
    if premarket_path:
        return load_yaml_config(str(premarket_path))
    premarket = app_config.get("premarket", {})
    return premarket if isinstance(premarket, dict) else {}


def write_report(report: object, app_config: dict[str, object]) -> None:
    base = Path(str(app_config["paths"]["reports"])).parent / "premarket"
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{report.date.isoformat()}.json"
    md_path = base / f"{report.date.isoformat()}.md"
    json_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report.markdown_report, encoding="utf-8")


if __name__ == "__main__":
    main()
