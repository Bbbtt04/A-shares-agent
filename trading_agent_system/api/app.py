from __future__ import annotations

import json
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
