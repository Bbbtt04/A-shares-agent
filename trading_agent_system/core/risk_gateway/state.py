from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.schemas import AccountSnapshot, BrokerOrder, MarketBar, PositionSnapshot, TradeIntent


def deep_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


@dataclass
class RiskGatewayState:
    config: dict[str, Any]
    account: AccountSnapshot | None = None
    positions: PositionSnapshot = field(default_factory=PositionSnapshot)
    open_orders: list[BrokerOrder] = field(default_factory=list)
    latest_bars: dict[str, MarketBar] = field(default_factory=dict)
    market_data_delay_ms: dict[str, int] = field(default_factory=dict)
    intent_seen_at: dict[str, list[datetime]] = field(default_factory=dict)
    premarket_context: PremarketContext | None = None
    approval_queue: list[dict[str, Any]] = field(default_factory=list)

    def update_account(self, account: AccountSnapshot) -> None:
        self.account = account

    def update_positions(self, positions: PositionSnapshot) -> None:
        self.positions = positions

    def update_bar(self, bar: MarketBar, delay_ms: int = 0) -> None:
        self.latest_bars[bar.symbol] = bar
        self.market_data_delay_ms[bar.symbol] = delay_ms

    def update_order(self, order: BrokerOrder) -> None:
        self.open_orders = [
            existing
            for existing in self.open_orders
            if existing.order_id != order.order_id
            and existing.status not in {"filled", "cancelled", "rejected", "expired"}
        ]
        if order.status in {"created", "submitted", "partially_filled"}:
            self.open_orders.append(order)

    def update_premarket_context(self, context: PremarketContext) -> None:
        self.premarket_context = context

    def queue_manual_review(self, intent: TradeIntent, decision: object) -> dict[str, Any]:
        item = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "intent": intent.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json") if hasattr(decision, "model_dump") else decision,
            "premarket": intent.metadata.get("premarket", {}),
        }
        self.approval_queue.append(item)
        return item

    def mark_intent(self, intent: TradeIntent) -> None:
        self.intent_seen_at.setdefault(intent.symbol, []).append(datetime.now(timezone.utc))

    def nav(self) -> float:
        return self.account.nav if self.account else 0

    def cash(self) -> float:
        return self.account.cash if self.account else 0

    def position_qty(self, symbol: str) -> int:
        return self.positions.positions.get(symbol, 0)

    def open_orders_for_symbol(self, symbol: str) -> list[BrokerOrder]:
        return [order for order in self.open_orders if order.symbol == symbol]

    def config_value(self, path: str, default: Any = None) -> Any:
        return deep_get(self.config, path, default)
