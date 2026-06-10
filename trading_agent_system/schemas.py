from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class StrictBaseModel(BaseModel):
    model_config = {"extra": "forbid", "use_enum_values": True}


class MarketBar(StrictBaseModel):
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None

    @model_validator(mode="after")
    def validate_prices(self) -> "MarketBar":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open/close/high")
        return self


class MarketQuote(StrictBaseModel):
    symbol: str
    name: str
    market: Literal["SH", "SZ", "UNKNOWN"] = "UNKNOWN"
    kind: Literal["index", "stock", "fund", "unknown"] = "unknown"
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    previous_close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    quote_ts: datetime | None = None
    source: str = "eastmoney"
    is_realtime: bool = False
    delay_seconds: int | None = None


class StockQuote(StrictBaseModel):
    symbol: str
    code: str
    name: str
    market: Literal["SH", "SZ", "BJ", "UNKNOWN"] = "UNKNOWN"
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    previous_close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover_ratio: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_cap: float | None = None
    float_market_cap: float | None = None
    tick_time: str | None = None
    source: str = "sina"


class IntelBrief(StrictBaseModel):
    event_id: str = Field(default_factory=lambda: make_id("intel"))
    first_seen_at: datetime
    published_at: datetime | None = None
    symbols: list[str]
    event_type: str
    importance: Literal["S", "A", "B", "C"]
    bias: Literal["bullish", "bearish", "neutral", "unclear"]
    confidence: float = Field(ge=0, le=1)
    actionability: Literal["watch", "candidate", "block"]
    summary: str
    evidence: list[dict[str, Any]]
    risk_flags: list[str] = Field(default_factory=list)
    ttl_seconds: int = 21600


class PremarketNewsItem(StrictBaseModel):
    item_id: str = Field(default_factory=lambda: make_id("news"))
    source: str
    source_tier: Literal["official", "professional", "sentiment", "unknown"] = "unknown"
    title: str
    summary: str = ""
    url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    category: str = "unknown"
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    credibility: float = Field(default=0.5, ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)


class PremarketSourceStatus(StrictBaseModel):
    source: str
    status: Literal["ok", "empty", "failed"]
    fetched_count: int = 0
    used_count: int = 0
    error: str | None = None


class PremarketCatalyst(StrictBaseModel):
    title: str
    category: str
    bias: Literal["bullish", "bearish", "neutral", "unclear"]
    confidence: float = Field(ge=0, le=1)
    importance: Literal["S", "A", "B", "C"]
    sources: list[str]
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    summary: str
    risk_flags: list[str] = Field(default_factory=list)


class PremarketTradePlan(StrictBaseModel):
    symbol: str
    name: str | None = None
    action: Literal["watch", "avoid", "block"]
    reason: str
    triggers: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class PremarketReport(StrictBaseModel):
    date: date
    generated_at: datetime = Field(default_factory=utc_now)
    window_start: datetime
    window_end: datetime
    market_view: Literal["positive", "neutral", "cautious"]
    summary: str
    source_status: list[PremarketSourceStatus]
    news_items: list[PremarketNewsItem] = Field(default_factory=list)
    catalysts: list[PremarketCatalyst] = Field(default_factory=list)
    watchlist: list[PremarketTradePlan] = Field(default_factory=list)
    avoid_list: list[PremarketTradePlan] = Field(default_factory=list)
    opening_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    post_close_digest: dict[str, Any] | None = None
    morning_brief: dict[str, Any] | None = None
    opening_radar: dict[str, Any] | None = None
    instruction: dict[str, Any] | None = None
    markdown_report: str = ""


class MarketState(StrictBaseModel):
    ts: datetime
    regime: str
    volatility_level: Literal["low", "normal", "high", "extreme"]
    liquidity_level: Literal["low", "normal", "high"]
    data_quality: Literal["ok", "stale", "missing"]
    risk_mode: Literal["normal", "reduced", "halt_new_entries"]
    reasons: list[str] = Field(default_factory=list)


class FeatureSnapshot(StrictBaseModel):
    snapshot_id: str = Field(default_factory=lambda: make_id("feat"))
    symbol: str
    ts: datetime
    features: dict[str, float | str | bool]
    related_intel_event_ids: list[str] = Field(default_factory=list)


class SignalCandidate(StrictBaseModel):
    signal_id: str = Field(default_factory=lambda: make_id("sig"))
    strategy_id: str
    strategy_version: str
    symbol: str
    side: Literal["buy", "sell"]
    raw_score: float
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    feature_snapshot_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    suggested_quantity: int | None = None
    suggested_limit_price: float | None = None
    invalidation: dict[str, Any] = Field(default_factory=dict)


class TradeIntent(StrictBaseModel):
    intent_id: str = Field(default_factory=lambda: make_id("intent"))
    created_at: datetime = Field(default_factory=utc_now)
    strategy_id: str
    strategy_version: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    order_type: Literal["limit", "marketable_limit"]
    limit_price: float | None = None
    ttl_seconds: int = 30
    confidence: float = Field(ge=0, le=1)
    entry_reason: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    feature_snapshot_id: str
    invalidation: dict[str, Any] = Field(default_factory=dict)
    max_loss_amount: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entry_reason")
    @classmethod
    def require_reason(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("entry_reason is required")
        return value

    @model_validator(mode="after")
    def validate_limit_price(self) -> "TradeIntent":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        return self


class IntradaySignalAnalysis(StrictBaseModel):
    signal_id: str
    strategy_id: str
    strategy_version: str
    side: Literal["buy", "sell"]
    confidence: float = Field(ge=0, le=1)
    status: Literal["planned", "filtered"]
    reasons: list[str] = Field(default_factory=list)
    filter_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class IntradaySymbolAnalysis(StrictBaseModel):
    symbol: str
    ts: datetime | None = None
    last_price: float | None = None
    score: float = Field(ge=0, le=1)
    status: Literal["tradable", "watch", "blocked", "no_signal"]
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    premarket: dict[str, Any] = Field(default_factory=dict)
    signals: list[IntradaySignalAnalysis] = Field(default_factory=list)
    intent_ids: list[str] = Field(default_factory=list)


class IntradayThemeAnalysis(StrictBaseModel):
    theme_name: str
    symbol_count: int = 0
    avg_score: float = Field(ge=0, le=1)
    avg_theme_strength: float = 0
    confirmed: bool = False
    symbols: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class IntradayAnalysisReport(StrictBaseModel):
    report_id: str = Field(default_factory=lambda: make_id("intraday"))
    generated_at: datetime = Field(default_factory=utc_now)
    market_state: MarketState
    symbol_count: int = 0
    trade_intent_count: int = 0
    symbols: list[IntradaySymbolAnalysis] = Field(default_factory=list)
    themes: list[IntradayThemeAnalysis] = Field(default_factory=list)
    generated_intents: list[TradeIntent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


class CheckResult(StrictBaseModel):
    check_name: str
    status: Literal["pass", "warn", "scale_down", "needs_human_approval", "hard_reject"]
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class RiskDecision(StrictBaseModel):
    decision_id: str = Field(default_factory=lambda: make_id("risk"))
    intent_id: str
    created_at: datetime = Field(default_factory=utc_now)
    decision: Literal["approved", "rejected", "needs_human_approval"]
    approved_quantity: int = 0
    approved_price: float | None = None
    reason: str
    checks: dict[str, CheckResult]


class OrderInstruction(StrictBaseModel):
    order_instruction_id: str = Field(default_factory=lambda: make_id("ordinst"))
    decision_id: str
    intent_id: str
    created_at: datetime = Field(default_factory=utc_now)
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    order_type: Literal["limit", "marketable_limit"]
    limit_price: float | None
    ttl_seconds: int


class BrokerOrder(StrictBaseModel):
    order_id: str = Field(default_factory=lambda: make_id("order"))
    order_instruction_id: str
    decision_id: str
    intent_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    order_type: Literal["limit", "marketable_limit"]
    limit_price: float | None = None
    status: Literal[
        "created",
        "submitted",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
        "expired",
    ] = "created"
    created_at: datetime = Field(default_factory=utc_now)
    submitted_at: datetime | None = None
    expires_at: datetime | None = None
    filled_quantity: int = 0


class Fill(StrictBaseModel):
    fill_id: str = Field(default_factory=lambda: make_id("fill"))
    order_id: str
    order_instruction_id: str
    decision_id: str
    intent_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = 0
    slippage_bps: float = 0
    ts: datetime = Field(default_factory=utc_now)


class PositionSnapshot(StrictBaseModel):
    snapshot_id: str = Field(default_factory=lambda: make_id("pos"))
    ts: datetime = Field(default_factory=utc_now)
    positions: dict[str, int] = Field(default_factory=dict)
    avg_cost: dict[str, float] = Field(default_factory=dict)


class AccountSnapshot(StrictBaseModel):
    snapshot_id: str = Field(default_factory=lambda: make_id("acct"))
    ts: datetime = Field(default_factory=utc_now)
    cash: float
    nav: float
    gross_exposure: float = 0
    realized_pnl: float = 0
    unrealized_pnl: float = 0
    daily_loss: float = 0


class TradeReviewContext(StrictBaseModel):
    trade_id: str
    intent: TradeIntent
    risk_decision: RiskDecision | None = None
    order_instruction: OrderInstruction | None = None
    fills: list[Fill] = Field(default_factory=list)
    related_intel: list[IntelBrief] = Field(default_factory=list)
    market_before: list[MarketBar] = Field(default_factory=list)
    market_after: list[MarketBar] = Field(default_factory=list)
    position_before: dict[str, Any] = Field(default_factory=dict)
    position_after: dict[str, Any] = Field(default_factory=dict)
    strategy_config: dict[str, Any] = Field(default_factory=dict)


class PnLSummary(StrictBaseModel):
    gross_pnl: float = 0
    net_pnl: float = 0
    fees: float = 0
    slippage: float = 0
    realized_pnl: float = 0
    unrealized_pnl: float = 0
    pnl_by_strategy: dict[str, float] = Field(default_factory=dict)
    pnl_by_symbol: dict[str, float] = Field(default_factory=dict)


class ExecutionMetrics(StrictBaseModel):
    fill_rate: float = 0
    cancel_rate: float = 0
    reject_rate: float = 0
    avg_slippage_bps: float = 0
    max_slippage_bps: float = 0
    avg_intent_to_fill_seconds: float = 0
    avg_intel_to_intent_seconds: float = 0
    warnings: list[str] = Field(default_factory=list)


class SignalQualityResult(StrictBaseModel):
    intent_id: str
    symbol: str
    strategy_id: str
    mfe_bps: float = 0
    mae_bps: float = 0
    return_after_5m_bps: float = 0
    return_after_15m_bps: float = 0
    return_after_30m_bps: float = 0
    diagnosis: list[str] = Field(default_factory=list)


class IntelQualityResult(StrictBaseModel):
    event_id: str
    symbols: list[str]
    event_type: str
    importance: str
    original_bias: str
    confirmed_later: bool = False
    price_reaction_bps_30m: float | None = None
    related_trade_count: int = 0
    related_pnl: float = 0
    diagnosis: list[str] = Field(default_factory=list)


class RiskReviewResult(StrictBaseModel):
    rejected_count: int = 0
    needs_human_approval_count: int = 0
    scaled_down_count: int = 0
    kill_switch_triggered: bool = False
    risk_breaches: list[dict[str, Any]] = Field(default_factory=list)
    suspicious_patterns: list[str] = Field(default_factory=list)


class StrategyHealth(StrictBaseModel):
    strategy_id: str
    strategy_version: str
    status_recommendation: Literal[
        "keep",
        "reduce_size",
        "pause",
        "disable_until_retest",
        "promote_to_next_stage",
    ]
    reasons: list[str]
    metrics: dict[str, Any] = Field(default_factory=dict)
    requires_backtest: bool = True
    auto_apply: bool = False

    @field_validator("auto_apply")
    @classmethod
    def forbid_auto_apply(cls, value: bool) -> bool:
        if value:
            raise ValueError("strategy suggestions cannot auto apply")
        return value


class DailyReviewReport(StrictBaseModel):
    date: date
    generated_at: datetime = Field(default_factory=utc_now)
    pnl: PnLSummary
    execution: ExecutionMetrics
    risk_review: RiskReviewResult
    signal_quality: list[SignalQualityResult] = Field(default_factory=list)
    intel_quality: list[IntelQualityResult] = Field(default_factory=list)
    strategy_health: list[StrategyHealth] = Field(default_factory=list)
    best_trades: list[dict[str, Any]] = Field(default_factory=list)
    worst_trades: list[dict[str, Any]] = Field(default_factory=list)
    key_mistakes: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    markdown_report: str = ""


EVENT_MODEL_BY_TOPIC = {
    "intel.briefs": IntelBrief,
    "market.bars.1m": MarketBar,
    "intraday.analysis": IntradayAnalysisReport,
    "trading.intents": TradeIntent,
    "risk.decisions": RiskDecision,
    "risk.approval_queue": dict,
    "orders.instructions": OrderInstruction,
    "orders.submitted": BrokerOrder,
    "orders.filled": Fill,
    "orders.cancelled": BrokerOrder,
    "orders.rejected": BrokerOrder,
    "positions.snapshots": PositionSnapshot,
    "account.snapshots": AccountSnapshot,
    "premarket.reports": PremarketReport,
    "premarket.post_close_digest": dict,
    "premarket.morning_brief": dict,
    "premarket.opening_radar": dict,
    "premarket.instructions": dict,
    "review.daily": DailyReviewReport,
}
