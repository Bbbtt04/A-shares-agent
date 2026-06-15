from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from .candidate_generator import CandidateGenerator
from .schemas import (
    EffectiveOnePickStrategy,
    OnePickCandidate,
    OnePickPremarketResult,
    OnePickSelection,
    OnePickTradePlan,
)
from .stock_selector import StockSelector
from .strategy_loader import OnePickStrategyLoader
from .trade_plan import TradePlanAgent
from trading_agent_system.schemas import make_id


class RiskGatewayPort(Protocol):
    def on_trade_intent(self, intent: Any) -> Any:
        ...

    def to_order_instruction(self, intent: Any, decision: Any) -> Any:
        ...


class PaperBrokerPort(Protocol):
    def on_order_instruction(self, instruction: Any) -> Any:
        ...


@dataclass
class OnePickRuntimePorts:
    step_runner: Any | None = None
    run_context: Any | None = None
    risk_gateway: RiskGatewayPort | None = None
    paper_broker: PaperBrokerPort | None = None
    event_bus: Any | None = None
    audit_ledger: Any | None = None
    llm_gateway: Any | None = None


@dataclass
class OnePickAgent:
    strategy_loader: OnePickStrategyLoader | Callable[[], EffectiveOnePickStrategy] | None = None
    candidate_generator: CandidateGenerator = field(default_factory=CandidateGenerator)
    stock_selector: StockSelector = field(default_factory=StockSelector)
    trade_plan_agent: TradePlanAgent | None = None
    ports: OnePickRuntimePorts = field(default_factory=OnePickRuntimePorts)
    submitted_buys: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.strategy_loader is None:
            self.strategy_loader = OnePickStrategyLoader()
        if self.trade_plan_agent is None:
            self.trade_plan_agent = TradePlanAgent(llm_gateway=self.ports.llm_gateway)

    def run_premarket(
        self,
        *,
        events: list[Any],
        evidence_packs: list[Any] | None = None,
        event_clusters: list[Any] | None = None,
        market_snapshots: dict[str, Any] | None = None,
        force: bool = False,
    ) -> OnePickPremarketResult:
        strategy = self._load_strategy()
        candidates = self._run_step(
            "candidates_generated",
            lambda: self.candidate_generator.generate(
                events=events,
                event_clusters=event_clusters,
                evidence_packs=evidence_packs or [],
                market_snapshots=market_snapshots or {},
            ),
            force=force,
            decoder=_decode_candidates,
        )
        selection = self._run_step(
            "stock_selected",
            lambda: self.stock_selector.select(candidates, strategy),
            force=force,
            decoder=_decode_selection,
        )
        last_price = self._last_price(selection.selected_symbol, market_snapshots or {})
        trade_plan = self._run_step(
            "trade_plan_created",
            lambda: self.trade_plan_agent.create_plan(selection, strategy, last_price=last_price),  # type: ignore[union-attr]
            force=force,
            decoder=_decode_trade_plan,
        )
        self._publish("one_pick.trade_plan_created", trade_plan)
        buy_submission = self._run_step(
            "buy_order_submitted",
            lambda: self.submit_buy(trade_plan, strategy),
            force=force,
        )
        return OnePickPremarketResult(
            strategy=strategy,
            candidates=candidates,
            selection=selection,
            trade_plan=trade_plan,
            buy_submission=buy_submission,
        )

    def submit_buy(self, plan: OnePickTradePlan, strategy: EffectiveOnePickStrategy) -> dict[str, Any] | None:
        if plan.plan_id in self.submitted_buys:
            return self.submitted_buys[plan.plan_id]
        if self.ports.risk_gateway is None or self.ports.paper_broker is None:
            return None
        intent = self.trade_plan_agent.to_trade_intent(plan, strategy)  # type: ignore[union-attr]
        decision = self.ports.risk_gateway.on_trade_intent(intent)
        if getattr(decision, "decision", None) != "approved":
            submission = _AttrDict(intent=intent, decision=decision, instruction=None, order=None)
            self.submitted_buys[plan.plan_id] = submission
            return submission
        instruction = self.ports.risk_gateway.to_order_instruction(intent, decision)
        order = self.ports.paper_broker.on_order_instruction(instruction)
        submission = _AttrDict(intent=intent, decision=decision, instruction=instruction, order=order)
        self.submitted_buys[plan.plan_id] = submission
        self._publish("one_pick.buy_order_submitted", submission)
        return submission

    def _load_strategy(self) -> EffectiveOnePickStrategy:
        loader = self.strategy_loader
        if callable(loader) and not hasattr(loader, "load"):
            return loader()
        return loader.load()  # type: ignore[union-attr]

    def _run_step(
        self,
        step_name: str,
        func: Callable[[], Any],
        *,
        force: bool = False,
        decoder: Callable[[Any], Any] | None = None,
    ) -> Any:
        runner = self.ports.step_runner
        if runner is None:
            return func()
        if _looks_like_formal_step_runner(runner):
            context = self._run_context()

            def wrapped(_context: Any) -> dict[str, Any]:
                value = func()
                json_value = _jsonable(value)
                payload = {"value": json_value}
                named_key = _payload_key(step_name)
                if named_key:
                    payload[named_key] = json_value
                return {
                    "payload": payload,
                    "output_refs": _output_refs(value),
                    "summary": step_name,
                }

            result = runner.run(context, step=step_name, fn=wrapped, force=force)
            value = result.payload.get("value")
            return decoder(value) if decoder else value
        if hasattr(runner, "run"):
            return runner.run(step_name, func, force=force)
        if hasattr(runner, "run_step"):
            return runner.run_step(step_name, func, force=force)
        raise TypeError("step_runner must expose run() or run_step()")

    def _run_context(self) -> Any:
        if self.ports.run_context is not None:
            return self.ports.run_context
        from trading_agent_system.core.runtime import AgentRunContext

        self.ports.run_context = AgentRunContext(
            run_id=make_id("onepick_run"),
            agent="one_pick_agent",
            permission_profile="paper",
        )
        return self.ports.run_context

    def _last_price(self, symbol: str, market_snapshots: dict[str, Any]) -> float:
        snapshot = market_snapshots.get(symbol, {})
        if isinstance(snapshot, dict):
            value = snapshot.get("last_price", snapshot.get("price", snapshot.get("close")))
        else:
            value = getattr(snapshot, "last_price", getattr(snapshot, "price", getattr(snapshot, "close", None)))
        if value is None:
            return 1.0
        return float(value)

    def _publish(self, topic: str, payload: Any) -> None:
        if self.ports.event_bus is not None:
            self.ports.event_bus.publish(topic, _jsonable(payload), producer="one_pick_agent")
        if self.ports.audit_ledger is not None:
            self.ports.audit_ledger.write(topic, _jsonable(payload))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


class _AttrDict(dict):
    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def _looks_like_formal_step_runner(runner: Any) -> bool:
    return hasattr(runner, "checkpoint_store") and hasattr(runner, "budget_guard")


def _output_refs(value: Any) -> list[str]:
    if isinstance(value, list):
        refs: list[str] = []
        for item in value:
            refs.extend(_output_refs(item))
        return refs
    for attr in ("candidate_id", "selection_id", "plan_id", "execution_id", "exit_plan_id", "outcome_id"):
        ref = getattr(value, attr, None)
        if ref:
            return [str(ref)]
    if isinstance(value, dict):
        for key in ("candidate_id", "selection_id", "plan_id", "execution_id", "exit_plan_id", "outcome_id"):
            if value.get(key):
                return [str(value[key])]
    return []


def _decode_candidates(value: Any) -> list[OnePickCandidate]:
    return [item if isinstance(item, OnePickCandidate) else OnePickCandidate.model_validate(item) for item in value or []]


def _decode_selection(value: Any) -> OnePickSelection:
    return value if isinstance(value, OnePickSelection) else OnePickSelection.model_validate(value)


def _decode_trade_plan(value: Any) -> OnePickTradePlan:
    return value if isinstance(value, OnePickTradePlan) else OnePickTradePlan.model_validate(value)


def _payload_key(step_name: str) -> str | None:
    return {
        "candidates_generated": "candidates",
        "stock_selected": "selection",
        "trade_plan_created": "trade_plan",
        "buy_order_submitted": "buy_submission",
    }.get(step_name)
