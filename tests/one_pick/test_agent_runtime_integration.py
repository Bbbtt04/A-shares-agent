from __future__ import annotations

from trading_agent_system.agents.one_pick_agent.agent import OnePickAgent, OnePickRuntimePorts
from trading_agent_system.agents.one_pick_agent.schemas import (
    EffectiveOnePickStrategy,
    OnePickSelectionConfig,
)
from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.runtime import (
    AgentRunContext,
    BudgetGuard,
    CheckpointStore,
    RuntimeBudget,
    StepRunner,
)
from trading_agent_system.schemas import OrderInstruction, RiskDecision


class FakeStepRunner:
    def __init__(self) -> None:
        self.steps: list[str] = []

    def run(self, step_name, func, *, force=False, **kwargs):
        self.steps.append(step_name)
        return func()


class FakeRiskGateway:
    def __init__(self) -> None:
        self.intent_ids: list[str] = []

    def on_trade_intent(self, intent):
        self.intent_ids.append(intent.intent_id)
        return RiskDecision(
            intent_id=intent.intent_id,
            decision="approved",
            approved_quantity=intent.quantity,
            approved_price=intent.limit_price,
            reason="approved",
            checks={},
        )

    def to_order_instruction(self, intent, decision):
        return OrderInstruction(
            decision_id=decision.decision_id,
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=decision.approved_quantity,
            order_type=intent.order_type,
            limit_price=decision.approved_price,
            ttl_seconds=intent.ttl_seconds,
        )


class FakePaperBroker:
    def __init__(self) -> None:
        self.instructions: list[OrderInstruction] = []

    def on_order_instruction(self, instruction):
        self.instructions.append(instruction)
        return {"order_id": "order_1", "status": "submitted"}


def _strategy() -> EffectiveOnePickStrategy:
    return EffectiveOnePickStrategy(
        strategy_id="one_pick_two_day_v1",
        strategy_version="1.0.0",
        selection=OnePickSelectionConfig(force_pick_one=True),
        scoring_weights={"catalyst_strength": 0.7, "source_quality": 0.3},
        risk_penalties={},
        blocked_risk_flags=[],
        tag_adjustments={},
        entry_rule={"default_quantity": 100},
        exit_rule={"take_profit_pct": 0.04, "stop_loss_pct": 0.02},
        learning={},
    )


def test_agent_uses_injected_step_runner_and_buy_ports_without_runtime_imports():
    step_runner = FakeStepRunner()
    risk_gateway = FakeRiskGateway()
    paper_broker = FakePaperBroker()
    agent = OnePickAgent(
        strategy_loader=lambda: _strategy(),
        ports=OnePickRuntimePorts(
            step_runner=step_runner,
            risk_gateway=risk_gateway,
            paper_broker=paper_broker,
        ),
    )

    result = agent.run_premarket(
        events=[
            {
                "event_id": "evt_1",
                "symbols": ["688981.SH"],
                "importance": "A",
                "bias": "bullish",
                "confidence": 0.8,
                "source_rank": "official",
                "related_themes": ["semiconductor"],
            }
        ],
        evidence_packs=[],
        market_snapshots={"688981.SH": {"last_price": 100.0}},
    )

    assert step_runner.steps == [
        "candidates_generated",
        "stock_selected",
        "trade_plan_created",
        "buy_order_submitted",
    ]
    assert result.selection.selected_symbol == "688981.SH"
    assert len(risk_gateway.intent_ids) == 1
    assert len(paper_broker.instructions) == 1


def test_agent_buy_submission_is_idempotent_per_plan_id():
    risk_gateway = FakeRiskGateway()
    paper_broker = FakePaperBroker()
    agent = OnePickAgent(
        strategy_loader=lambda: _strategy(),
        ports=OnePickRuntimePorts(risk_gateway=risk_gateway, paper_broker=paper_broker),
    )
    result = agent.run_premarket(
        events=[
            {
                "event_id": "evt_1",
                "symbols": ["688981.SH"],
                "importance": "A",
                "bias": "bullish",
                "confidence": 0.8,
                "source_rank": "official",
                "related_themes": ["semiconductor"],
            }
        ],
        evidence_packs=[],
        market_snapshots={"688981.SH": {"last_price": 100.0}},
    )

    first = agent.submit_buy(result.trade_plan, result.strategy)
    second = agent.submit_buy(result.trade_plan, result.strategy)

    assert first.intent.intent_id == second.intent.intent_id
    assert len(risk_gateway.intent_ids) == 1
    assert len(paper_broker.instructions) == 1


def test_agent_runs_through_formal_step_runner_and_writes_checkpoints(tmp_path):
    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    step_runner = StepRunner(
        checkpoint_store,
        TraceLogger(tmp_path / "traces"),
        MetricsRecorder(tmp_path / "metrics"),
        AuditLedger(tmp_path / "audit.jsonl"),
        MemoryEventBus(),
        BudgetGuard(RuntimeBudget(max_tool_calls=10)),
    )
    context = AgentRunContext(
        run_id="run_formal",
        agent="one_pick_agent",
        permission_profile="paper",
        budget=RuntimeBudget(max_tool_calls=10),
    )
    agent = OnePickAgent(
        strategy_loader=lambda: _strategy(),
        ports=OnePickRuntimePorts(step_runner=step_runner, run_context=context),
    )

    result = agent.run_premarket(
        events=[
            {
                "event_id": "evt_1",
                "symbols": ["688981.SH"],
                "importance": "A",
                "bias": "bullish",
                "confidence": 0.8,
                "source_rank": "official",
                "related_themes": ["semiconductor"],
            }
        ],
        evidence_packs=[],
        market_snapshots={"688981.SH": {"last_price": 100.0}},
    )

    assert result.selection.selected_symbol == "688981.SH"
    assert checkpoint_store.load(run_id="run_formal", step="candidates_generated").status == "success"
    assert checkpoint_store.load(run_id="run_formal", step="stock_selected").status == "success"
    assert checkpoint_store.load(run_id="run_formal", step="trade_plan_created").status == "success"
    assert checkpoint_store.load(run_id="run_formal", step="buy_order_submitted").status == "success"
