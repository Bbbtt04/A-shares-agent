from __future__ import annotations

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.strategy_registry import StrategyRegistry
from trading_agent_system.schemas import AccountSnapshot, IntelBrief, MarketBar, PositionSnapshot, TradeIntent

from .feature_builder import FeatureBuilder
from .market_state import MarketStateMonitor
from .position_guardian import PositionGuardian
from .signal_engine import SignalEngine
from .trade_planner import TradePlanner


class IntradayAgent:
    allowed_publish_topics = {"trading.intents", "system.alerts"}

    def __init__(
        self,
        watchlist: list[str],
        strategy_registry: StrategyRegistry,
        event_bus: MemoryEventBus,
        audit: AuditLedger,
        max_market_data_delay_ms: int = 1000,
        premarket_context: PremarketContext | None = None,
    ) -> None:
        self.watchlist = watchlist
        self.strategy_registry = strategy_registry
        self.event_bus = event_bus
        self.audit = audit
        self.market_state_monitor = MarketStateMonitor(max_market_data_delay_ms)
        self.feature_builder = FeatureBuilder()
        self.signal_engine = SignalEngine()
        self.trade_planner = TradePlanner()
        self.position_guardian = PositionGuardian()
        self.bars: dict[str, list[MarketBar]] = {symbol: [] for symbol in watchlist}
        self.delays_ms: dict[str, int] = {}
        self.intel: list[IntelBrief] = []
        self.positions: PositionSnapshot | None = None
        self.account: AccountSnapshot | None = None
        self.premarket_context = premarket_context

    def ingest_bar(self, bar: MarketBar, delay_ms: int = 0) -> None:
        self.bars.setdefault(bar.symbol, []).append(bar)
        self.delays_ms[bar.symbol] = delay_ms

    def ingest_intel(self, brief: IntelBrief) -> None:
        self.intel.append(brief)

    def ingest_positions(self, positions: PositionSnapshot) -> None:
        self.positions = positions

    def ingest_account(self, account: AccountSnapshot) -> None:
        self.account = account

    def ingest_premarket_context(self, context: PremarketContext) -> None:
        self.premarket_context = context

    def scan(self) -> list[TradeIntent]:
        market_state = self.market_state_monitor.build(self.bars, self.delays_ms, self.intel)
        if market_state.data_quality != "ok":
            self.audit.warn("market_data_not_ok", market_state)
            return []
        intents: list[TradeIntent] = []
        for symbol in self.watchlist:
            symbol_bars = self.bars.get(symbol, [])
            if not symbol_bars:
                continue
            snapshot = self.feature_builder.build(symbol, symbol_bars, self.intel, market_state)
            candidates = self.signal_engine.evaluate(
                symbol=symbol,
                snapshot=snapshot,
                market_state=market_state,
                strategy_registry=self.strategy_registry,
                intel=self.intel,
                last_price=symbol_bars[-1].close,
            )
            self.audit.write("feature_snapshot", snapshot)
            for candidate in candidates:
                intent = self.trade_planner.plan(candidate, snapshot, market_state, self.intel, self.premarket_context)
                if intent is None:
                    self.audit.write("trade_intent_filtered", candidate)
                    continue
                self._publish("trading.intents", intent)
                self.audit.write("trade_intent_created", intent)
                intents.append(intent)
        return intents

    def _publish(self, topic: str, event: object) -> None:
        if topic not in self.allowed_publish_topics:
            raise PermissionError(f"IntradayAgent cannot publish {topic}")
        self.event_bus.publish(topic, event)
