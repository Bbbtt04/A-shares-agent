from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import EventBus
from trading_agent_system.core.observability import MetricsRecorder, TraceLogger
from trading_agent_system.schemas import StrictBaseModel

from .budget import BudgetExceeded, BudgetGuard
from .checkpoint import CheckpointStore, RuntimeCheckpoint
from .context import AgentRunContext


class StepResult(StrictBaseModel):
    status: Literal["success", "failed", "skipped"]
    step: str
    output_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    checkpoint: RuntimeCheckpoint | None = None
    error: str | None = None


StepFunction = Callable[[AgentRunContext], Any]


class StepRunner:
    def __init__(
        self,
        checkpoint_store: CheckpointStore,
        trace_logger: TraceLogger,
        metrics_recorder: MetricsRecorder,
        audit_ledger: AuditLedger,
        event_bus: EventBus,
        budget_guard: BudgetGuard,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.trace_logger = trace_logger
        self.metrics_recorder = metrics_recorder
        self.audit_ledger = audit_ledger
        self.event_bus = event_bus
        self.budget_guard = budget_guard

    def run(
        self,
        context: AgentRunContext,
        *,
        step: str,
        fn: StepFunction,
        input_refs: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        force: bool = False,
    ) -> StepResult:
        input_refs = input_refs or []
        evidence_ids = evidence_ids or []
        if self.checkpoint_store.is_completed(run_id=context.run_id, step=step) and not force:
            return self._skip(context, step)

        try:
            self.budget_guard.assert_tool_allowed()
        except BudgetExceeded as exc:
            checkpoint = self._record_failure(
                context,
                step,
                str(exc),
                input_refs=input_refs,
                output_refs=[],
                payload={},
                evidence_ids=evidence_ids,
                status_tag="budget_exceeded",
                audit_event_type="runtime.step.budget_exceeded",
                event_topic="runtime.step_budget_exceeded",
            )
            raise BudgetExceeded(str(exc)) from exc

        try:
            with self.trace_logger.step(
                agent=context.agent,
                step=step,
                run_id=context.run_id,
                input_refs=input_refs,
                evidence_ids=evidence_ids,
            ) as span:
                raw_result = fn(context)
                payload, output_refs, summary = self._normalize_result(raw_result)
                span.set_output_refs(output_refs)
                span.set_summary(summary)
        except Exception as exc:
            checkpoint = self._record_failure(
                context,
                step,
                str(exc),
                input_refs=input_refs,
                output_refs=[],
                payload={},
                evidence_ids=evidence_ids,
                status_tag="failed",
                audit_event_type="runtime.step.failed",
                event_topic="runtime.step_failed",
            )
            return self._raise_with_checkpoint(exc, checkpoint)

        self.budget_guard.record_tool_call()
        checkpoint = self.checkpoint_store.save_success(
            run_id=context.run_id,
            trading_day=context.trading_day,
            agent=context.agent,
            step=step,
            input_refs=input_refs,
            output_refs=output_refs,
            payload=payload,
        )
        self._record_side_effects(
            context,
            step,
            status_tag="success",
            audit_event_type="runtime.step.success",
            event_topic="runtime.step_succeeded",
            checkpoint=checkpoint,
            evidence_ids=evidence_ids,
        )
        return StepResult(
            status="success",
            step=step,
            output_refs=output_refs,
            payload=payload,
            checkpoint=checkpoint,
        )

    def _skip(self, context: AgentRunContext, step: str) -> StepResult:
        checkpoint = self.checkpoint_store.load(run_id=context.run_id, step=step)
        self._record_side_effects(
            context,
            step,
            status_tag="skipped",
            audit_event_type="runtime.step.skipped",
            event_topic="runtime.step_skipped",
            checkpoint=checkpoint,
            evidence_ids=[],
        )
        return StepResult(
            status="skipped",
            step=step,
            output_refs=checkpoint.output_refs if checkpoint else [],
            payload=checkpoint.payload if checkpoint else {},
            checkpoint=checkpoint,
        )

    def _record_failure(
        self,
        context: AgentRunContext,
        step: str,
        error: str,
        *,
        input_refs: list[str],
        output_refs: list[str],
        payload: dict[str, Any],
        evidence_ids: list[str],
        status_tag: str,
        audit_event_type: str,
        event_topic: str,
    ) -> RuntimeCheckpoint:
        checkpoint = self.checkpoint_store.save_failed(
            run_id=context.run_id,
            trading_day=context.trading_day,
            agent=context.agent,
            step=step,
            error=error,
            input_refs=input_refs,
            output_refs=output_refs,
            payload=payload,
        )
        if status_tag == "budget_exceeded":
            self.trace_logger.record(
                agent=context.agent,
                step=step,
                run_id=context.run_id,
                status="failed",
                input_refs=input_refs,
                output_refs=output_refs,
                evidence_ids=evidence_ids,
                error=error,
            )
        self._record_side_effects(
            context,
            step,
            status_tag=status_tag,
            audit_event_type=audit_event_type,
            event_topic=event_topic,
            checkpoint=checkpoint,
            evidence_ids=evidence_ids,
        )
        return checkpoint

    def _record_side_effects(
        self,
        context: AgentRunContext,
        step: str,
        *,
        status_tag: str,
        audit_event_type: str,
        event_topic: str,
        checkpoint: RuntimeCheckpoint | None,
        evidence_ids: list[str],
    ) -> None:
        payload = {
            "run_id": context.run_id,
            "agent": context.agent,
            "step": step,
            "status": status_tag,
            "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
            "budget": self.budget_guard.metrics_fields(),
        }
        self.metrics_recorder.record(
            "runtime_step_total",
            1,
            tags={"agent": context.agent, "step": step, "status": status_tag},
            run_id=context.run_id,
        )
        self.audit_ledger.write(audit_event_type, payload)
        self.event_bus.publish(
            event_topic,
            payload,
            producer=context.agent,
            trading_day=context.trading_day,
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            evidence_ids=evidence_ids,
        )

    def _normalize_result(self, raw_result: Any) -> tuple[dict[str, Any], list[str], str]:
        if raw_result is None:
            return {}, [], ""
        if isinstance(raw_result, BaseModel):
            return raw_result.model_dump(mode="json"), [], ""
        if isinstance(raw_result, dict):
            output_refs = list(raw_result.get("output_refs", []))
            summary = str(raw_result.get("summary", ""))
            payload = raw_result.get("payload")
            if payload is None:
                payload = {
                    key: value
                    for key, value in raw_result.items()
                    if key not in {"output_refs", "summary"}
                }
            return dict(payload), output_refs, summary
        return {"value": raw_result}, [], ""

    def _raise_with_checkpoint(self, exc: Exception, checkpoint: RuntimeCheckpoint) -> StepResult:
        raise exc
