from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import date as Date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from trading_agent_system.core.config import load_yaml_config
from trading_agent_system.agents.premarket_agent.factor_learning import (
    PremarketFactorLearningAgent,
    PremarketFactorLearningState,
    PremarketFactorLearningStore,
)
from trading_agent_system.agents.premarket_agent.factor_scoring import PremarketFactorScoreSet
from trading_agent_system.agents.premarket_agent.outcome_evaluator import PremarketSignalOutcomeEvaluator
from trading_agent_system.core.knowledge import KnowledgeStore, RagRetriever
from trading_agent_system.core.market_data import (
    EastMoneyMarketDataProvider,
    SinaMarketDataProvider,
    TencentMarketDataProvider,
)
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.premarket import PremarketContextLoader
from trading_agent_system.core.storage import JsonlEventRepository
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "daily"
PREMARKET_REPORT_DIR = ROOT / "reports" / "premarket"
APP_CONFIG = ROOT / "configs" / "app.yaml"
EVENT_DIR = ROOT / "data" / "events"
TRACE_DIR = ROOT / "data" / "traces"
METRICS_DIR = ROOT / "data" / "metrics"
AUDIT_DIR = ROOT / "data" / "audit"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge.sqlite"
A_STOCK_DATA_SOURCE = "a-stock-data/premarket"
ONE_PICK_CHECKPOINT_DIR = ROOT / "data" / "runtime" / "checkpoints"
ONE_PICK_LEARNING_DIR = ROOT / "data" / "strategy_learning"
PREMARKET_LEARNING_DIR = ROOT / "data" / "premarket_learning"
DAILY_STRATEGY_DB = ROOT / "data" / "daily_strategy.sqlite"
LLM_RUNTIME_CONFIG = ROOT / "data" / "config" / "llm_runtime.json"
DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def _env_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _cors_origin_regex() -> str | None:
    configured = os.getenv("CORS_ORIGIN_REGEX")
    if configured is not None:
        return configured or None
    if os.getenv("RAILWAY_ENVIRONMENT"):
        return r"https://.*\.up\.railway\.app"
    return None


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


class OnePickRollbackRequest(BaseModel):
    target_version: str


class PremarketFactorLearningRollbackRequest(BaseModel):
    target_version: str


class LlmProviderUpdateRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None


class LlmAgentRouteUpdateRequest(BaseModel):
    agent: str
    provider: str
    model: str
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_llm_tokens: int | None = Field(default=None, ge=0)
    max_llm_cost: float | None = Field(default=None, ge=0)


JOBS: dict[str, tuple[str, list[str]]] = {
    "premarket": (
        "盘前 Agent",
        ["scripts/run_premarket_agent.py", "--date", "{date}", "--config", "configs/app.yaml"],
    ),
    "daily_strategy_recommendation": (
        "每日单票策略",
        ["scripts/run_daily_premarket_recommendation.py", "--date", "{date}"],
    ),
    "daily_strategy_settlement": (
        "单票策略结算",
        ["scripts/run_daily_strategy_settlement.py", "--date", "{date}"],
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
    allow_origins=[*DEFAULT_CORS_ORIGINS, *_env_list("CORS_ORIGINS")],
    allow_origin_regex=_cors_origin_regex(),
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


@app.get("/api/llm/config")
def llm_runtime_config() -> dict[str, object]:
    config = _load_llm_runtime_config()
    return {
        "providers": {
            provider: _redacted_provider_config(provider_config)
            for provider, provider_config in config.get("providers", {}).items()
            if isinstance(provider_config, dict)
        },
        "agent_routes": config.get("agent_routes", {}),
        "usage": _llm_usage_summary(),
        "config_path": str(LLM_RUNTIME_CONFIG),
    }


@app.post("/api/llm/provider")
def update_llm_provider(request: LlmProviderUpdateRequest) -> dict[str, object]:
    provider = request.provider.strip()
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    config = _load_llm_runtime_config()
    providers = config.setdefault("providers", {})
    provider_config = dict(providers.get(provider, {})) if isinstance(providers.get(provider), dict) else {}
    if request.api_key is not None and request.api_key.strip():
        provider_config["api_key"] = request.api_key.strip()
    if request.base_url is not None:
        provider_config["base_url"] = request.base_url.strip()
    if request.default_model is not None:
        provider_config["default_model"] = request.default_model.strip()
    providers[provider] = provider_config
    _save_llm_runtime_config(config)
    return llm_runtime_config()


@app.post("/api/llm/agent-route")
def update_llm_agent_route(request: LlmAgentRouteUpdateRequest) -> dict[str, object]:
    agent = request.agent.strip()
    provider = request.provider.strip()
    model = request.model.strip()
    if not agent:
        raise HTTPException(status_code=400, detail="agent is required")
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    config = _load_llm_runtime_config()
    routes = config.setdefault("agent_routes", {})
    routes[agent] = {
        "provider": provider,
        "model": model,
        "budget": {
            "max_llm_calls": request.max_llm_calls,
            "max_llm_tokens": request.max_llm_tokens,
            "max_llm_cost": request.max_llm_cost,
        },
    }
    _save_llm_runtime_config(config)
    return llm_runtime_config()


@app.get("/api/llm/usage")
def llm_usage() -> dict[str, object]:
    return {"usage": _llm_usage_summary()}


@app.post("/api/run/{job}", response_model=RunResult)
def run_job(job: str, request: RunRequest | None = None) -> RunResult:
    request = request or RunRequest()
    return _run_job(job, request.date)


@app.post("/api/run-all", response_model=RunAllResult)
def run_all(request: RunRequest | None = None) -> RunAllResult:
    request = request or RunRequest()
    started = time.perf_counter()
    results = [
        _run_job(job, request.date)
        for job in [
            "premarket",
            "daily_strategy_recommendation",
            "daily_strategy_settlement",
            "intraday",
            "risk",
            "broker",
            "review",
        ]
    ]
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


@app.get("/api/premarket/recommendations/latest")
def premarket_recommendations_latest() -> dict[str, object]:
    repository = JsonlEventRepository(EVENT_DIR)
    recommendations = _latest_event_payload(repository, "premarket.strategy_recommendations")
    return {
        "status": "ok" if recommendations else "empty",
        "semantic_reviews": _latest_event_payload(repository, "premarket.semantic_reviews"),
        "factor_scores": _latest_event_payload(repository, "premarket.factor_scores"),
        "recommendations": recommendations,
    }


@app.get("/api/daily-strategy/latest")
def daily_strategy_latest() -> dict[str, object]:
    store = StrategyLedgerStore(DAILY_STRATEGY_DB)
    try:
        recommendation = store.recommendations.latest()
        outcome = store.outcomes.latest()
        active_weight = store.weights.active()
    finally:
        store.close()
    return {
        "status": "ok" if recommendation else "empty",
        "recommendation": recommendation,
        "latest_outcome": outcome,
        "active_weight_version": active_weight,
    }


@app.get("/api/daily-strategy/audit/{run_id}")
def daily_strategy_audit(run_id: str) -> dict[str, object]:
    store = StrategyLedgerStore(DAILY_STRATEGY_DB)
    try:
        timeline = store.audits.by_run(run_id)
    finally:
        store.close()
    return {"run_id": run_id, "timeline": timeline}


@app.get("/api/premarket/factor-learning/state")
def premarket_factor_learning_state() -> dict[str, object]:
    store = PremarketFactorLearningStore(PREMARKET_LEARNING_DIR)
    current = store.get_current()
    return {
        "learning_state": _plain_data(current) if current else None,
        "versions": store.list_versions(),
        "path": str(PREMARKET_LEARNING_DIR),
    }


@app.post("/api/premarket/factor-learning/rollback")
def premarket_factor_learning_rollback(request: PremarketFactorLearningRollbackRequest | dict[str, object]) -> dict[str, object]:
    target_version = request.target_version if isinstance(request, PremarketFactorLearningRollbackRequest) else request.get("target_version")
    if not target_version:
        raise HTTPException(status_code=400, detail="target_version is required")
    try:
        state = PremarketFactorLearningStore(PREMARKET_LEARNING_DIR).rollback_current(str(target_version))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"learning_state": _plain_data(state)}


@app.post("/api/premarket/factor-learning/evaluate")
def premarket_factor_learning_evaluate(request: dict[str, object]) -> dict[str, object]:
    if not isinstance(request.get("score_set"), dict):
        raise HTTPException(status_code=400, detail="score_set is required")
    if not isinstance(request.get("market_results"), dict):
        raise HTTPException(status_code=400, detail="market_results is required")
    score_set = PremarketFactorScoreSet.model_validate(request["score_set"])
    evaluation_date = Date.fromisoformat(str(request["evaluation_date"])) if request.get("evaluation_date") else None
    outcome_set = PremarketSignalOutcomeEvaluator().evaluate(
        score_set,
        request["market_results"],  # type: ignore[arg-type]
        index_return=float(request.get("index_return") or 0.0),
        evaluation_date=evaluation_date,
    )
    store = PremarketFactorLearningStore(PREMARKET_LEARNING_DIR)
    current_state = store.get_current() or PremarketFactorLearningState(version="pfl_initial")
    update = PremarketFactorLearningAgent().update(current_state, outcome_set)
    store.save_version(update.next_state)
    return {
        "outcome_set": _plain_data(outcome_set),
        "learning_update": _plain_data(update),
        "learning_state": _plain_data(update.next_state),
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


@app.get("/api/one-pick/latest")
def one_pick_latest() -> dict[str, object]:
    return _one_pick_debug_snapshot()


@app.get("/api/one-pick/run/{run_id}")
def one_pick_run(run_id: str) -> dict[str, object]:
    return _one_pick_debug_snapshot(run_id=run_id)


@app.get("/api/one-pick/learning-state")
def one_pick_learning_state() -> dict[str, object]:
    return {"learning_state": _one_pick_learning_state()}


@app.post("/api/one-pick/learning-state/rollback")
def one_pick_learning_rollback(request: OnePickRollbackRequest | dict[str, object]) -> dict[str, object]:
    target_version = request.target_version if isinstance(request, OnePickRollbackRequest) else request.get("target_version")
    if not target_version:
        raise HTTPException(status_code=400, detail="target_version is required")
    learning_state = _one_pick_learning_state()
    versions = learning_state["versions"]
    if target_version not in {str(version.get("version")) for version in versions if version.get("version") is not None}:
        raise HTTPException(status_code=404, detail=f"learning version not found: {target_version}")
    ONE_PICK_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    (ONE_PICK_LEARNING_DIR / "one_pick_current.json").write_text(
        json.dumps({"current_version": target_version}, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return {"learning_state": _one_pick_learning_state()}


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


def _default_llm_runtime_config() -> dict[str, object]:
    return {
        "providers": {
            "openai": {"api_key": "", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4.1-mini"},
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com", "default_model": "deepseek-chat"},
            "qwen": {"api_key": "", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus"},
        },
        "agent_routes": {
            "premarket_agent": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "budget": {"max_llm_calls": 4, "max_llm_tokens": 8000, "max_llm_cost": 1.0},
            },
            "one_pick_agent": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "budget": {"max_llm_calls": 3, "max_llm_tokens": 6000, "max_llm_cost": 1.0},
            },
            "review_agent": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "budget": {"max_llm_calls": 2, "max_llm_tokens": 4000, "max_llm_cost": 0.5},
            },
        },
    }


def _load_llm_runtime_config() -> dict[str, object]:
    default = _default_llm_runtime_config()
    if not LLM_RUNTIME_CONFIG.exists():
        return default
    try:
        loaded = json.loads(LLM_RUNTIME_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    if not isinstance(loaded, dict):
        return default
    return _deep_merge(default, loaded)


def _save_llm_runtime_config(config: dict[str, object]) -> None:
    LLM_RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    LLM_RUNTIME_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _deep_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _redacted_provider_config(provider_config: dict[str, object]) -> dict[str, object]:
    api_key = str(provider_config.get("api_key") or "")
    return {
        "api_key_set": bool(api_key),
        "api_key_preview": _api_key_preview(api_key),
        "base_url": provider_config.get("base_url") or "",
        "default_model": provider_config.get("default_model") or "",
    }


def _api_key_preview(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}...{api_key[-4:]}"


def _llm_usage_summary() -> dict[str, object]:
    records = _llm_audit_records()
    by_provider: dict[str, dict[str, float]] = {}
    by_agent: dict[str, dict[str, float]] = {}
    total = {"calls": 0.0, "tokens": 0.0, "cost": 0.0}
    recent: list[dict[str, object]] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        provider = str(payload.get("provider_name") or "unknown")
        agent = str(payload.get("agent") or payload.get("agent_name") or "unknown")
        tokens = float(payload.get("usage_total") or payload.get("total_tokens") or 0)
        cost = float(payload.get("estimated_cost") or payload.get("cost") or 0)
        for bucket in (total, by_provider.setdefault(provider, {"calls": 0.0, "tokens": 0.0, "cost": 0.0})):
            bucket["calls"] += 1
            bucket["tokens"] += tokens
            bucket["cost"] += cost
        agent_bucket = by_agent.setdefault(agent, {"calls": 0.0, "tokens": 0.0, "cost": 0.0})
        agent_bucket["calls"] += 1
        agent_bucket["tokens"] += tokens
        agent_bucket["cost"] += cost
        recent.append(
            {
                "ts": record.get("ts"),
                "provider": provider,
                "agent": agent,
                "tokens": tokens,
                "cost": cost,
                "cache_hit": payload.get("cache_hit"),
            }
        )
    return {
        "total": _usage_ints(total),
        "by_provider": {key: _usage_ints(value) for key, value in by_provider.items()},
        "by_agent": {key: _usage_ints(value) for key, value in by_agent.items()},
        "recent": list(reversed(recent[-10:])),
    }


def _llm_audit_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(AUDIT_DIR.glob("*.jsonl")) if AUDIT_DIR.exists() else []:
        for row in _read_jsonl_file(path):
            if row.get("event_type") == "llm.call":
                rows.append(row)
    rows.sort(key=lambda row: str(row.get("ts") or ""))
    return rows


def _usage_ints(value: dict[str, float]) -> dict[str, float | int]:
    return {
        "calls": int(value.get("calls", 0)),
        "tokens": int(value.get("tokens", 0)),
        "cost": round(float(value.get("cost", 0)), 6),
    }


def _one_pick_debug_snapshot(run_id: str | None = None) -> dict[str, object]:
    checkpoints = _load_one_pick_checkpoints(run_id=run_id)
    resolved_run_id = run_id or _latest_run_id(checkpoints)
    if resolved_run_id is not None:
        checkpoints = [item for item in checkpoints if item.get("run_id") == resolved_run_id]

    traces = [
        trace.model_dump(mode="json")
        for trace in TraceLogger(TRACE_DIR).load(run_id=resolved_run_id, agent="one_pick_agent", limit=200)
    ] if resolved_run_id else []
    metrics = [
        metric.model_dump(mode="json")
        for metric in MetricsRecorder(METRICS_DIR).load(run_id=resolved_run_id, limit=200)
    ] if resolved_run_id else []
    events = _load_one_pick_events(run_id=resolved_run_id)
    learning_state = _one_pick_learning_state()
    selected_stock = _first_present(
        [_extract_payload(checkpoints, ("selected_stock", "selection", "selected"))],
        _extract_event_payload(events, ("selected_stock", "selection", "selected")),
    )
    selected_stock = _normalize_selected_stock(selected_stock)
    trade_plan = _first_present(
        [_extract_payload(checkpoints, ("trade_plan", "plan"))],
        _extract_event_payload(events, ("trade_plan", "plan")),
    )
    fills = [
        event["payload"]
        for event in events
        if event["topic"] in {"one_pick.buy_filled", "one_pick.sell_filled"}
    ]
    outcome = _first_present(
        [_extract_payload(checkpoints, ("outcome",))],
        _extract_event_payload(events, ("outcome", "review", "result")),
    )
    budget_usage = _one_pick_budget_usage(metrics, checkpoints)
    evidence_refs = sorted(
        {
            str(ref)
            for item in [*checkpoints, *traces, *events]
            for ref in item.get("evidence_ids", [])
            if ref
        }
    )
    for value in (selected_stock, trade_plan, outcome):
        if isinstance(value, dict):
            evidence_refs.extend(str(ref) for ref in value.get("evidence_ids", []) if ref)
    evidence_refs = sorted(set(evidence_refs))
    trace_refs = [
        {
            "trace_id": trace["trace_id"],
            "step": trace["step"],
            "status": trace["status"],
            "output_refs": trace.get("output_refs", []),
            "evidence_ids": trace.get("evidence_ids", []),
        }
        for trace in traces
    ]
    latest_checkpoint = checkpoints[-1] if checkpoints else None
    return {
        "status": "ok" if resolved_run_id and (checkpoints or events or traces) else "empty",
        "run_id": resolved_run_id,
        "trading_day": _first_non_empty([item.get("trading_day") for item in checkpoints + events]),
        "selected_stock": selected_stock,
        "trade_plan": trade_plan,
        "fills": fills,
        "outcome": outcome,
        "learning_state": learning_state,
        "learning_version": learning_state.get("current_version"),
        "learning_update": learning_state.get("current"),
        "checkpoints": checkpoints,
        "checkpoint_timeline": [
            {
                "checkpoint_id": item.get("checkpoint_id"),
                "step": item.get("step"),
                "status": item.get("status"),
                "updated_at": item.get("updated_at") or item.get("created_at"),
            }
            for item in checkpoints
        ],
        "trace_refs": trace_refs,
        "evidence_refs": evidence_refs,
        "budget_usage": budget_usage,
        "events": events,
        "latest_checkpoint": latest_checkpoint,
    }


def _load_one_pick_checkpoints(*, run_id: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _read_jsonl_dir(ONE_PICK_CHECKPOINT_DIR):
        item_run_id = item.get("run_id")
        agent = str(item.get("agent") or "")
        if run_id is not None and item_run_id != run_id:
            continue
        if agent and "one_pick" not in agent and not str(item.get("step") or "").startswith("one_pick"):
            continue
        rows.append(item)
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    return rows


def _load_one_pick_events(*, run_id: str | None = None) -> list[dict[str, Any]]:
    repository = JsonlEventRepository(EVENT_DIR)
    events: list[dict[str, Any]] = []
    for topic in repository.list_topics():
        if not topic.startswith("one.pick") and not topic.startswith("one_pick"):
            continue
        normalized_topic = _normalize_one_pick_topic(topic)
        for envelope in repository.load_envelopes(topic, run_id=run_id, limit=200):
            events.append(
                {
                    "event_id": envelope.event_id,
                    "topic": normalized_topic,
                    "producer": envelope.producer,
                    "run_id": envelope.run_id,
                    "trading_day": envelope.trading_day.isoformat() if envelope.trading_day else None,
                    "created_at": envelope.created_at.isoformat(),
                    "evidence_ids": envelope.evidence_ids,
                    "payload": envelope.payload,
                }
            )
    events.sort(key=lambda item: str(item.get("created_at") or ""))
    return events


def _normalize_one_pick_topic(topic: str) -> str:
    if topic.startswith("one.pick."):
        return f"one_pick.{topic.removeprefix('one.pick.').replace('.', '_')}"
    return topic


def _one_pick_learning_state() -> dict[str, object]:
    versions_path = ONE_PICK_LEARNING_DIR / "one_pick_versions.jsonl"
    current_path = ONE_PICK_LEARNING_DIR / "one_pick_current.json"
    versions = _read_jsonl_file(versions_path)
    current_version = None
    if current_path.exists():
        try:
            current_data = json.loads(current_path.read_text(encoding="utf-8"))
            current_version = current_data.get("current_version") or current_data.get("version")
        except json.JSONDecodeError:
            current_version = None
    if current_version is None and versions:
        current_version = versions[-1].get("version")
    current = next((item for item in reversed(versions) if item.get("version") == current_version), None)
    return {
        "current_version": current_version,
        "current": current,
        "versions": versions,
        "version_count": len(versions),
        "path": str(ONE_PICK_LEARNING_DIR),
    }


def _read_jsonl_dir(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("*.jsonl")):
        rows.extend(_read_jsonl_file(file_path))
    return rows


def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows


def _plain_data(value: object) -> object:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[attr-defined]
    return value


def _latest_run_id(checkpoints: list[dict[str, Any]]) -> str | None:
    for item in reversed(checkpoints):
        if item.get("run_id"):
            return str(item["run_id"])
    return None


def _extract_payload(items: list[dict[str, Any]], keys: tuple[str, ...]) -> object | None:
    for item in reversed(items):
        payload = item.get("payload")
        found = _find_nested_value(payload, keys)
        if found is not None:
            return found
    return None


def _extract_event_payload(events: list[dict[str, Any]], keys: tuple[str, ...]) -> object | None:
    for event in reversed(events):
        found = _find_nested_value(event.get("payload"), keys)
        if found is not None:
            return found
    return None


def _find_nested_value(value: object, keys: tuple[str, ...]) -> object | None:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for nested in value.values():
            found = _find_nested_value(nested, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_nested_value(nested, keys)
            if found is not None:
                return found
    return None


def _normalize_selected_stock(value: object | None) -> object | None:
    if not isinstance(value, dict):
        return value
    symbol = value.get("symbol") or value.get("selected_symbol")
    if not symbol:
        return value
    normalized = dict(value)
    normalized["symbol"] = symbol
    if value.get("selected_name") and not normalized.get("name"):
        normalized["name"] = value["selected_name"]
    return normalized


def _one_pick_budget_usage(metrics: list[dict[str, Any]], checkpoints: list[dict[str, Any]]) -> dict[str, float]:
    usage: dict[str, float] = {}
    for metric in metrics:
        name = str(metric.get("name") or "")
        if "budget" not in name and "token" not in name and "cost" not in name:
            continue
        usage[name] = usage.get(name, 0.0) + float(metric.get("value") or 0)
    for checkpoint in checkpoints:
        payload = checkpoint.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("budget"), dict):
            for key, value in payload["budget"].items():
                if isinstance(value, int | float):
                    usage[key] = usage.get(key, 0.0) + float(value)
    return usage


def _first_present(candidates: list[object | None], fallback: object | None) -> object | None:
    for item in candidates:
        if item is not None:
            return item
    return fallback


def _first_non_empty(values: list[object | None]) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
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
