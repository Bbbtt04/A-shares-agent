from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading_agent_system.agents.one_pick_agent import OnePickAgent, OnePickRuntimePorts, OnePickStrategyLoader
from trading_agent_system.agents.one_pick_agent.real_inputs import RealOnePickInputBuilder
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import DurableEventBus
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.runtime import (
    AgentRunContext,
    BudgetGuard,
    CheckpointStore,
    RuntimeBudget,
    StepRunner,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the one-pick two-day paper agent core.")
    parser.add_argument("--phase", choices=["premarket", "exit", "review", "full-demo"], default="full-demo")
    parser.add_argument("--input", choices=["real", "demo"], default="real")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--date", default=str(date.today()))
    parser.add_argument("--config", default=None)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config) if args.config else None
    trading_day = date.fromisoformat(args.date)
    input_mode = "demo" if args.phase == "full-demo" and args.input == "demo" else args.input
    run_id = args.run_id or f"one_pick_{input_mode}_{trading_day.isoformat()}"
    budget = RuntimeBudget(max_llm_calls=3, max_llm_tokens=6000, max_llm_cost=1.0, max_tool_calls=40)
    step_runner = StepRunner(
        CheckpointStore(),
        TraceLogger(),
        MetricsRecorder(),
        AuditLedger(),
        DurableEventBus(),
        BudgetGuard(budget),
    )
    context = AgentRunContext(
        run_id=run_id,
        trading_day=trading_day,
        agent="one_pick_agent",
        correlation_id=run_id,
        permission_profile="paper",
        budget=budget,
        metadata={"phase": args.phase, "input": input_mode, "script": "run_one_pick_agent"},
    )
    agent = OnePickAgent(
        strategy_loader=OnePickStrategyLoader(config_path=config_path),
        ports=OnePickRuntimePorts(step_runner=step_runner, run_context=context, event_bus=DurableEventBus()),
    )

    if args.phase in {"premarket", "full-demo"}:
        inputs = _build_inputs(input_mode, trading_day)
        result = agent.run_premarket(
            events=inputs["events"],
            event_clusters=inputs["event_clusters"],
            evidence_packs=inputs["evidence_packs"],
            market_snapshots=inputs["market_snapshots"],
            force=args.force,
        )
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "trading_day": trading_day.isoformat(),
                    "input": inputs["metadata"],
                    **result.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(
        json.dumps(
            {
                "phase": args.phase,
                "status": "waiting_for_runtime_ports",
                "message": "Inject StepRunner/RiskGateway/PaperBroker and persisted executions before this phase.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _build_inputs(input_mode: str, trading_day: date) -> dict[str, Any]:
    if input_mode == "demo":
        return {
            "events": _demo_events(trading_day.isoformat()),
            "event_clusters": [],
            "evidence_packs": [{"evidence_id": "demo_rag_1", "symbols": ["688981.SH"], "score": 0.8}],
            "market_snapshots": {"688981.SH": {"last_price": 100.0}},
            "metadata": {"source": "demo", "universe": "demo"},
        }
    real_inputs = RealOnePickInputBuilder().build(trading_day=trading_day)
    if not real_inputs.events and not real_inputs.event_clusters and not real_inputs.evidence_packs:
        raise RuntimeError(
            "No premarket artifacts were found. Run scripts/run_premarket_agent.py first, "
            "or use --input demo for a dry run."
        )
    return {
        "events": real_inputs.events,
        "event_clusters": real_inputs.event_clusters,
        "evidence_packs": real_inputs.evidence_packs,
        "market_snapshots": real_inputs.market_snapshots,
        "metadata": real_inputs.metadata,
    }


def _demo_events(trading_day: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": f"demo_policy_{trading_day}",
            "symbols": ["688981.SH"],
            "title": "official semiconductor catalyst",
            "importance": "A",
            "bias": "bullish",
            "confidence": 0.8,
            "source_rank": "official",
            "related_themes": ["semiconductor"],
            "risk_flags": [],
        }
    ]


if __name__ == "__main__":
    main()
