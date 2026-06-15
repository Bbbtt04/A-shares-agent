from datetime import date

import pytest

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.core.runtime import (
    AgentRunContext,
    BudgetExceeded,
    BudgetGuard,
    CheckpointStore,
    RuntimeBudget,
    StepRunner,
)


def _runner(tmp_path, budget: RuntimeBudget | None = None):
    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    trace_logger = TraceLogger(tmp_path / "traces")
    metrics = MetricsRecorder(tmp_path / "metrics")
    audit = AuditLedger(tmp_path / "audit.jsonl")
    event_bus = MemoryEventBus()
    guard = BudgetGuard(budget or RuntimeBudget(max_tool_calls=10))
    runner = StepRunner(checkpoint_store, trace_logger, metrics, audit, event_bus, guard)
    return runner, checkpoint_store, trace_logger, metrics, audit, event_bus, guard


def _context() -> AgentRunContext:
    return AgentRunContext(
        run_id="run_1",
        trading_day=date(2026, 6, 15),
        agent="one_pick",
        correlation_id="corr_1",
        permission_profile="paper",
        budget=RuntimeBudget(max_tool_calls=10),
        metadata={"phase": "premarket"},
    )


def test_agent_run_context_carries_runtime_metadata():
    context = _context()

    assert context.run_id == "run_1"
    assert context.trading_day == date(2026, 6, 15)
    assert context.permission_profile == "paper"
    assert context.metadata == {"phase": "premarket"}


def test_successful_step_writes_trace_metric_audit_event_and_checkpoint(tmp_path):
    runner, store, traces, metrics, audit, event_bus, guard = _runner(tmp_path)
    context = _context()

    def step_fn(received_context: AgentRunContext):
        assert received_context == context
        return {"output_refs": ["selection_1"], "payload": {"symbol": "600519"}, "summary": "selected stock"}

    result = runner.run(
        context,
        step="stock_selected",
        input_refs=["candidate_1"],
        evidence_ids=["evidence_1"],
        fn=step_fn,
    )

    assert result.status == "success"
    assert result.output_refs == ["selection_1"]
    assert store.load(run_id="run_1", step="stock_selected").payload == {"symbol": "600519"}
    assert traces.load(run_id="run_1")[0].status == "success"
    assert traces.load(run_id="run_1")[0].decision_summary == "selected stock"
    assert metrics.load(name="runtime_step_total", run_id="run_1")[0].tags["status"] == "success"
    assert audit.records[0]["event_type"] == "runtime.step.success"
    assert event_bus.events("runtime.step_succeeded")[0]["step"] == "stock_selected"
    assert guard.budget.spent_tool_calls == 1


def test_failed_step_writes_failed_checkpoint_and_trace_error(tmp_path):
    runner, store, traces, metrics, audit, event_bus, _guard = _runner(tmp_path)
    context = _context()

    def step_fn(_context: AgentRunContext):
        raise RuntimeError("selector failed")

    with pytest.raises(RuntimeError, match="selector failed"):
        runner.run(context, step="stock_selected", fn=step_fn)

    assert store.load(run_id="run_1", step="stock_selected").status == "failed"
    assert "selector failed" in store.load(run_id="run_1", step="stock_selected").error
    assert traces.load(run_id="run_1")[0].status == "failed"
    assert "selector failed" in traces.load(run_id="run_1")[0].error
    assert metrics.load(name="runtime_step_total", run_id="run_1")[0].tags["status"] == "failed"
    assert audit.records[0]["event_type"] == "runtime.step.failed"
    assert event_bus.events("runtime.step_failed")[0]["step"] == "stock_selected"


def test_completed_step_is_skipped_on_rerun(tmp_path):
    runner, store, _traces, _metrics, _audit, event_bus, _guard = _runner(tmp_path)
    context = _context()
    calls = 0

    def step_fn(_context: AgentRunContext):
        nonlocal calls
        calls += 1
        return {"payload": {"calls": calls}}

    first = runner.run(context, step="stock_selected", fn=step_fn)
    second = runner.run(context, step="stock_selected", fn=step_fn)

    assert first.status == "success"
    assert second.status == "skipped"
    assert second.payload == {"calls": 1}
    assert calls == 1
    assert store.load(run_id="run_1", step="stock_selected").status == "success"
    assert event_bus.events("runtime.step_skipped")[0]["step"] == "stock_selected"


def test_force_reruns_completed_step(tmp_path):
    runner, store, _traces, _metrics, _audit, _event_bus, _guard = _runner(tmp_path)
    context = _context()
    calls = 0

    def step_fn(_context: AgentRunContext):
        nonlocal calls
        calls += 1
        return {"payload": {"calls": calls}}

    runner.run(context, step="stock_selected", fn=step_fn)
    forced = runner.run(context, step="stock_selected", fn=step_fn, force=True)

    assert forced.status == "success"
    assert forced.payload == {"calls": 2}
    assert calls == 2
    assert store.load(run_id="run_1", step="stock_selected").payload == {"calls": 2}


def test_budget_failure_prevents_step_execution(tmp_path):
    runner, store, traces, metrics, audit, event_bus, _guard = _runner(tmp_path, RuntimeBudget(max_tool_calls=0))
    context = _context()
    calls = 0

    def step_fn(_context: AgentRunContext):
        nonlocal calls
        calls += 1
        return {"payload": {"calls": calls}}

    with pytest.raises(BudgetExceeded):
        runner.run(context, step="stock_selected", fn=step_fn)

    assert calls == 0
    assert store.load(run_id="run_1", step="stock_selected").status == "failed"
    assert "tool call budget exceeded" in traces.load(run_id="run_1")[0].error
    assert metrics.load(name="runtime_step_total", run_id="run_1")[0].tags["status"] == "budget_exceeded"
    assert audit.records[0]["event_type"] == "runtime.step.budget_exceeded"
    assert event_bus.events("runtime.step_budget_exceeded")[0]["step"] == "stock_selected"
