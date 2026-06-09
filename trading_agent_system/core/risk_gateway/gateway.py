from __future__ import annotations

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.schemas import CheckResult, OrderInstruction, RiskDecision, TradeIntent

from .checks import DEFAULT_CHECKS, RiskCheck
from .state import RiskGatewayState


class RiskGateway:
    def __init__(
        self,
        state: RiskGatewayState,
        event_bus: MemoryEventBus,
        audit: AuditLedger,
        checks: list[RiskCheck] | None = None,
    ) -> None:
        self.state = state
        self.event_bus = event_bus
        self.audit = audit
        self.checks = checks or DEFAULT_CHECKS

    def on_trade_intent(self, intent: TradeIntent) -> RiskDecision:
        results: list[CheckResult] = []
        for check in self.checks:
            result = check.run(intent, self.state)
            results.append(result)
            if result.status == "hard_reject":
                decision = self._decision(intent, "rejected", 0, None, result.reason, results)
                return self._publish_decision(decision, intent)
            if result.status == "needs_human_approval":
                decision = self._decision(intent, "needs_human_approval", 0, None, result.reason, results)
                return self._publish_decision(decision, intent)

        approved_quantity = self._apply_position_sizer(intent, results)
        if approved_quantity <= 0:
            decision = self._decision(intent, "rejected", 0, None, "approved_quantity_zero", results)
            return self._publish_decision(decision, intent)

        approved_price = intent.limit_price
        decision = self._decision(intent, "approved", approved_quantity, approved_price, "approved", results)
        self._publish_decision(decision, intent)
        instruction = self.to_order_instruction(intent, decision)
        self.event_bus.publish("orders.instructions", instruction)
        self.audit.write("order_instruction_created", instruction)
        self.state.mark_intent(intent)
        return decision

    def to_order_instruction(self, intent: TradeIntent, decision: RiskDecision) -> OrderInstruction:
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

    def _apply_position_sizer(self, intent: TradeIntent, results: list[CheckResult]) -> int:
        quantity = intent.quantity
        for result in results:
            if result.status != "scale_down":
                continue
            nav = float(result.details.get("nav", 0))
            max_pct = float(result.details.get("max_pct", 0))
            price = intent.limit_price or self.state.latest_bars[intent.symbol].close
            current_value = abs(self.state.position_qty(intent.symbol)) * price
            allowed_value = max(0.0, nav * max_pct - current_value)
            quantity = min(quantity, int(allowed_value // price // 100 * 100))
        return quantity

    def _decision(
        self,
        intent: TradeIntent,
        decision: str,
        approved_quantity: int,
        approved_price: float | None,
        reason: str,
        results: list[CheckResult],
    ) -> RiskDecision:
        checks = {result.check_name: result for result in results}
        return RiskDecision(
            intent_id=intent.intent_id,
            decision=decision,
            approved_quantity=approved_quantity,
            approved_price=approved_price,
            reason=reason,
            checks=checks,
        )

    def _publish_decision(self, decision: RiskDecision, intent: TradeIntent | None = None) -> RiskDecision:
        self.event_bus.publish("risk.decisions", decision, producer="risk_gateway")
        if intent is not None and decision.decision == "needs_human_approval":
            queue_item = self.state.queue_manual_review(intent, decision)
            self.event_bus.publish(
                "risk.approval_queue",
                queue_item,
                producer="risk_gateway",
                evidence_ids=intent.evidence_ids,
            )
            self.audit.write("risk_approval_queued", queue_item)
        self.audit.write("risk_decision", decision)
        return decision
