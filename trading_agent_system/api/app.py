from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date as Date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.core.knowledge import KnowledgeStore, RagRetriever
from trading_agent_system.core.market_data import (
    EastMoneyMarketDataProvider,
    SinaMarketDataProvider,
    TencentMarketDataProvider,
)
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.premarket import PremarketContextLoader
from trading_agent_system.core.storage import JsonlEventRepository


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "daily"
PREMARKET_REPORT_DIR = ROOT / "reports" / "premarket"
APP_CONFIG = ROOT / "configs" / "app.yaml"
EVENT_DIR = ROOT / "data" / "events"
TRACE_DIR = ROOT / "data" / "traces"
METRICS_DIR = ROOT / "data" / "metrics"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge.sqlite"
A_STOCK_DATA_SOURCE = "a-stock-data/premarket"


class RunRequest(BaseModel):
    date: Date = Field(default_factory=Date.today)


class RunResult(BaseModel):
    job: str
    label: str
    command: list[str]
    status: Literal["success", "failed"]
    returncode: int
    elapsed_ms: int
    stdout: str
    stderr: str
    parsed: object | None = None


class RunAllResult(BaseModel):
    status: Literal["success", "failed"]
    elapsed_ms: int
    results: list[RunResult]


class QuoteRequest(BaseModel):
    symbols: list[str] | None = None


JOBS: dict[str, tuple[str, list[str]]] = {
    "premarket": (
        "盘前 Agent",
        ["scripts/run_premarket_agent.py", "--date", "{date}", "--config", "configs/app.yaml"],
    ),
    "intraday": (
        "盘中 Agent",
        ["scripts/run_intraday_agent.py", "--config", "configs/app.yaml", "--demo"],
    ),
    "risk": (
        "风控网关",
        ["scripts/run_risk_gateway.py", "--config", "configs/risk.paper.yaml", "--demo"],
    ),
    "broker": (
        "Paper Broker",
        ["scripts/run_paper_broker.py", "--config", "configs/app.yaml", "--demo"],
    ),
    "review": (
        "复盘 Agent",
        ["scripts/run_review_agent.py", "--date", "{date}", "--config", "configs/app.yaml", "--demo"],
    ),
}


app = FastAPI(title="A股 Agent Console API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "root": str(ROOT),
        "safe_defaults": {
            "trading_enabled": False,
            "require_human_approval": True,
            "mode": "paper",
        },
    }


@app.post("/api/run/{job}", response_model=RunResult)
def run_job(job: str, request: RunRequest | None = None) -> RunResult:
    request = request or RunRequest()
    return _run_job(job, request.date)


@app.post("/api/run-all", response_model=RunAllResult)
def run_all(request: RunRequest | None = None) -> RunAllResult:
    request = request or RunRequest()
    started = time.perf_counter()
    results = [_run_job(job, request.date) for job in ["premarket", "intraday", "risk", "broker", "review"]]
    status = "success" if all(result.status == "success" for result in results) else "failed"
    return RunAllResult(
        status=status,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        results=results,
    )


@app.get("/api/reports")
def list_reports() -> dict[str, object]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(REPORT_DIR.glob("*.md"), reverse=True):
        reports.append(
            {
                "name": path.name,
                "date": path.stem,
                "path": str(path),
                "size": path.stat().st_size,
            }
        )
    return {"reports": reports}


@app.get("/api/reports/{report_name}", response_class=PlainTextResponse)
def read_report(report_name: str) -> str:
    if "/" in report_name or ".." in report_name or not report_name.endswith(".md"):
        raise HTTPException(status_code=400, detail="invalid report name")
    path = REPORT_DIR / report_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return path.read_text(encoding="utf-8")


@app.get("/api/premarket/latest")
def latest_premarket_report() -> dict[str, object]:
    PREMARKET_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = sorted(PREMARKET_REPORT_DIR.glob("*.json"), reverse=True)
    if not reports:
        return {"report": None}
    try:
        return {"report": json.loads(reports[0].read_text(encoding="utf-8"))}
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"invalid premarket report: {reports[0].name}") from error


@app.get("/api/premarket/context")
def premarket_context_latest() -> dict[str, object]:
    PREMARKET_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    context = PremarketContextLoader(PREMARKET_REPORT_DIR).load_latest()
    return {"context": context.model_dump(mode="json") if context else None}


@app.get("/api/premarket/rag/latest")
def premarket_rag_latest() -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    return {
        "evidence": _latest_event_payload(repository, "premarket.rag_evidence_packs"),
        "evaluation": _latest_event_payload(repository, "premarket.rag_evaluation"),
    }


@app.get("/api/premarket/debug")
def premarket_debug(
    trading_day: Date | None = None,
    q: str = "盘前",
    limit: int = 200,
) -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    report = _load_premarket_report(trading_day)
    resolved_day = trading_day or _report_date(report) or Date.today()
    warnings: list[str] = _report_warnings(report)

    step_specs = [
        ("raw_documents", "窗口内原始文档", "premarket.raw_documents"),
        ("normalized_events", "事件抽取", "premarket.normalized_events"),
        ("event_clusters", "事件聚类", "premarket.event_clusters"),
        ("morning_brief", "盘前摘要", "premarket.morning_brief"),
        ("opening_radar", "开盘雷达", "premarket.opening_radar"),
        ("instructions", "盘前约束", "premarket.instructions"),
    ]
    source_fetch_step = _source_fetch_step(report, limit)
    crawled_documents_step = _debug_step(
        repository,
        "crawled_documents",
        "全部爬取数据",
        "premarket.crawled_documents",
        resolved_day,
        None,
    )
    steps = [
        _debug_step(repository, step_id, label, topic, resolved_day, limit)
        for step_id, label, topic in step_specs
    ]

    knowledge_records: list[dict[str, object]] = []
    knowledge_results: list[dict[str, object]] = []
    try:
        store = KnowledgeStore(KNOWLEDGE_PATH)
        knowledge_records = [
            record.model_dump(mode="json")
            for record in store.list_records(trading_day=resolved_day, limit=limit)
        ]
        knowledge_results = [
            result.model_dump(mode="json")
            for result in RagRetriever(store).search(query=q, trading_day=resolved_day, top_k=limit)
        ]
    except Exception as error:  # pragma: no cover - defensive for broken local sqlite files
        warnings.append(f"knowledge store read failed: {error}")

    return {
        "trading_day": resolved_day.isoformat(),
        "query": {"q": q, "limit": limit},
        "steps": [
            source_fetch_step,
            crawled_documents_step,
            *steps,
            {
                "id": "knowledge_store",
                "label": "落入知识库",
                "topic": "knowledge_records",
                "status": "ok" if knowledge_records else "empty",
                "count": len(knowledge_records),
                "items": knowledge_records[:limit],
                "event": None,
            },
            _debug_step(repository, "rag_evidence", "RAG 证据包", "premarket.rag_evidence_packs", resolved_day, limit),
        ],
        "knowledge": {
            "record_count": len(knowledge_records),
            "records": knowledge_records[:limit],
            "query_results": knowledge_results,
        },
        "rag": {
            "evidence": _latest_event_payload(repository, "premarket.rag_evidence_packs", trading_day=resolved_day),
            "evaluation": _latest_event_payload(repository, "premarket.rag_evaluation", trading_day=resolved_day),
        },
        "a_stock_data": _a_stock_data_debug_summary(report, crawled_documents_step["items"]),
        "conclusion": _premarket_conclusion(report),
        "warnings": warnings,
    }


@app.get("/api/intraday/latest")
def latest_intraday_analysis() -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    envelopes = repository.load_envelopes("intraday.analysis", limit=1)
    if not envelopes:
        return {"report": None, "event": None}
    envelope = envelopes[-1]
    return {
        "report": envelope.payload,
        "event": {
            "event_id": envelope.event_id,
            "producer": envelope.producer,
            "run_id": envelope.run_id,
            "trading_day": envelope.trading_day.isoformat() if envelope.trading_day else None,
            "created_at": envelope.created_at.isoformat(),
            "evidence_ids": envelope.evidence_ids,
        },
    }


@app.get("/api/observability/events")
def observability_events(topic: str | None = None, limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    topics = [topic] if topic else repository.list_topics()
    events = []
    for item in topics:
        events.extend(envelope.model_dump(mode="json") for envelope in repository.load_envelopes(item, limit=limit))
    events.sort(key=lambda event: event["created_at"], reverse=True)
    return {"topics": topics, "events": events[:limit]}


@app.get("/api/observability/traces")
def observability_traces(
    run_id: str | None = None,
    agent: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    traces = TraceLogger(TRACE_DIR).load(run_id=run_id, agent=agent, limit=limit)
    return {"traces": [trace.model_dump(mode="json") for trace in traces]}


@app.get("/api/observability/metrics")
def observability_metrics(
    name: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    metrics = MetricsRecorder(METRICS_DIR).load(name=name, run_id=run_id, limit=limit)
    return {"metrics": [metric.model_dump(mode="json") for metric in metrics]}


@app.get("/api/observability/knowledge/search")
def observability_knowledge_search(
    q: str,
    trading_day: Date | None = None,
    theme: list[str] | None = Query(default=None),
    symbol: list[str] | None = Query(default=None),
    source_rank_min: str | None = None,
    top_k: int = Query(default=8, ge=1, le=50),
) -> dict[str, object]:
    results = RagRetriever(KnowledgeStore(KNOWLEDGE_PATH)).search(
        query=q,
        trading_day=trading_day,
        themes=theme,
        symbols=symbol,
        source_rank_min=source_rank_min,
        top_k=top_k,
    )
    return {"results": [result.model_dump(mode="json") for result in results]}


@app.get("/api/risk/approval-queue")
def risk_approval_queue(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    queue = []
    for envelope in repository.load_envelopes("risk.approval_queue", limit=limit):
        payload = dict(envelope.payload)
        payload.update(
            {
                "event_id": envelope.event_id,
                "run_id": envelope.run_id,
                "trading_day": envelope.trading_day.isoformat() if envelope.trading_day else None,
                "evidence_ids": envelope.evidence_ids,
                "created_at": envelope.created_at.isoformat(),
            }
        )
        queue.append(payload)
    queue.sort(key=lambda item: item["created_at"], reverse=True)
    return {"queue": queue[:limit]}


@app.get("/api/decisions/traces")
def decision_traces(
    intent_id: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    timeline = []
    for topic in [
        "trading.intents",
        "risk.decisions",
        "risk.approval_queue",
        "orders.instructions",
        "orders.submitted",
        "orders.filled",
        "orders.cancelled",
        "orders.rejected",
    ]:
        for envelope in repository.load_envelopes(topic, run_id=run_id, limit=limit):
            payload_intent_id = _payload_intent_id(envelope.payload)
            if intent_id and payload_intent_id != intent_id:
                continue
            timeline.append(
                {
                    "topic": envelope.topic,
                    "event_id": envelope.event_id,
                    "producer": envelope.producer,
                    "run_id": envelope.run_id,
                    "trading_day": envelope.trading_day.isoformat() if envelope.trading_day else None,
                    "created_at": envelope.created_at.isoformat(),
                    "intent_id": payload_intent_id,
                    "evidence_ids": envelope.evidence_ids,
                    "payload": envelope.payload,
                }
            )
    timeline.sort(key=lambda item: item["created_at"])
    return {"intent_id": intent_id, "run_id": run_id, "timeline": timeline[:limit]}


@app.get("/api/rag/debug")
def rag_debug(
    q: str,
    trading_day: Date | None = None,
    theme: list[str] | None = Query(default=None),
    symbol: list[str] | None = Query(default=None),
    source_rank_min: str | None = None,
    top_k: int = Query(default=8, ge=1, le=50),
) -> dict[str, object]:
    filters = {
        "q": q,
        "trading_day": trading_day.isoformat() if trading_day else None,
        "themes": theme or [],
        "symbols": symbol or [],
        "source_rank_min": source_rank_min,
        "top_k": top_k,
    }
    results = RagRetriever(KnowledgeStore(KNOWLEDGE_PATH)).search(
        query=q,
        trading_day=trading_day,
        themes=theme,
        symbols=symbol,
        source_rank_min=source_rank_min,
        top_k=top_k,
    )
    return {
        "query": filters,
        "result_count": len(results),
        "results": [result.model_dump(mode="json") for result in results],
    }


@app.get("/api/market/quotes")
def market_quotes() -> dict[str, object]:
    config = load_yaml_config(APP_CONFIG)
    symbols = _default_market_symbols(config)
    source, quotes, error = _fetch_quotes_with_fallback(symbols)
    return {
        "source": source,
        "notice": "公开行情接口可能存在延迟，仅用于监控与 paper trading。",
        "symbols": symbols,
        "quotes": [quote.model_dump(mode="json") for quote in quotes],
        "error": error,
    }


@app.post("/api/market/quotes")
def market_quotes_for_symbols(request: QuoteRequest) -> dict[str, object]:
    config = load_yaml_config(APP_CONFIG)
    symbols = request.symbols or _default_market_symbols(config)
    source, quotes, error = _fetch_quotes_with_fallback(symbols)
    return {
        "source": source,
        "notice": "公开行情接口可能存在延迟，仅用于监控与 paper trading。",
        "symbols": symbols,
        "quotes": [quote.model_dump(mode="json") for quote in quotes],
        "error": error,
    }


@app.get("/api/market/stocks")
def market_stocks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    sort: Literal["symbol", "trade", "changepercent", "volume", "amount", "turnoverratio"] = "changepercent",
    asc: bool = False,
) -> dict[str, object]:
    try:
        data = SinaMarketDataProvider().fetch_stock_page(
            page=page,
            page_size=page_size,
            sort=sort,
            asc=asc,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"sina stock quote failed: {error}") from error
    quotes = data.pop("quotes")
    return {
        **data,
        "notice": "公开行情接口可能存在延迟，仅用于监控与 paper trading。",
        "quotes": [quote.model_dump(mode="json") for quote in quotes],
    }


def _run_job(job: str, report_date: Date) -> RunResult:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {job}")
    label, args = JOBS[job]
    command = [sys.executable, *[item.format(date=report_date.isoformat()) for item in args]]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=30,
        check=False,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return RunResult(
        job=job,
        label=label,
        command=command,
        status="success" if completed.returncode == 0 else "failed",
        returncode=completed.returncode,
        elapsed_ms=elapsed_ms,
        stdout=completed.stdout,
        stderr=completed.stderr,
        parsed=_parse_stdout(completed.stdout),
    )


def _parse_stdout(stdout: str) -> object | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(stripped)
        return parsed
    except json.JSONDecodeError:
        return None


def _payload_intent_id(payload: dict[str, object]) -> str | None:
    direct = payload.get("intent_id")
    if direct:
        return str(direct)
    for key in ("intent", "decision", "order_instruction", "fill"):
        nested = payload.get(key)
        if isinstance(nested, dict) and nested.get("intent_id"):
            return str(nested["intent_id"])
    return None


def _latest_event_payload(
    repository: JsonlEventRepository,
    topic: str,
    *,
    trading_day: Date | None = None,
) -> dict[str, object] | None:
    envelopes = repository.load_envelopes(topic, trading_day=trading_day, limit=1)
    if not envelopes:
        return None
    envelope = envelopes[-1]
    return {
        "event": {
            "event_id": envelope.event_id,
            "producer": envelope.producer,
            "run_id": envelope.run_id,
            "trading_day": envelope.trading_day.isoformat() if envelope.trading_day else None,
            "created_at": envelope.created_at.isoformat(),
            "evidence_ids": envelope.evidence_ids,
        },
        "payload": envelope.payload,
    }


def _debug_step(
    repository: JsonlEventRepository,
    step_id: str,
    label: str,
    topic: str,
    trading_day: Date,
    limit: int | None,
) -> dict[str, object]:
    latest = _latest_event_payload(repository, topic, trading_day=trading_day)
    payload = latest["payload"] if latest else None
    count = _payload_count(payload)
    return {
        "id": step_id,
        "label": label,
        "topic": topic,
        "status": "ok" if count else "empty",
        "count": count,
        "items": _payload_items(payload, limit),
        "metadata": _payload_metadata(payload),
        "event": latest["event"] if latest else None,
    }


def _payload_metadata(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    keys = ("window_start", "window_end", "total_count")
    return {key: payload[key] for key in keys if key in payload}


def _payload_count(payload: object) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            return len(payload["value"])
        if payload.get("value") is not None:
            return 1
        if isinstance(payload.get("packs"), list):
            return len(payload["packs"])
        if isinstance(payload.get("items"), list):
            return len(payload["items"])
        return 1 if payload else 0
    return 0


def _payload_items(payload: object, limit: int | None) -> list[object]:
    if isinstance(payload, list):
        return payload if limit is None else payload[:limit]
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            return payload["value"] if limit is None else payload["value"][:limit]
        if payload.get("value") is not None:
            return [payload["value"]]
        if isinstance(payload.get("packs"), list):
            return payload["packs"] if limit is None else payload["packs"][:limit]
        if isinstance(payload.get("items"), list):
            return payload["items"] if limit is None else payload["items"][:limit]
        return [payload] if payload else []
    return []


def _load_premarket_report(trading_day: Date | None) -> dict[str, object] | None:
    PREMARKET_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if trading_day is not None:
        path = PREMARKET_REPORT_DIR / f"{trading_day.isoformat()}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    reports = sorted(PREMARKET_REPORT_DIR.glob("*.json"), reverse=True)
    if not reports:
        return None
    return json.loads(reports[0].read_text(encoding="utf-8"))


def _report_date(report: dict[str, object] | None) -> Date | None:
    if not report or not report.get("date"):
        return None
    return Date.fromisoformat(str(report["date"]))


def _source_fetch_step(report: dict[str, object] | None, limit: int) -> dict[str, object]:
    source_status = []
    if report and isinstance(report.get("source_status"), list):
        source_status = [item for item in report["source_status"] if isinstance(item, dict)]
    fetched_count = sum(int(item.get("fetched_count") or 0) for item in source_status)
    used_count = sum(int(item.get("used_count") or 0) for item in source_status)
    return {
        "id": "source_fetch",
        "label": "源站抓取状态",
        "topic": "premarket.report.source_status",
        "status": "ok" if fetched_count else "empty",
        "count": fetched_count,
        "items": source_status[:limit],
        "event": None,
        "summary": {
            "fetched_count": fetched_count,
            "used_count": used_count,
            "filtered_count": max(fetched_count - used_count, 0),
        },
    }


def _a_stock_data_debug_summary(
    report: dict[str, object] | None,
    crawled_items: list[object],
) -> dict[str, object]:
    config = _a_stock_data_config()
    source_status = _a_stock_data_source_status(report)
    crawled = [
        item
        for item in crawled_items
        if isinstance(item, dict)
        and (item.get("provider_name") == A_STOCK_DATA_SOURCE or item.get("source") == A_STOCK_DATA_SOURCE)
    ]
    category_counts: dict[str, int] = {}
    for item in crawled:
        category = str(item.get("category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "enabled": bool(config.get("enabled", False)),
        "symbols": config.get("symbols", []),
        "status": source_status.get("status", "empty" if config.get("enabled", False) else "disabled"),
        "fetched_count": int(source_status.get("fetched_count") or 0),
        "used_count": int(source_status.get("used_count") or 0),
        "crawled_count": len(crawled),
        "in_window_count": sum(1 for item in crawled if item.get("in_premarket_window")),
        "category_counts": category_counts,
    }


def _a_stock_data_config() -> dict[str, object]:
    try:
        config = load_yaml_config(APP_CONFIG)
    except (FileNotFoundError, OSError):
        return {"enabled": False, "symbols": []}
    premarket = config.get("premarket", {}) if isinstance(config, dict) else {}
    a_stock_data = premarket.get("a_stock_data", {}) if isinstance(premarket, dict) else {}
    if not isinstance(a_stock_data, dict):
        return {"enabled": False, "symbols": []}
    symbols = [str(symbol) for symbol in a_stock_data.get("symbols", []) if symbol]
    return {
        "enabled": bool(a_stock_data.get("enabled", False)),
        "symbols": symbols,
    }


def _a_stock_data_source_status(report: dict[str, object] | None) -> dict[str, object]:
    if not report or not isinstance(report.get("source_status"), list):
        return {}
    for item in report["source_status"]:
        if not isinstance(item, dict):
            continue
        if item.get("provider_name") == A_STOCK_DATA_SOURCE or item.get("source") == A_STOCK_DATA_SOURCE:
            return item
    return {}


def _report_warnings(report: dict[str, object] | None) -> list[str]:
    if not report or not isinstance(report.get("warnings"), list):
        return []
    return [str(item) for item in report["warnings"]]


def _premarket_conclusion(report: dict[str, object] | None) -> dict[str, object]:
    if not report:
        return {
            "available": False,
            "market_view": "-",
            "summary": "暂无盘前报告",
            "watchlist": [],
            "avoid_list": [],
            "catalysts": [],
        }
    return {
        "available": True,
        "market_view": report.get("market_view") or "-",
        "summary": report.get("summary") or "",
        "watchlist": report.get("watchlist") or [],
        "avoid_list": report.get("avoid_list") or [],
        "catalysts": report.get("catalysts") or [],
    }


def _fetch_quotes_with_fallback(symbols: list[str]) -> tuple[str, list[object], str | None]:
    errors: list[str] = []
    for source, provider in [
        ("eastmoney", EastMoneyMarketDataProvider()),
        ("tencent", TencentMarketDataProvider()),
    ]:
        try:
            quotes = provider.fetch_quotes(symbols)
            if quotes:
                return source, quotes, "; ".join(errors) or None
            errors.append(f"{source}: empty quote response")
        except Exception as error:
            errors.append(f"{source}: {error}")
    return "none", [], "; ".join(errors)


def _default_market_symbols(config: dict[str, object]) -> list[str]:
    market = config.get("market", {})
    indexes = market.get("indexes", []) if isinstance(market, dict) else []
    watchlist = config.get("watchlist", [])
    symbols = [*indexes, *watchlist]
    seen: set[str] = set()
    deduped: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    return deduped
