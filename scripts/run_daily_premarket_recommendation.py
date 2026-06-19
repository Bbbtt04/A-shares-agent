from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.run_premarket_factor_pipeline import build_llm_gateway_from_config, run_pipeline


def run_daily_recommendation(
    report_path: str | Path,
    ledger_store: object,
    event_dir: str | Path = "data/events",
    learning_dir: str | Path = "data/premarket_learning",
    generated_at: datetime | None = None,
    run_id: str | None = None,
    top_n: int = 10,
    llm_gateway: object | None = None,
) -> dict[str, object]:
    report_path = Path(report_path)
    trading_day = _trading_day_from_report(report_path)
    run_id = run_id or f"daily_premarket_recommend_{trading_day.isoformat()}"
    generated_at = generated_at or datetime.now(timezone.utc)
    metadata = {"report_path": str(report_path), "top_n": top_n}

    ledger_store.runs.start(run_id, trading_day, "premarket_recommend", metadata=metadata)
    try:
        pipeline_result = run_pipeline(
            report_path=report_path,
            event_dir=event_dir,
            learning_dir=learning_dir,
            generated_at=generated_at,
            run_id=run_id,
            top_n=top_n,
            llm_gateway=llm_gateway,
        )
    except Exception as error:
        ledger_store.runs.finish(run_id, "failed", error_message=str(error))
        raise

    recommendations = _recommendation_items(pipeline_result.get("recommendations"))
    payloads = (
        [
            _recommendation_payload(
                item,
                run_id=run_id,
                trading_day=trading_day,
                priority=index + 1,
            )
            for index, item in enumerate(recommendations)
        ]
        if recommendations
        else [_no_trade_payload(run_id, trading_day)]
    )
    for payload in payloads:
        ledger_store.recommendations.save(payload)

    _log_audit(
        ledger_store,
        run_id=run_id,
        trading_day=trading_day,
        stage="semantic_review",
        input_payload={"report_path": str(report_path), "top_n": top_n},
        output_payload=pipeline_result.get("semantic_reviews"),
        reasoning_summary="semantic reviews generated from premarket report",
    )
    _log_audit(
        ledger_store,
        run_id=run_id,
        trading_day=trading_day,
        stage="factor_scoring",
        input_payload=pipeline_result.get("semantic_reviews"),
        output_payload=pipeline_result.get("factor_scores"),
        reasoning_summary="factor scores generated from semantic reviews and learning state",
    )
    _log_audit(
        ledger_store,
        run_id=run_id,
        trading_day=trading_day,
        stage="recommendation",
        input_payload=pipeline_result.get("factor_scores"),
        output_payload=pipeline_result.get("recommendations"),
        reasoning_summary="daily premarket recommendations persisted to strategy ledger",
    )

    ledger_store.runs.finish(run_id, "success")
    return {
        "run_id": run_id,
        "trading_day": trading_day.isoformat(),
        "status": "success",
        "saved_recommendation_count": len(payloads),
        "recommendations": payloads,
        "pipeline_result": {key: _plain_data(value) for key, value in pipeline_result.items()},
    }


def _trading_day_from_report(report_path: Path) -> date:
    if report_path.exists():
        data = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("date"):
            return date.fromisoformat(str(data["date"]))
    return date.fromisoformat(report_path.stem)


def _recommendation_items(recommendation_set: object) -> list[object]:
    items = _read(recommendation_set, "recommendations", [])
    return list(items) if isinstance(items, list) else []


def _recommendation_payload(
    recommendation: object,
    *,
    run_id: str,
    trading_day: date,
    priority: int,
) -> dict[str, object]:
    symbol = str(_read(recommendation, "symbol", ""))
    item_priority = int(_read(recommendation, "priority", priority) or priority)
    evidence_ids = _read(recommendation, "evidence_ids", []) or []
    handoff_version = _read(recommendation, "handoff_payload_version", "premarket_strategy_handoff.v1")
    return {
        "recommendation_id": f"{run_id}_{symbol}_{item_priority}",
        "run_id": run_id,
        "trading_day": trading_day.isoformat(),
        "symbol": symbol,
        "action": str(_read(recommendation, "action", "")),
        "priority": item_priority,
        "confidence": float(_read(recommendation, "confidence", 0.0) or 0.0),
        "signal_score": float(_read(recommendation, "signal_score", 0.0) or 0.0),
        "expected_risk_reward": _read(recommendation, "expected_risk_reward", None),
        "entry_conditions": list(_read(recommendation, "entry_conditions", []) or []),
        "avoid_conditions": list(_read(recommendation, "avoid_conditions", []) or []),
        "risk_notes": list(_read(recommendation, "risk_notes", []) or []),
        "handoff_payload": {
            "version": handoff_version,
            "symbol": symbol,
            "action": _read(recommendation, "action", ""),
            "priority": item_priority,
            "evidence_ids": list(evidence_ids) if isinstance(evidence_ids, list) else [],
            "reason": _read(recommendation, "reason", None),
        },
    }


def _no_trade_payload(run_id: str, trading_day: date) -> dict[str, object]:
    return {
        "recommendation_id": f"{run_id}_no_trade",
        "run_id": run_id,
        "trading_day": trading_day.isoformat(),
        "symbol": "NO_TRADE",
        "action": "no_trade",
        "priority": 1,
        "confidence": 0.0,
        "signal_score": 0.0,
        "expected_risk_reward": None,
        "entry_conditions": [],
        "avoid_conditions": [],
        "risk_notes": ["No actionable premarket recommendation was produced."],
        "handoff_payload": {
            "version": "premarket_strategy_handoff.v1",
            "reason": "pipeline returned no recommendations",
        },
    }


def _log_audit(
    ledger_store: object,
    *,
    run_id: str,
    trading_day: date,
    stage: str,
    input_payload: object,
    output_payload: object,
    reasoning_summary: str,
) -> None:
    ledger_store.audits.log(
        {
            "audit_id": f"{run_id}_{stage}",
            "run_id": run_id,
            "trading_day": trading_day.isoformat(),
            "symbol": None,
            "stage": stage,
            "input": _plain_data(input_payload),
            "output": _plain_data(output_payload),
            "reasoning_summary": reasoning_summary,
            "model_name": None,
            "latency_ms": None,
        }
    )


def _plain_data(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_data(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {key: _plain_data(item) for key, item in vars(value).items() if not key.startswith("_")}
    return value


def _read(source: object, name: str, default: object = None) -> object:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily premarket recommendations and persist them to the ledger.")
    parser.add_argument("--report", default=None)
    parser.add_argument("--db-path", default="data/daily_strategy.sqlite")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--event-dir", default="data/events")
    parser.add_argument("--learning-dir", default="data/premarket_learning")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--llm-config", default="data/config/llm_runtime.json")
    args = parser.parse_args()

    from trading_agent_system.core.strategy_ledger import StrategyLedgerStore

    report_path = Path(args.report) if args.report else Path("reports/premarket") / f"{args.date}.json"
    llm_gateway = build_llm_gateway_from_config(args.llm_config, agent="premarket_agent")[0] if args.use_llm else None
    store = StrategyLedgerStore(args.db_path)
    try:
        result = run_daily_recommendation(
            report_path,
            store,
            event_dir=args.event_dir,
            learning_dir=args.learning_dir,
            top_n=args.top_n,
            llm_gateway=llm_gateway,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
