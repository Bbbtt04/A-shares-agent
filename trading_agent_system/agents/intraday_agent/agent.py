from __future__ import annotations

from trading_agent_system.core.audit import AuditLedger
from trading_agent_system.core.event_bus import MemoryEventBus
from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.core.strategy_registry import StrategyRegistry
from trading_agent_system.schemas import (
    AccountSnapshot,
    FeatureSnapshot,
    IntelBrief,
    IntradayAnalysisReport,
    MarketBar,
    MarketState,
    SignalCandidate,
    PositionSnapshot,
    TradeIntent,
)

from .analysis import build_intraday_analysis_report
from .feature_builder import FeatureBuilder
from .market_state import MarketStateMonitor
from .position_guardian import PositionGuardian
from .signal_engine import SignalEngine
from .trade_planner import TradePlanner


class IntradayAgent:
    allowed_publish_topics = {"intraday.analysis", "trading.intents", "system.alerts"}

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
        self.latest_analysis_report: IntradayAnalysisReport | None = None

    def ingest_bar(self, bar: MarketBar, delay_ms: int = 0) -> None:
        self.bars.setdefault(bar.symbol, []).append(bar)
        self.delays_ms[bar.symbol] = delay_ms

    def ingest_intel(self, brief: IntelBrief | dict[str, object]) -> None:
        self.intel.append(brief if isinstance(brief, IntelBrief) else IntelBrief.model_validate(brief))

    def ingest_positions(self, positions: PositionSnapshot) -> None:
        self.positions = positions

    def ingest_account(self, account: AccountSnapshot) -> None:
        self.account = account

    def ingest_premarket_context(self, context: PremarketContext) -> None:
        self.premarket_context = context

    def scan(self) -> list[TradeIntent]:
        market_state = self.market_state_monitor.build(self.bars, self.delays_ms, self.intel)
        snapshots: dict[str, FeatureSnapshot] = {}
        latest_prices: dict[str, float] = {}
        candidates_by_symbol: dict[str, list[SignalCandidate]] = {}
        filtered_reasons: dict[str, str] = {}
        planned_signal_ids: set[str] = set()
        intents_by_symbol: dict[str, list[TradeIntent]] = {}
        warnings: list[str] = []
        if market_state.data_quality != "ok":
            self.audit.warn("market_data_not_ok", market_state)
            warnings.extend(market_state.reasons)
            self._publish_analysis(
                market_state=market_state,
                snapshots=snapshots,
                latest_prices=latest_prices,
                candidates_by_symbol=candidates_by_symbol,
                filtered_reasons=filtered_reasons,
                planned_signal_ids=planned_signal_ids,
                intents_by_symbol=intents_by_symbol,
                generated_intents=[],
                warnings=warnings,
            )
            return []
        intents: list[TradeIntent] = []
        for symbol in self.watchlist:
            symbol_bars = self.bars.get(symbol, [])
            if not symbol_bars:
                warnings.append(f"{symbol}: no market bars")
                continue
            latest_prices[symbol] = symbol_bars[-1].close
            snapshot = self.feature_builder.build(
                symbol,
                symbol_bars,
                self.intel,
                market_state,
                premarket_context=self.premarket_context,
                peer_bars=self.bars,
            )
            snapshots[symbol] = snapshot
            candidates = self.signal_engine.evaluate(
                symbol=symbol,
                snapshot=snapshot,
                market_state=market_state,
                strategy_registry=self.strategy_registry,
                intel=self.intel,
                last_price=symbol_bars[-1].close,
            )
            candidates_by_symbol[symbol] = candidates
            self.audit.write("feature_snapshot", snapshot)
            for candidate in candidates:
                filter_reason = self.trade_planner.filter_reason(
                    candidate,
                    snapshot,
                    market_state,
                    self.intel,
                    self.premarket_context,
                )
                if filter_reason is not None:
                    filtered_reasons[candidate.signal_id] = filter_reason
                    self.audit.write("trade_intent_filtered", candidate)
                    continue
                intent = self.trade_planner.plan(candidate, snapshot, market_state, self.intel, self.premarket_context)
                if intent is None:
                    filtered_reasons[candidate.signal_id] = "unknown_filter"
                    self.audit.write("trade_intent_filtered", candidate)
                    continue
                planned_signal_ids.add(candidate.signal_id)
                self._publish("trading.intents", intent)
                self.audit.write("trade_intent_created", intent)
                intents.append(intent)
                intents_by_symbol.setdefault(symbol, []).append(intent)
        self._publish_analysis(
            market_state=market_state,
            snapshots=snapshots,
            latest_prices=latest_prices,
            candidates_by_symbol=candidates_by_symbol,
            filtered_reasons=filtered_reasons,
            planned_signal_ids=planned_signal_ids,
            intents_by_symbol=intents_by_symbol,
            generated_intents=intents,
            warnings=warnings,
        )
        return intents

    def _publish_analysis(
        self,
        *,
        market_state: MarketState,
        snapshots: dict[str, FeatureSnapshot],
        latest_prices: dict[str, float],
        candidates_by_symbol: dict[str, list[SignalCandidate]],
        filtered_reasons: dict[str, str],
        planned_signal_ids: set[str],
        intents_by_symbol: dict[str, list[TradeIntent]],
        generated_intents: list[TradeIntent],
        warnings: list[str],
    ) -> None:
        report = build_intraday_analysis_report(
            watchlist=self.watchlist,
            market_state=market_state,
            snapshots=snapshots,
            latest_prices=latest_prices,
            candidates_by_symbol=candidates_by_symbol,
            filtered_reasons=filtered_reasons,
            planned_signal_ids=planned_signal_ids,
            intents_by_symbol=intents_by_symbol,
            generated_intents=generated_intents,
            premarket_context=self.premarket_context,
            warnings=warnings,
        )
        self.latest_analysis_report = report
        self._publish("intraday.analysis", report)
        self.audit.write("intraday_analysis_report", report)

    def _publish(self, topic: str, event: object) -> None:
        if topic not in self.allowed_publish_topics:
            raise PermissionError(f"IntradayAgent cannot publish {topic}")
        evidence_ids = getattr(event, "evidence_ids", None)
        trading_day = self.premarket_context.trading_day if self.premarket_context else None
        self.event_bus.publish(
            topic,
            event,
            producer="intraday_agent",
            trading_day=trading_day,
            evidence_ids=list(evidence_ids or []),
        )
