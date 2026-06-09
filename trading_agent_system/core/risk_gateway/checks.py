from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from trading_agent_system.schemas import CheckResult, TradeIntent

from .state import RiskGatewayState


class RiskCheck(Protocol):
    name: str

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        ...


def passed(name: str, reason: str, **details: object) -> CheckResult:
    return CheckResult(check_name=name, status="pass", reason=reason, details=dict(details))


def rejected(name: str, reason: str, **details: object) -> CheckResult:
    return CheckResult(check_name=name, status="hard_reject", reason=reason, details=dict(details))


class GlobalTradingEnabledCheck:
    name = "global_trading_enabled"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if state.config_value("global.trading_enabled", False):
            return passed(self.name, "trading_enabled")
        if intent.side == "sell" and state.config_value("global.allow_reduce_only", True):
            current_qty = state.position_qty(intent.symbol)
            if current_qty > 0:
                return passed(self.name, "reduce_only_sell_allowed", position=current_qty)
        return rejected(self.name, "trading_disabled")


class KillSwitchCheck:
    name = "kill_switch"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if state.config_value("global.kill_switch", False):
            return rejected(self.name, "kill_switch_enabled")
        return passed(self.name, "kill_switch_clear")


class TradingSessionCheck:
    name = "trading_session"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        return passed(self.name, "paper_session_open")


class MarketDataFreshnessCheck:
    name = "market_data_freshness"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        delay_ms = state.market_data_delay_ms.get(intent.symbol)
        if delay_ms is None:
            return rejected(self.name, "missing_market_data_delay")
        limit = state.config_value("limits.max_market_data_delay_ms", 1000)
        if delay_ms > limit:
            return rejected(self.name, "market_data_stale", delay_ms=delay_ms, max_delay_ms=limit)
        return passed(self.name, "market_data_fresh", delay_ms=delay_ms)


class StrategyAllowedCheck:
    name = "strategy_allowed"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if intent.strategy_id in state.config_value("blacklists.strategies", []):
            return rejected(self.name, "strategy_blacklisted")
        allowed = state.config_value("strategies.allowed", ["*"])
        disabled = state.config_value("strategies.disabled", [])
        if intent.strategy_id in disabled:
            return rejected(self.name, "strategy_disabled")
        if "*" not in allowed and intent.strategy_id not in allowed:
            return rejected(self.name, "strategy_not_allowed")
        return passed(self.name, "strategy_allowed")


class SymbolAllowedCheck:
    name = "symbol_allowed"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        allowed = state.config_value("symbols.allowed", ["*"])
        if "*" not in allowed and intent.symbol not in allowed:
            return rejected(self.name, "symbol_not_allowed")
        return passed(self.name, "symbol_allowed")


class PremarketConstraintCheck:
    name = "premarket_constraints"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        context = state.premarket_context
        if context is None or intent.side != "buy":
            return passed(self.name, "premarket_context_not_applicable")
        metadata = context.metadata_for(intent.symbol)
        if metadata["blocks_new_entry"]:
            return rejected(
                self.name,
                "premarket_avoid_new_entry",
                instruction_types=metadata["matched_instruction_types"],
                reasons=metadata["reasons"],
                evidence_ids=metadata["evidence_ids"],
            )
        if metadata["requires_confirmation"]:
            return CheckResult(
                check_name=self.name,
                status="needs_human_approval",
                reason="premarket_requires_confirmation",
                details={
                    "instruction_types": metadata["matched_instruction_types"],
                    "reasons": metadata["reasons"],
                    "evidence_ids": metadata["evidence_ids"],
                },
            )
        return passed(self.name, "premarket_constraints_clear", instruction_types=metadata["matched_instruction_types"])


class BlacklistCheck:
    name = "blacklist"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if intent.symbol in state.config_value("blacklists.symbols", []):
            return rejected(self.name, "symbol_blacklisted")
        if any(flag in state.config_value("blacklists.event_types", []) for flag in intent.metadata.get("risk_flags", [])):
            return rejected(self.name, "event_type_blacklisted")
        return passed(self.name, "not_blacklisted")


class OrderTypeCheck:
    name = "order_type"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if intent.order_type == "marketable_limit" and state.config_value("price.reject_market_orders", True):
            return rejected(self.name, "market_orders_rejected")
        return passed(self.name, "order_type_allowed")


class PriceBandCheck:
    name = "price_band"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if not state.config_value("price.require_price_band_check", True):
            return passed(self.name, "price_band_check_disabled")
        bar = state.latest_bars.get(intent.symbol)
        if bar is None:
            return rejected(self.name, "missing_reference_price")
        price = intent.limit_price or bar.close
        max_bps = state.config_value("price.max_limit_price_deviation_bps", 50)
        deviation_bps = abs(price - bar.close) / bar.close * 10000
        if deviation_bps > max_bps:
            return rejected(
                self.name,
                "limit_price_deviation_too_large",
                deviation_bps=round(deviation_bps, 4),
                max_bps=max_bps,
            )
        return passed(self.name, "price_within_band", deviation_bps=round(deviation_bps, 4))


class LotSizeCheck:
    name = "lot_size"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        lot_size = state.config_value("symbols.lot_size", 100)
        if intent.quantity % lot_size != 0:
            return rejected(self.name, "quantity_not_lot_aligned", lot_size=lot_size)
        return passed(self.name, "lot_size_ok", lot_size=lot_size)


class AccountCashCheck:
    name = "account_cash"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if intent.side == "sell":
            return passed(self.name, "sell_does_not_require_cash")
        if state.account is None:
            return rejected(self.name, "missing_account_snapshot")
        price = intent.limit_price or state.latest_bars.get(intent.symbol).close
        needed = price * intent.quantity
        if needed > state.cash():
            return rejected(self.name, "insufficient_cash", required=needed, cash=state.cash())
        return passed(self.name, "cash_available", required=needed, cash=state.cash())


class PositionLimitCheck:
    name = "position_limit"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if state.account is None:
            return rejected(self.name, "missing_account_snapshot")
        nav = state.nav()
        max_pct = state.config_value("limits.max_position_pct_nav_per_symbol", 0)
        if max_pct <= 0:
            return rejected(self.name, "position_limit_zero")
        bar = state.latest_bars.get(intent.symbol)
        if bar is None:
            return rejected(self.name, "missing_reference_price")
        current_value = abs(state.position_qty(intent.symbol)) * bar.close
        next_value = current_value + (intent.quantity * (intent.limit_price or bar.close))
        if nav <= 0:
            return rejected(self.name, "invalid_nav")
        if next_value / nav > max_pct:
            return CheckResult(
                check_name=self.name,
                status="scale_down",
                reason="position_limit_scaled_down",
                details={"next_value": next_value, "nav": nav, "max_pct": max_pct},
            )
        return passed(self.name, "position_limit_ok", next_value=next_value, nav=nav)


class GrossExposureCheck:
    name = "gross_exposure"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if state.account is None:
            return rejected(self.name, "missing_account_snapshot")
        max_pct = state.config_value("limits.max_total_gross_exposure_pct_nav", 0)
        if max_pct <= 0:
            return rejected(self.name, "gross_exposure_limit_zero")
        bar = state.latest_bars.get(intent.symbol)
        if bar is None:
            return rejected(self.name, "missing_reference_price")
        projected = state.account.gross_exposure + intent.quantity * (intent.limit_price or bar.close)
        if state.nav() <= 0 or projected / state.nav() > max_pct:
            return rejected(self.name, "gross_exposure_limit_breach", projected=projected, nav=state.nav())
        return passed(self.name, "gross_exposure_ok", projected=projected, nav=state.nav())


class DailyLossLimitCheck:
    name = "daily_loss_limit"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if state.account is None:
            return rejected(self.name, "missing_account_snapshot")
        max_loss_pct = state.config_value("limits.max_daily_loss_pct_nav", 0)
        if max_loss_pct <= 0:
            return passed(self.name, "daily_loss_limit_disabled")
        if state.nav() > 0 and abs(min(0, state.account.daily_loss)) / state.nav() > max_loss_pct:
            return rejected(self.name, "daily_loss_limit_breach")
        return passed(self.name, "daily_loss_ok")


class OrderFrequencyCheck:
    name = "order_frequency"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        max_per_minute = state.config_value("limits.max_orders_per_minute", 5)
        one_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        recent = [ts for timestamps in state.intent_seen_at.values() for ts in timestamps if ts >= one_minute_ago]
        if len(recent) >= max_per_minute:
            return rejected(self.name, "order_frequency_limit_breach", recent=len(recent), max=max_per_minute)
        return passed(self.name, "order_frequency_ok", recent=len(recent))


class DuplicateIntentCheck:
    name = "duplicate_intent"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        max_dup = state.config_value("limits.max_duplicate_intents_per_symbol_per_minute", 1)
        one_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        recent = [ts for ts in state.intent_seen_at.get(intent.symbol, []) if ts >= one_minute_ago]
        if len(recent) >= max_dup:
            return rejected(self.name, "duplicate_intent_limit_breach", symbol=intent.symbol, recent=len(recent))
        return passed(self.name, "duplicate_intent_ok", symbol=intent.symbol, recent=len(recent))


class OpenOrderLimitCheck:
    name = "open_order_limit"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        max_open = state.config_value("limits.max_open_orders_per_symbol", 2)
        open_count = len(state.open_orders_for_symbol(intent.symbol))
        if open_count >= max_open:
            return rejected(self.name, "open_order_limit_breach", open_count=open_count, max=max_open)
        return passed(self.name, "open_order_limit_ok", open_count=open_count)


class LiquidityCheck:
    name = "liquidity"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        max_spread = state.config_value("liquidity.max_spread_bps", 0)
        spread = intent.metadata.get("spread_bps", 0)
        if max_spread > 0 and spread > max_spread:
            return rejected(self.name, "spread_too_wide", spread_bps=spread, max_spread_bps=max_spread)
        return passed(self.name, "liquidity_ok", spread_bps=spread)


class HumanApprovalCheck:
    name = "human_approval"

    def run(self, intent: TradeIntent, state: RiskGatewayState) -> CheckResult:
        if not state.config_value("global.require_human_approval", True):
            return passed(self.name, "human_approval_not_required")
        low_conf_required = state.config_value("human_approval.required_for_low_confidence", True)
        low_conf_threshold = state.config_value("human_approval.low_confidence_threshold", 0.6)
        if low_conf_required and intent.confidence < low_conf_threshold:
            return CheckResult(
                check_name=self.name,
                status="needs_human_approval",
                reason="low_confidence_requires_human_approval",
                details={"confidence": intent.confidence, "threshold": low_conf_threshold},
            )
        required_value = state.config_value("human_approval.required_above_order_value", 0)
        price = intent.limit_price or state.latest_bars.get(intent.symbol).close
        order_value = price * intent.quantity
        if required_value <= 0 or order_value >= required_value:
            return CheckResult(
                check_name=self.name,
                status="needs_human_approval",
                reason="order_requires_human_approval",
                details={"order_value": order_value, "threshold": required_value},
            )
        return passed(self.name, "human_approval_not_triggered")


DEFAULT_CHECKS: list[RiskCheck] = [
    GlobalTradingEnabledCheck(),
    KillSwitchCheck(),
    TradingSessionCheck(),
    MarketDataFreshnessCheck(),
    StrategyAllowedCheck(),
    SymbolAllowedCheck(),
    PremarketConstraintCheck(),
    BlacklistCheck(),
    OrderTypeCheck(),
    PriceBandCheck(),
    LotSizeCheck(),
    AccountCashCheck(),
    PositionLimitCheck(),
    GrossExposureCheck(),
    DailyLossLimitCheck(),
    OrderFrequencyCheck(),
    DuplicateIntentCheck(),
    OpenOrderLimitCheck(),
    LiquidityCheck(),
    HumanApprovalCheck(),
]
