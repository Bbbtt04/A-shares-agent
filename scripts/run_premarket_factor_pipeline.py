from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trading_agent_system.agents.premarket_agent.factor_learning import PremarketFactorLearningStore
from trading_agent_system.agents.premarket_agent.factor_scoring import PremarketFactorScorer
from trading_agent_system.agents.premarket_agent.schemas import PreMarketEvent
from trading_agent_system.agents.premarket_agent.semantic_review import PremarketSemanticReviewAgent
from trading_agent_system.agents.premarket_agent.strategy_recommendation import PremarketStrategyRecommendationAgent
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.events import make_envelope
from trading_agent_system.core.llm_gateway import LLMGateway, OpenAICompatibleClient
from trading_agent_system.core.storage import JsonlEventRepository


def run_pipeline(
    *,
    report_path: str | Path,
    event_dir: str | Path = "data/events",
    learning_dir: str | Path = "data/premarket_learning",
    generated_at: datetime | None = None,
    run_id: str | None = None,
    top_n: int = 10,
    llm_gateway: object | None = None,
) -> dict[str, object]:
    report = _load_report(Path(report_path))
    trading_day = date.fromisoformat(str(report["date"]))
    generated_at = generated_at or datetime.now(timezone.utc)
    run_id = run_id or f"premarket_factor_{trading_day.isoformat()}"
    events = _events_from_report(report)
    learning_state = PremarketFactorLearningStore(learning_dir).get_current()
    learning_payload = asdict(learning_state) if learning_state is not None else None

    semantic_reviews = PremarketSemanticReviewAgent(llm_gateway=llm_gateway).review(
        events,
        evidence_packs=_evidence_packs_from_report(report),
        trading_day=trading_day,
        top_n=top_n,
    )
    factor_scores = PremarketFactorScorer(generated_at=generated_at).score(
        events,
        semantic_reviews=semantic_reviews,
        learning_state=learning_payload,
        trading_day=trading_day,
    )
    recommendations = PremarketStrategyRecommendationAgent(generated_at=generated_at).build(factor_scores)

    repository = JsonlEventRepository(event_dir)
    for topic, payload in [
        ("premarket.semantic_reviews", semantic_reviews),
        ("premarket.factor_scores", factor_scores),
        ("premarket.strategy_recommendations", recommendations),
    ]:
        repository.append_envelope(
            make_envelope(
                topic,
                _plain_data(payload),
                producer="premarket_factor_pipeline",
                trading_day=trading_day,
                run_id=run_id,
                evidence_ids=_evidence_ids(payload),
            )
        )

    return {
        "semantic_reviews": semantic_reviews,
        "factor_scores": factor_scores,
        "recommendations": recommendations,
    }


def build_llm_gateway_from_config(
    config_path: str | Path = "data/config/llm_runtime.json",
    *,
    agent: str = "premarket_agent",
) -> tuple[LLMGateway, dict[str, Any]]:
    config = _load_json_config(Path(config_path))
    routes = config.get("agent_routes", {}) if isinstance(config.get("agent_routes"), dict) else {}
    route = routes.get(agent, {}) if isinstance(routes, dict) else {}
    if not isinstance(route, dict):
        route = {}
    provider_name = str(route.get("provider") or "openai")
    providers = config.get("providers", {}) if isinstance(config.get("providers"), dict) else {}
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = str(route.get("model") or provider_config.get("default_model") or "")
    client = OpenAICompatibleClient(
        provider_name=provider_name,
        api_key=str(provider_config.get("api_key") or ""),
        base_url=str(provider_config.get("base_url") or ""),
        default_model=model,
    )
    return LLMGateway(clients={provider_name: client}, audit_ledger=AuditLedger()), {**route, "provider": provider_name, "model": model}


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("date"):
        raise ValueError("premarket report must be a JSON object with date")
    return data


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"config must be a JSON object: {path}")
    return data


def _events_from_report(report: dict[str, Any]) -> list[PreMarketEvent]:
    raw_events = (
        report.get("normalized_events")
        or report.get("events")
        or (report.get("post_close_digest") or {}).get("events")
        or []
    )
    return [PreMarketEvent.model_validate(event) for event in raw_events if isinstance(event, dict)]


def _evidence_packs_from_report(report: dict[str, Any]) -> list[object]:
    rag = report.get("rag") if isinstance(report.get("rag"), dict) else {}
    packs = rag.get("evidence_packs") if isinstance(rag, dict) else None
    return packs if isinstance(packs, list) else []


def _evidence_ids(payload: object) -> list[str]:
    data = _plain_data(payload)
    text = json.dumps(data, ensure_ascii=False, default=str)
    ids: list[str] = []
    for key in ("evidence_ids", "evidence_event_ids"):
        marker = f'"{key}":'
        if marker not in text:
            continue
    if isinstance(data, dict):
        ids.extend(_collect_evidence_ids(data))
    return sorted(set(ids))


def _collect_evidence_ids(value: object) -> list[str]:
    if isinstance(value, dict):
        ids: list[str] = []
        for key, item in value.items():
            if key in {"evidence_ids", "evidence_event_ids"} and isinstance(item, list):
                ids.extend(str(entry) for entry in item if entry)
            else:
                ids.extend(_collect_evidence_ids(item))
        return ids
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            ids.extend(_collect_evidence_ids(item))
        return ids
    return []


def _plain_data(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the premarket factor signal pipeline from a saved premarket report.")
    parser.add_argument("--report", default=None)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--event-dir", default="data/events")
    parser.add_argument("--learning-dir", default="data/premarket_learning")
    parser.add_argument("--llm-config", default="data/config/llm_runtime.json")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else Path("reports/premarket") / f"{args.date}.json"
    llm_gateway = build_llm_gateway_from_config(args.llm_config, agent="premarket_agent")[0] if args.use_llm else None
    result = run_pipeline(
        report_path=report_path,
        event_dir=args.event_dir,
        learning_dir=args.learning_dir,
        top_n=args.top_n,
        llm_gateway=llm_gateway,
    )
    print(json.dumps({key: _plain_data(value) for key, value in result.items()}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
