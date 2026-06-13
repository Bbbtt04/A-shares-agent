from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from time import perf_counter
from zoneinfo import ZoneInfo

from premarket_contracts import FetchWindowContract

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.knowledge import RagIndexer
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.reference import ThemeRegistry
from trading_agent_system.schemas import (
    PremarketCatalyst,
    PremarketNewsItem,
    PremarketReport,
    PremarketSourceStatus,
    PremarketTradePlan,
    make_id,
)

from .news_provider import NewsProviderResult
from .builders import RiskFilter, ScenarioBuilder, ThemeDetector
from .pipeline import EventClusterer, EventScorer
from .rag.evaluation import RAGEvaluator
from .rag.rag_service import PreMarketRAGService
from .schemas import (
    Actionability,
    AuctionSignal,
    Bias,
    EventCluster,
    Importance,
    InstructionType,
    MorningBrief,
    OpeningRadar,
    PostCloseDigest,
    PreMarketEvent,
    PreMarketInstruction,
    PreMarketInstructionItem,
    PreMarketWindow,
    RawDocument,
    SourceRank,
)
from .trading_calendar import TradingCalendarService


CHINA_TZ = ZoneInfo("Asia/Shanghai")

POSITIVE_WORDS = {"支持", "利好", "增长", "增持", "回购", "突破", "中标", "订单", "改善", "降准", "降息", "并购", "重组"}
NEGATIVE_WORDS = {"处罚", "调查", "减持", "亏损", "下滑", "风险", "退市", "立案", "暴跌", "违约", "终止"}
OFFICIAL_WORDS = {"证监会", "交易所", "上交所", "深交所", "北交所", "央行", "国务院", "发改委", "工信部"}
RISK_WORDS = {"传闻", "网传", "未经证实", "小作文", "澄清", "监管函", "问询函"}

SECTOR_KEYWORDS: dict[str, set[str]] = {
    "半导体": {"半导体", "芯片", "光刻", "晶圆", "存储"},
    "机器人": {"机器人", "人形机器人", "减速器", "伺服"},
    "低空经济": {"低空", "飞行汽车", "无人机", "eVTOL"},
    "算力": {"算力", "数据中心", "AI服务器", "液冷", "GPU"},
    "新能源": {"新能源", "储能", "锂电", "光伏", "风电"},
    "券商": {"券商", "证券", "投行", "并购重组"},
    "医药": {"医药", "创新药", "医疗器械", "集采"},
    "消费": {"消费", "白酒", "食品", "旅游", "免税"},
}

SYMBOL_KEYWORDS: dict[str, str] = {
    "贵州茅台": "600519.SH",
    "宁德时代": "300750.SZ",
    "比亚迪": "002594.SZ",
    "中芯国际": "688981.SH",
    "工业富联": "601138.SH",
    "东方财富": "300059.SZ",
    "寒武纪": "688256.SH",
    "北方华创": "002371.SZ",
}


def _premarket_window_id(window: PreMarketWindow) -> str:
    return f"pmw_{window.trading_day.isoformat()}"


def _evidence_ids_from_packs(packs: list[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    evidence_ids: list[str] = []
    for pack in packs:
        items = pack.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("evidence_id"):
                evidence_id = str(item["evidence_id"])
                if evidence_id in seen:
                    continue
                seen.add(evidence_id)
                evidence_ids.append(evidence_id)
    return evidence_ids


def _unique_strings(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for group in groups:
        for value in group:
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
    return values


def _instruction_refs(
    brief: MorningBrief,
    radar: OpeningRadar,
    *event_id_groups: list[str],
) -> tuple[list[str], list[str]]:
    evidence_event_ids = _unique_strings(*event_id_groups)
    source_ids = _unique_strings(brief.source_ids, radar.source_ids)
    if not evidence_event_ids and not source_ids:
        source_ids = ["system"]
    return evidence_event_ids, source_ids


class PremarketAgent:
    def __init__(
        self,
        event_bus: MemoryEventBus,
        audit: AuditLedger,
        providers: list[object],
        calendar: TradingCalendarService | None = None,
        trace_logger: TraceLogger | None = None,
        metrics: MetricsRecorder | None = None,
        knowledge_indexer: RagIndexer | None = None,
        premarket_rag_service: PreMarketRAGService | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.audit = audit
        self.providers = providers
        self.calendar = calendar or TradingCalendarService()
        self.trace_logger = trace_logger
        self.metrics = metrics
        self.knowledge_indexer = knowledge_indexer
        self.premarket_rag_service = premarket_rag_service
        self.scorer = EventScorer()
        self.clusterer = EventClusterer()
        self.theme_detector = ThemeDetector()
        self.risk_filter = RiskFilter()
        self.scenario_builder = ScenarioBuilder()
        self.theme_registry = ThemeRegistry.default()

    def run(self, report_date: date, limit_per_source: int = 30) -> PremarketReport:
        run_id = make_id("pmrun")
        started = perf_counter()
        window = self.calendar.build_window(report_date)
        self.audit.write("premarket_window_built", window)
        self._trace(
            run_id=run_id,
            step="build_window",
            status="success",
            output_refs=[window.trading_day.isoformat()],
            decision_summary=f"{window.window_start.isoformat()} -> {window.continuous_open.isoformat()}",
        )
        fetch_window = self.calendar.build_fetch_window(report_date, mode="premarket")
        crawled: list[PremarketNewsItem] = []
        collected: list[PremarketNewsItem] = []
        statuses: list[PremarketSourceStatus] = []
        for provider in self.providers:
            result = self._fetch_provider(provider, limit_per_source, fetch_window)
            provider_items = [
                item.model_copy(update={"provider_name": item.provider_name or result.source})
                for item in fetch_window.filter_items(result.items)
            ]
            result.items = provider_items
            crawled.extend(provider_items)
            self._metric(
                "data_source_fetch_total",
                1,
                tags={"agent": "premarket", "source": result.source, "status": result.status},
                run_id=run_id,
            )
            self.audit.write(
                "premarket_provider_fetched",
                {
                    "source": result.source,
                    "status": result.status,
                    "fetched_count": len(result.items),
                    "error": result.error,
                },
            )
            filtered = provider_items
            enriched = [self._enrich(item) for item in filtered]
            collected.extend(enriched)
            provider_source_status = getattr(provider, "last_source_status", None)
            if provider_source_status:
                statuses.extend(provider_source_status)
            else:
                statuses.append(result.source_status(used_count=len(enriched)))
            self.audit.write(
                "premarket_provider_filtered",
                {"source": result.source, "used_count": len(enriched), "window": window.model_dump(mode="json")},
            )

        collected = self._dedupe(collected)
        self._trace(
            run_id=run_id,
            step="collect_sources",
            status="success",
            output_refs=[item.item_id for item in collected[:20]],
            decision_summary=f"collected={len(collected)}, sources={len(statuses)}",
        )
        raw_documents = self._to_raw_documents(collected)
        events = self._to_events(collected, raw_documents, window)
        clusters = self.clusterer.cluster(events)
        self.audit.write("premarket_event_clusters_created", {"count": len(clusters)})
        self._trace(
            run_id=run_id,
            step="normalize_and_cluster",
            status="success",
            input_refs=[document.source_id for document in raw_documents[:20]],
            output_refs=[cluster.cluster_id for cluster in clusters[:20]],
            evidence_ids=[event.event_id for event in events[:20]],
            decision_summary=f"events={len(events)}, clusters={len(clusters)}",
        )
        theme_seeds = self.theme_detector.detect(clusters)
        avoid_candidates = self.risk_filter.build_avoid_candidates(clusters)
        scenarios = self.scenario_builder.build(window, theme_seeds, avoid_candidates)
        post_close_digest = self._build_post_close_digest(window, events, clusters, theme_seeds, avoid_candidates)
        catalysts = self._build_catalysts(collected)
        morning_brief = self._build_morning_brief(window, catalysts, events, statuses, post_close_digest, theme_seeds, avoid_candidates, scenarios)
        opening_radar = self._build_opening_radar(window, morning_brief)
        watchlist = self._build_watchlist(catalysts)
        avoid_list = self._build_avoid_list(collected, catalysts)
        warnings = self._warnings(statuses, collected)
        market_view = self._market_view(catalysts, warnings)
        instruction = self._build_instruction(window, morning_brief, opening_radar, watchlist, avoid_list, warnings)
        report = PremarketReport(
            date=report_date,
            window_start=window.window_start,
            window_end=fetch_window.window_end,
            market_view=market_view,
            summary=self._summary(market_view, catalysts, warnings),
            source_status=statuses,
            news_items=collected[:80],
            catalysts=catalysts,
            watchlist=watchlist,
            avoid_list=avoid_list,
            opening_rules=self._opening_rules(),
            warnings=warnings,
            post_close_digest=post_close_digest.model_dump(mode="json"),
            morning_brief=morning_brief.model_dump(mode="json"),
            opening_radar=opening_radar.model_dump(mode="json"),
            instruction=instruction.model_dump(mode="json"),
        )
        report = report.model_copy(update={"markdown_report": render_premarket_markdown(report)})
        crawled_document_payloads = self._to_crawled_documents(crawled, fetch_window)
        raw_document_payloads = [document.model_dump(mode="json") for document in raw_documents]
        event_payloads = [event.model_dump(mode="json") for event in events]
        cluster_payloads = [cluster.model_dump(mode="json") for cluster in clusters]
        morning_brief_payload = morning_brief.model_dump(mode="json")
        instruction_payload = instruction.model_dump(mode="json")
        indexed_count = 0
        rag_pack_payloads: list[dict[str, object]] = []
        rag_evaluation_payload: dict[str, object] | None = None
        if self.knowledge_indexer is not None:
            records = self.knowledge_indexer.index_premarket_payload(
                trading_day=window.trading_day,
                raw_documents=raw_document_payloads,
                events=event_payloads,
                clusters=cluster_payloads,
                morning_brief=morning_brief_payload,
                instruction=instruction_payload,
            )
            indexed_count = len(records)
            self._metric("rag_index_records_total", indexed_count, tags={"agent": "premarket"}, run_id=run_id)
        if self.premarket_rag_service is not None:
            rag_documents = self.premarket_rag_service.index_payloads(
                trading_day=window.trading_day,
                premarket_window_id=_premarket_window_id(window),
                raw_documents=raw_document_payloads,
                events=event_payloads,
                clusters=cluster_payloads,
            )
            packs = self.premarket_rag_service.retrieve_all_evidence_packs(
                window.trading_day,
                _premarket_window_id(window),
            )
            evaluator = RAGEvaluator()
            evaluation_metrics = evaluator.evaluate_packs(packs)
            evaluation_summary = evaluator.summarize(evaluation_metrics)
            rag_pack_payloads = [pack.model_dump(mode="json") for pack in packs]
            rag_evaluation_payload = {
                "trading_day": window.trading_day.isoformat(),
                "premarket_window_id": _premarket_window_id(window),
                "metrics": [metric.model_dump(mode="json") for metric in evaluation_metrics],
                "summary": evaluation_summary,
            }
            self._metric("rag_qdrant_index_records_total", len(rag_documents), tags={"agent": "premarket"}, run_id=run_id)
            self._metric(
                "rag_evidence_token_estimate",
                sum(pack.token_estimate for pack in packs),
                tags={"agent": "premarket"},
                run_id=run_id,
            )
            self._metric(
                "rag_evidence_coverage_ratio",
                float(evaluation_summary["avg_evidence_coverage_ratio"]),
                tags={"agent": "premarket"},
                run_id=run_id,
            )
            self._metric(
                "rag_duplicate_ratio",
                float(evaluation_summary["avg_duplicate_ratio"]),
                tags={"agent": "premarket"},
                run_id=run_id,
            )
        self._trace(
            run_id=run_id,
            step="build_outputs",
            status="success",
            output_refs=[post_close_digest.digest_id, morning_brief.brief_id, opening_radar.radar_id, instruction.instruction_id],
            evidence_ids=[event.event_id for event in events[:20]],
            decision_summary=f"themes={len(theme_seeds)}, avoid={len(avoid_candidates)}, indexed={indexed_count}",
        )
        self._publish(
            "premarket.crawled_documents",
            {
                "total_count": len(crawled_document_payloads),
                "window_start": fetch_window.window_start.isoformat(),
                "window_end": fetch_window.window_end.isoformat(),
                "items": crawled_document_payloads,
            },
            window,
            run_id,
            [item["item_id"] for item in crawled_document_payloads[:100] if item.get("item_id")],
        )
        self._publish("premarket.raw_documents", raw_document_payloads, window, run_id)
        self._publish("premarket.normalized_events", event_payloads, window, run_id, [event.event_id for event in events])
        self._publish("premarket.event_clusters", cluster_payloads, window, run_id, [cluster.cluster_id for cluster in clusters])
        self._publish("premarket.post_close_digest", post_close_digest.model_dump(mode="json"), window, run_id, post_close_digest.source_ids)
        self._publish("premarket.morning_brief", morning_brief_payload, window, run_id, morning_brief.source_ids)
        self._publish("premarket.opening_radar", opening_radar.model_dump(mode="json"), window, run_id, opening_radar.source_ids)
        self._publish("premarket.instructions", instruction_payload, window, run_id, instruction.source_ids)
        if rag_pack_payloads:
            rag_evidence_event = {
                "trading_day": window.trading_day.isoformat(),
                "premarket_window_id": _premarket_window_id(window),
                "pack_count": len(rag_pack_payloads),
                "token_estimate": sum(int(pack.get("token_estimate") or 0) for pack in rag_pack_payloads),
                "packs": rag_pack_payloads,
            }
            self._publish(
                "premarket.rag_evidence_packs",
                rag_evidence_event,
                window,
                run_id,
                _evidence_ids_from_packs(rag_pack_payloads),
            )
        if rag_evaluation_payload is not None:
            self._publish(
                "premarket.rag_evaluation",
                rag_evaluation_payload,
                window,
                run_id,
                _evidence_ids_from_packs(rag_pack_payloads),
            )
        self._publish("premarket.reports", report, window, run_id, morning_brief.source_ids)
        self._metric("agent_run_total", 1, tags={"agent": "premarket", "status": "success"}, run_id=run_id)
        self._metric(
            "agent_run_duration_ms",
            int((perf_counter() - started) * 1000),
            tags={"agent": "premarket"},
            run_id=run_id,
        )
        self.audit.write("premarket_post_close_digest_created", post_close_digest)
        self.audit.write("premarket_morning_brief_created", morning_brief)
        self.audit.write("premarket_opening_radar_created", opening_radar)
        self.audit.write("premarket_instruction_created", instruction)
        self.audit.write("premarket_report_created", report)
        return report

    def _publish(
        self,
        topic: str,
        event: object,
        window: PreMarketWindow,
        run_id: str,
        evidence_ids: list[str] | None = None,
    ) -> None:
        self.event_bus.publish(
            topic,
            event,
            producer="premarket_agent",
            trading_day=window.trading_day,
            run_id=run_id,
            correlation_id=run_id,
            evidence_ids=evidence_ids,
        )

    def _trace(
        self,
        *,
        run_id: str,
        step: str,
        status: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        decision_summary: str = "",
        error: str | None = None,
    ) -> None:
        if self.trace_logger is None:
            return
        self.trace_logger.record(
            agent="premarket_agent",
            step=step,
            run_id=run_id,
            status=status,
            input_refs=input_refs,
            output_refs=output_refs,
            evidence_ids=evidence_ids,
            decision_summary=decision_summary,
            error=error,
        )

    def _metric(self, name: str, value: float, *, tags: dict[str, str], run_id: str) -> None:
        if self.metrics is None:
            return
        self.metrics.record(name, value, tags=tags, run_id=run_id)

    def _fetch_provider(self, provider: object, limit: int, fetch_window: FetchWindowContract) -> NewsProviderResult:
        try:
            return provider.fetch(limit=limit, window=fetch_window)
        except TypeError as error:
            if "window" not in str(error):
                raise
            return provider.fetch(limit=limit)

    def _to_crawled_documents(
        self,
        items: list[PremarketNewsItem],
        window: FetchWindowContract,
    ) -> list[dict[str, object]]:
        documents: list[dict[str, object]] = []
        for item in items:
            payload = item.model_dump(mode="json")
            payload["in_premarket_window"] = window.contains(item.published_at)
            documents.append(payload)
        self.audit.write("premarket_crawled_documents_collected", {"count": len(documents)})
        return documents

    def _to_raw_documents(self, items: list[PremarketNewsItem]) -> list[RawDocument]:
        documents = []
        for item in items:
            body = f"{item.source}|{item.title}|{item.url or ''}|{item.published_at or ''}"
            documents.append(
                RawDocument(
                    source_id=item.item_id,
                    source_name=item.source,
                    source_rank=self._source_rank(item),
                    title=item.title,
                    url=item.url,
                    external_id=item.url or item.item_id,
                    published_at=item.published_at,
                    fetched_at=item.collected_at,
                    content_hash=sha256(body.encode("utf-8")).hexdigest(),
                    raw_text=item.summary or item.title,
                    raw_payload=item.model_dump(mode="json"),
                    format="json",
                    symbols=item.symbols,
                    tags=[item.category, *item.sectors, *item.risk_flags],
                )
            )
        self.audit.write("premarket_raw_documents_normalized", {"count": len(documents)})
        return documents

    def _to_events(
        self,
        items: list[PremarketNewsItem],
        documents: list[RawDocument],
        window: PreMarketWindow,
    ) -> list[PreMarketEvent]:
        document_by_id = {document.source_id: document for document in documents}
        events = []
        for item in items:
            document = document_by_id[item.item_id]
            text = f"{item.title} {item.summary}"
            positive = sum(1 for word in POSITIVE_WORDS if word in text)
            negative = sum(1 for word in NEGATIVE_WORDS if word in text)
            bias = Bias.BULLISH if positive > negative else Bias.BEARISH if negative > positive else Bias.NEUTRAL
            event = PreMarketEvent(
                event_id=make_id("pmevt"),
                source_ids=[document.source_id],
                source_rank=document.source_rank,
                title=item.title,
                summary=item.summary or item.title,
                published_at=item.published_at,
                first_seen_at=item.collected_at,
                last_updated_at=item.collected_at,
                symbols=item.symbols,
                companies=[],
                event_type=item.category,
                related_themes=item.sectors,
                importance=self._event_importance(item, positive, negative),
                bias=bias,
                confidence=self.scorer.confidence(item, document.source_rank),
                actionability=self._event_actionability(item, bias),
                is_post_close=(item.published_at is None or item.published_at.astimezone(CHINA_TZ) >= window.window_start),
                is_watchlist_related=bool(item.symbols or item.sectors),
                evidence=[{"source_id": document.source_id, "url": item.url, "source": item.source}],
                risk_flags=item.risk_flags,
            )
            events.append(event)
        self.audit.write("premarket_events_normalized", {"count": len(events)})
        return events

    def _cluster_events(self, events: list[PreMarketEvent]) -> list[EventCluster]:
        grouped: dict[str, list[PreMarketEvent]] = {}
        for event in events:
            key = event.related_themes[0] if event.related_themes else event.symbols[0] if event.symbols else event.event_type
            grouped.setdefault(key, []).append(event)
        clusters = []
        for key, related in grouped.items():
            primary = sorted(related, key=lambda item: (item.importance, item.confidence), reverse=True)[0]
            clusters.append(
                EventCluster(
                    cluster_id=make_id("pmclu"),
                    primary_event_id=primary.event_id,
                    supporting_event_ids=[item.event_id for item in related if item.event_id != primary.event_id],
                    first_seen_at=min(item.first_seen_at for item in related),
                    last_updated_at=max(item.last_updated_at for item in related),
                    symbols=sorted({symbol for item in related for symbol in item.symbols}),
                    companies=[],
                    event_type=primary.event_type,
                    title=primary.title if key == primary.event_type else f"{key}: {primary.title}",
                    summary=primary.summary,
                    primary_source_rank=primary.source_rank,
                    evidence_count=len(related),
                    importance=primary.importance,
                    bias=primary.bias,
                    confidence=min(0.95, sum(item.confidence for item in related) / len(related) + 0.03 * (len(related) - 1)),
                    actionability=primary.actionability,
                    risk_flags=sorted({flag for item in related for flag in item.risk_flags}),
                )
            )
        self.audit.write("premarket_event_clusters_created", {"count": len(clusters)})
        return clusters

    def _build_post_close_digest(
        self,
        window: PreMarketWindow,
        events: list[PreMarketEvent],
        clusters: list[EventCluster],
        theme_seeds: list[object],
        avoid_candidates: list[object],
    ) -> PostCloseDigest:
        return PostCloseDigest(
            digest_id=make_id("pmdig"),
            trading_day=window.trading_day,
            previous_trading_day=window.previous_trading_day,
            window=window,
            generated_at=datetime.now(CHINA_TZ),
            events=events[:80],
            clusters=clusters[:30],
            event_clusters=clusters[:30],
            official_announcements=[event for event in events if event.source_rank == SourceRank.OFFICIAL.value],
            regulatory_events=[event for event in events if event.event_type.startswith("regulatory")],
            policy_events=[event for event in events if "policy" in event.event_type or event.source_rank == SourceRank.OFFICIAL.value],
            post_close_news=[event for event in events if event.source_rank == SourceRank.AUTHORIZED_NEWS.value],
            overseas_events=[event for event in events if event.source_rank == SourceRank.OVERSEAS.value],
            theme_seeds=theme_seeds[:12],
            avoid_candidates=avoid_candidates[:20],
            data_quality={
                "event_count": len(events),
                "cluster_count": len(clusters),
                "source_count": len({source_id for event in events for source_id in event.source_ids}),
            },
            risk_event_ids=[event.event_id for event in events if event.risk_flags or event.bias == Bias.BEARISH.value],
            risk_flags=sorted({flag for event in events for flag in event.risk_flags}),
            source_ids=sorted({source_id for event in events for source_id in event.source_ids}),
            summary=f"收盘后至盘前共归一化 {len(events)} 条事件，聚合为 {len(clusters)} 个主题。",
        )

    def _build_morning_brief(
        self,
        window: PreMarketWindow,
        catalysts: list[PremarketCatalyst],
        events: list[PreMarketEvent],
        statuses: list[PremarketSourceStatus],
        digest: PostCloseDigest,
        theme_seeds: list[object],
        avoid_candidates: list[object],
        scenarios: list[object],
    ) -> MorningBrief:
        warnings = self._warnings(statuses, [self._event_to_news_stub(event) for event in events])
        market_view = self._market_view(catalysts, warnings)
        key_themes = sorted({sector for catalyst in catalysts for sector in catalyst.sectors})[:8]
        top_events = sorted(events, key=lambda event: (self._importance_rank(event.importance), event.confidence), reverse=True)[:12]
        return MorningBrief(
            brief_id=make_id("pmbrf"),
            trading_day=window.trading_day,
            window=window,
            generated_at=datetime.now(CHINA_TZ),
            market_view=market_view,
            market_mode=self._market_mode(market_view, theme_seeds, warnings),
            headline=self._summary(market_view, catalysts, warnings),
            summary=self._summary(market_view, catalysts, warnings),
            post_close_digest={
                "digest_id": digest.digest_id,
                "summary": digest.summary,
                "event_count": len(digest.events),
                "cluster_count": len(digest.clusters),
            },
            key_post_close_events=digest.event_clusters[:10],
            announcement_events=digest.official_announcements[:10],
            policy_events=digest.policy_events[:10],
            overnight_summary=digest.post_close_news[:12],
            top_themes=theme_seeds[:8],
            avoid_list=avoid_candidates[:12],
            scenarios=scenarios[:8],
            instructions_preview=[{"target": item.symbol, "restriction": item.restriction, "reason": item.reason} for item in avoid_candidates[:6]],
            data_quality=digest.data_quality,
            top_event_ids=[event.event_id for event in top_events],
            key_themes=key_themes,
            risk_event_ids=[event.event_id for event in events if event.risk_flags or event.bias == Bias.BEARISH.value],
            watch_symbols=sorted({symbol for event in events if event.actionability in {Actionability.WATCH.value, Actionability.CANDIDATE.value} for symbol in event.symbols}),
            avoid_symbols=sorted({symbol for event in events if event.actionability == Actionability.BLOCK.value for symbol in event.symbols}),
            source_ids=sorted({source_id for event in events for source_id in event.source_ids}),
            warnings=warnings,
        )

    def _build_opening_radar(self, window: PreMarketWindow, brief: MorningBrief) -> OpeningRadar:
        signals = [
            AuctionSignal(
                symbol=symbol,
                observed_at=window.auction_observation_end,
                phase="observation",
                signal_type="watch_only",
                source_ids=brief.source_ids,
                reason="09:15-09:20 仅观察，不能确认盘前主题。",
            )
            for symbol in brief.watch_symbols[:12]
        ]
        if not signals and brief.top_themes:
            theme = brief.top_themes[0]
            signals.append(
                AuctionSignal(
                    symbol=f"主题:{theme.theme_name}",
                    observed_at=window.auction_observation_end,
                    phase="observation",
                    signal_type="watch_only",
                    evidence_event_ids=theme.evidence_event_ids,
                    source_ids=brief.source_ids,
                    reason="等待 09:20-09:25 竞价确认窗口验证。",
                )
            )
        watch_items = [
            {
                "symbol": symbol or f"主题:{theme.theme_name}",
                "theme": theme.theme_name,
                "rank_in_watchlist": theme.rank,
                "signal": "ignore",
                "evidence_event_ids": theme.evidence_event_ids,
                "notes": ["未接入 09:20-09:25 竞价数据，当前只保留观察，不确认强弱。"],
            }
            for theme in brief.top_themes[:8]
            for symbol in (theme.related_symbols[:3] or [""])
        ]
        risk_alerts = [
            {
                "symbol": item.symbol,
                "signal": "risk_alert",
                "evidence_event_ids": item.related_event_ids,
                "notes": [item.reason, f"restriction={item.restriction}"],
            }
            for item in brief.avoid_list[:8]
        ]
        return OpeningRadar(
            radar_id=make_id("pmrad"),
            trading_day=window.trading_day,
            generated_at=datetime.now(CHINA_TZ),
            confirm_window_start=window.auction_confirm_start,
            confirm_window_end=window.auction_end,
            confirmed_themes=[],
            failed_themes=[],
            signals=signals,
            risk_alerts=risk_alerts,
            watch_items=watch_items,
            avoid_items=risk_alerts,
            intraday_instructions=[
                {
                    "action": "require_confirmation",
                    "scope": "opening_auction",
                    "reason": "OpeningRadar 未接入确认窗口行情，只允许传递约束和观察项。",
                }
            ],
            rejected_theme_event_ids=[],
            source_ids=brief.source_ids,
            warnings=["当前 MVP 未接入 09:20-09:25 竞价数据，所有雷达信号保持 watch_only。"],
        )

    def _build_instruction(
        self,
        window: PreMarketWindow,
        brief: MorningBrief,
        radar: OpeningRadar,
        watchlist: list[PremarketTradePlan],
        avoid_list: list[PremarketTradePlan],
        warnings: list[str],
    ) -> PreMarketInstruction:
        items: list[PreMarketInstructionItem] = []
        for plan in watchlist[:12]:
            evidence_event_ids, source_ids = _instruction_refs(brief, radar, brief.top_event_ids[:5])
            items.append(
                PreMarketInstructionItem(
                    instruction_type=InstructionType.WATCH_OPENING_AUCTION,
                    target=plan.symbol,
                    reason=plan.reason,
                    evidence_event_ids=evidence_event_ids,
                    source_ids=source_ids,
                    expires_at=window.continuous_open,
                    requires_manual_review=bool(plan.risk_flags),
                )
            )
        for plan in avoid_list[:12]:
            evidence_event_ids, source_ids = _instruction_refs(
                brief,
                radar,
                brief.risk_event_ids[:5],
                brief.top_event_ids[:5],
            )
            items.append(
                PreMarketInstructionItem(
                    instruction_type=InstructionType.AVOID_NEW_ENTRY,
                    target=plan.symbol,
                    reason=plan.reason,
                    evidence_event_ids=evidence_event_ids,
                    source_ids=source_ids,
                    expires_at=window.continuous_open,
                    requires_manual_review=True,
                )
            )
        if warnings:
            evidence_event_ids, source_ids = _instruction_refs(brief, radar)
            items.append(
                PreMarketInstructionItem(
                    instruction_type=InstructionType.REQUIRE_CONFIRMATION,
                    target="ALL",
                    reason="盘前消息源或竞价确认不足，开盘前需要人工确认。",
                    evidence_event_ids=evidence_event_ids,
                    source_ids=source_ids,
                    expires_at=window.continuous_open,
                    requires_manual_review=True,
                )
            )
        source_ids = _unique_strings(brief.source_ids, radar.source_ids, *[item.source_ids for item in items])
        return PreMarketInstruction(
            instruction_id=make_id("pmins"),
            trading_day=window.trading_day,
            generated_at=datetime.now(CHINA_TZ),
            items=items,
            source_ids=source_ids,
            warnings=[*warnings, *radar.warnings],
        )

    def _enrich(self, item: PremarketNewsItem) -> PremarketNewsItem:
        text = f"{item.title} {item.summary}"
        registry_themes = {
            theme
            for keyword, theme in self.theme_registry.aliases.items()
            if keyword in text and self.theme_registry.resolve_theme(theme)
        }
        direct_registry_themes = {theme for theme in self.theme_registry.theme_symbols if theme in text}
        sectors = sorted(
            set(item.sectors)
            | {sector for sector, words in SECTOR_KEYWORDS.items() if any(word in text for word in words)}
            | registry_themes
            | direct_registry_themes
        )
        symbols = sorted(set(item.symbols) | {symbol for name, symbol in SYMBOL_KEYWORDS.items() if name in text})
        category = item.category
        if any(word in text for word in OFFICIAL_WORDS):
            category = "official_policy"
        elif sectors:
            category = "industry_catalyst"
        elif item.source_tier == "sentiment":
            category = "sentiment"
        risk_flags = sorted(set(item.risk_flags) | {word for word in RISK_WORDS if word in text})
        credibility = self._credibility(item, risk_flags)
        return item.model_copy(
            update={
                "category": category,
                "sectors": sectors,
                "symbols": symbols,
                "risk_flags": risk_flags,
                "credibility": credibility,
            }
        )

    def _source_rank(self, item: PremarketNewsItem) -> SourceRank:
        return self.scorer.source_rank(item)

    def _event_importance(self, item: PremarketNewsItem, positive: int, negative: int) -> Importance:
        return self.scorer.importance(item, positive, negative)

    def _event_actionability(self, item: PremarketNewsItem, bias: Bias) -> Actionability:
        return self.scorer.actionability(item, bias)

    def _event_to_news_stub(self, event: PreMarketEvent) -> PremarketNewsItem:
        source_rank = event.source_rank
        return PremarketNewsItem(
            item_id=event.event_id,
            source=str(source_rank),
            source_tier="official" if source_rank == SourceRank.OFFICIAL.value else "professional",
            title=event.title,
            summary=event.summary,
            published_at=event.published_at,
            category=event.event_type,
            symbols=event.symbols,
            sectors=event.related_themes,
            credibility=event.confidence,
            risk_flags=event.risk_flags,
        )

    def _credibility(self, item: PremarketNewsItem, risk_flags: list[str]) -> float:
        base = {"official": 0.92, "professional": 0.78, "sentiment": 0.36}.get(item.source_tier, item.credibility)
        if item.url:
            base += 0.03
        if risk_flags:
            base -= 0.22
        return max(0, min(1, base))

    def _market_mode(self, market_view: str, theme_seeds: list[object], warnings: list[str]) -> str:
        if warnings and market_view == "cautious":
            return "risk_off"
        catalyst_types = {getattr(theme, "catalyst_type", "") for theme in theme_seeds}
        if "policy" in catalyst_types:
            return "policy_sensitive"
        if "earnings" in catalyst_types:
            return "earnings_sensitive"
        if market_view == "positive" and theme_seeds:
            return "risk_on"
        if theme_seeds:
            return "news_driven"
        return "normal" if market_view != "cautious" else "unclear"

    def _dedupe(self, items: list[PremarketNewsItem]) -> list[PremarketNewsItem]:
        seen: set[str] = set()
        deduped: list[PremarketNewsItem] = []
        for item in sorted(items, key=lambda news: news.published_at or news.collected_at, reverse=True):
            key = item.title[:42]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _build_catalysts(self, items: list[PremarketNewsItem]) -> list[PremarketCatalyst]:
        catalysts: list[PremarketCatalyst] = []
        for item in items:
            text = f"{item.title} {item.summary}"
            positive = sum(1 for word in POSITIVE_WORDS if word in text)
            negative = sum(1 for word in NEGATIVE_WORDS if word in text)
            if positive == 0 and negative == 0 and not item.sectors and not item.symbols:
                continue
            bias = "bullish" if positive > negative else "bearish" if negative > positive else "neutral"
            importance = self._importance(item, positive, negative)
            confidence = min(0.95, item.credibility * (0.75 + 0.08 * max(positive, negative, 1)))
            catalysts.append(
                PremarketCatalyst(
                    title=item.title,
                    category=item.category,
                    bias=bias,
                    confidence=confidence,
                    importance=importance,
                    sources=[item.source],
                    symbols=item.symbols,
                    sectors=item.sectors,
                    summary=item.summary or item.title,
                    risk_flags=item.risk_flags,
                )
            )
        return catalysts[:16]

    def _importance(self, item: PremarketNewsItem, positive: int, negative: int) -> str:
        if item.source_tier == "official" and (positive or negative):
            return "S"
        if item.symbols or len(item.sectors) >= 2:
            return "A"
        if item.sectors or positive or negative:
            return "B"
        return "C"

    def _importance_rank(self, value: str) -> int:
        return {"S": 4, "A": 3, "B": 2, "C": 1}.get(str(value), 0)

    def _build_watchlist(self, catalysts: list[PremarketCatalyst]) -> list[PremarketTradePlan]:
        plans: list[PremarketTradePlan] = []
        sector_counts = Counter(sector for catalyst in catalysts if catalyst.bias == "bullish" for sector in catalyst.sectors)
        for sector, count in sector_counts.most_common(5):
            related = [item for item in catalysts if sector in item.sectors and item.bias == "bullish"]
            plans.append(
                PremarketTradePlan(
                    symbol=f"板块:{sector}",
                    name=sector,
                    action="watch",
                    reason=f"{sector} 出现 {count} 条偏积极盘前催化",
                    triggers=["09:15-09:25 集合竞价量比放大", "板块内多只个股竞价强于大盘", "高开不超过策略阈值"],
                    risk_flags=sorted({flag for item in related for flag in item.risk_flags}),
                    confidence=min(0.85, sum(item.confidence for item in related) / max(1, len(related))),
                )
            )
        symbol_seen: set[str] = set()
        for catalyst in catalysts:
            if catalyst.bias != "bullish":
                continue
            for symbol in catalyst.symbols:
                if symbol in symbol_seen:
                    continue
                symbol_seen.add(symbol)
                plans.append(
                    PremarketTradePlan(
                        symbol=symbol,
                        action="watch",
                        reason=catalyst.title,
                        triggers=["竞价成交额显著放大", "开盘后不跌破竞价均价", "消息有公告或多源确认"],
                        risk_flags=catalyst.risk_flags,
                        confidence=catalyst.confidence,
                    )
                )
        return plans[:10]

    def _build_avoid_list(
        self,
        items: list[PremarketNewsItem],
        catalysts: list[PremarketCatalyst],
    ) -> list[PremarketTradePlan]:
        plans: list[PremarketTradePlan] = []
        for catalyst in catalysts:
            if catalyst.bias == "bearish" or catalyst.risk_flags:
                targets = catalyst.symbols or [f"板块:{sector}" for sector in catalyst.sectors] or ["消息未映射标的"]
                for target in targets:
                    plans.append(
                        PremarketTradePlan(
                            symbol=target,
                            action="avoid" if catalyst.risk_flags else "block",
                            reason=catalyst.title,
                            triggers=["消息未确认不得交易", "负面公告优先回避", "高波动只观察"],
                            risk_flags=catalyst.risk_flags or ["bearish_catalyst"],
                            confidence=catalyst.confidence,
                        )
                    )
        if not items:
            plans.append(
                PremarketTradePlan(
                    symbol="ALL",
                    action="block",
                    reason="盘前消息源无有效数据",
                    triggers=["等待消息源恢复", "只允许查看行情，不输出买入建议"],
                    risk_flags=["missing_premarket_news"],
                    confidence=0.95,
                )
            )
        return plans[:10]

    def _warnings(self, statuses: list[PremarketSourceStatus], items: list[PremarketNewsItem]) -> list[str]:
        warnings = []
        failed = [status.source for status in statuses if status.status == "failed"]
        if failed:
            warnings.append(f"消息源不可用：{', '.join(failed)}")
        if not items:
            warnings.append("盘前窗口内没有可用消息，禁止基于新闻做主动买入。")
        if all(item.source_tier == "sentiment" for item in items) and items:
            warnings.append("当前只有情绪源，不能单独作为交易依据。")
        return warnings

    def _market_view(self, catalysts: list[PremarketCatalyst], warnings: list[str]) -> str:
        if warnings and not catalysts:
            return "cautious"
        score = sum((1 if item.bias == "bullish" else -1 if item.bias == "bearish" else 0) * item.confidence for item in catalysts)
        if score > 1.2:
            return "positive"
        if score < -0.6 or warnings:
            return "cautious"
        return "neutral"

    def _summary(self, market_view: str, catalysts: list[PremarketCatalyst], warnings: list[str]) -> str:
        if warnings and not catalysts:
            return "盘前消息源质量不足，今日只做行情观察，不生成主动买入建议。"
        key = "、".join(sorted({sector for catalyst in catalysts for sector in catalyst.sectors})[:4])
        view_text = {"positive": "偏积极", "neutral": "中性", "cautious": "谨慎"}[market_view]
        return f"盘前结论{view_text}。重点关注：{key or '暂无明确板块'}。"

    def _opening_rules(self) -> list[str]:
        return [
            "只把盘前结果作为 watchlist，不自动下单。",
            "无公告或多源确认的消息降权，雪球/股吧类仅作为情绪线索。",
            "集合竞价高开过大时不追，等待开盘后成交额与承接确认。",
            "出现问询函、监管处罚、业绩大幅下修、退市风险时加入禁入。",
        ]


def premarket_window(report_date: date) -> tuple[datetime, datetime]:
    previous = previous_business_day(report_date)
    start = datetime.combine(previous, time(15, 0), tzinfo=CHINA_TZ)
    end = datetime.combine(report_date, time(9, 15), tzinfo=CHINA_TZ)
    return start, end


def previous_business_day(value: date) -> date:
    current = value - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def render_premarket_markdown(report: PremarketReport) -> str:
    lines = [
        f"# 盘前消息与交易分析：{report.date.isoformat()}",
        "",
        f"- 时间窗口：{report.window_start.isoformat()} -> {report.window_end.isoformat()}",
        f"- 盘前结论：{report.market_view}",
        f"- 摘要：{report.summary}",
        "",
        "## 消息源状态",
    ]
    for status in report.source_status:
        lines.append(f"- {status.source}: {status.status}, fetched={status.fetched_count}, used={status.used_count}, error={status.error or '-'}")
    lines.extend(["", "## 重点催化"])
    if report.catalysts:
        for catalyst in report.catalysts:
            lines.append(f"- [{catalyst.importance}/{catalyst.bias}] {catalyst.title} | {catalyst.summary}")
    else:
        lines.append("- 暂无可交易级别催化。")
    lines.extend(["", "## 观察清单"])
    if report.watchlist:
        for item in report.watchlist:
            lines.append(f"- {item.symbol}: {item.reason}；触发：{' / '.join(item.triggers)}")
    else:
        lines.append("- 暂无。")
    lines.extend(["", "## 禁入/回避"])
    for item in report.avoid_list:
        lines.append(f"- {item.symbol}: {item.reason}；风险：{', '.join(item.risk_flags)}")
    lines.extend(["", "## 开盘规则"])
    for rule in report.opening_rules:
        lines.append(f"- {rule}")
    if report.warnings:
        lines.extend(["", "## 警告"])
        for warning in report.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"
