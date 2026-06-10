from __future__ import annotations

from collections import defaultdict
from typing import Any

from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.schemas import (
    FeatureSnapshot,
    IntradayAnalysisReport,
    IntradaySignalAnalysis,
    IntradaySymbolAnalysis,
    IntradayThemeAnalysis,
    MarketState,
    SignalCandidate,
    TradeIntent,
)


FILTER_REASON_LABELS = {
    "confidence_below_minimum": "信心不足，未达到交易阈值",
    "market_data_not_ok": "行情质量异常，禁止新开仓",
    "market_halt_new_entries": "市场状态要求暂停新开仓",
    "premarket_blocks_new_entry": "盘前约束禁止新开仓",
    "unverified_or_rumor_risk": "消息带有未证实或传闻风险",
}


def build_intraday_analysis_report(
    *,
    watchlist: list[str],
    market_state: MarketState,
    snapshots: dict[str, FeatureSnapshot],
    latest_prices: dict[str, float],
    candidates_by_symbol: dict[str, list[SignalCandidate]],
    filtered_reasons: dict[str, str],
    planned_signal_ids: set[str],
    intents_by_symbol: dict[str, list[TradeIntent]],
    generated_intents: list[TradeIntent],
    premarket_context: PremarketContext | None = None,
    warnings: list[str] | None = None,
) -> IntradayAnalysisReport:
    symbols = [
        _build_symbol_analysis(
            symbol=symbol,
            market_state=market_state,
            snapshot=snapshots.get(symbol),
            last_price=latest_prices.get(symbol),
            candidates=candidates_by_symbol.get(symbol, []),
            filtered_reasons=filtered_reasons,
            planned_signal_ids=planned_signal_ids,
            intents=intents_by_symbol.get(symbol, []),
            premarket_context=premarket_context,
        )
        for symbol in watchlist
    ]
    themes = _build_theme_analysis(symbols)
    return IntradayAnalysisReport(
        market_state=market_state,
        symbol_count=len(symbols),
        trade_intent_count=len(generated_intents),
        symbols=symbols,
        themes=themes,
        generated_intents=generated_intents,
        warnings=warnings or [],
        summary=_summary(market_state, symbols, themes, generated_intents),
    )


def _build_symbol_analysis(
    *,
    symbol: str,
    market_state: MarketState,
    snapshot: FeatureSnapshot | None,
    last_price: float | None,
    candidates: list[SignalCandidate],
    filtered_reasons: dict[str, str],
    planned_signal_ids: set[str],
    intents: list[TradeIntent],
    premarket_context: PremarketContext | None,
) -> IntradaySymbolAnalysis:
    features = snapshot.features if snapshot else {}
    premarket = _premarket_metadata(symbol, snapshot, premarket_context)
    signals = [
        IntradaySignalAnalysis(
            signal_id=candidate.signal_id,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            side=candidate.side,
            confidence=candidate.confidence,
            status="planned" if candidate.signal_id in planned_signal_ids else "filtered",
            reasons=list(candidate.reasons),
            filter_reason=filtered_reasons.get(candidate.signal_id),
            evidence_ids=candidate.evidence_ids,
        )
        for candidate in candidates
    ]
    score = _score(features, market_state, premarket)
    reasons = _symbol_reasons(
        snapshot=snapshot,
        candidates=candidates,
        filtered_reasons=filtered_reasons,
        signals=signals,
        intents=intents,
        premarket=premarket,
    )
    return IntradaySymbolAnalysis(
        symbol=symbol,
        ts=snapshot.ts if snapshot else None,
        last_price=last_price,
        score=score,
        status=_status(score, signals, intents, premarket),
        reasons=reasons,
        risk_flags=_risk_flags(intents),
        features=dict(features),
        premarket=premarket,
        signals=signals,
        intent_ids=[intent.intent_id for intent in intents],
    )


def _premarket_metadata(
    symbol: str,
    snapshot: FeatureSnapshot | None,
    premarket_context: PremarketContext | None,
) -> dict[str, Any]:
    if premarket_context is None:
        return {}
    theme = snapshot.features.get("primary_theme") if snapshot else ""
    themes = [str(theme)] if theme else []
    return premarket_context.metadata_for(symbol, themes)


def _score(features: dict[str, Any], market_state: MarketState, premarket: dict[str, Any]) -> float:
    return_5m = max(0.0, _float(features.get("return_5m")))
    volume_ratio = max(0.0, _float(features.get("volume_ratio_5m")))
    theme_strength = max(0.0, _float(features.get("theme_strength")))
    bullish = max(0.0, _float(features.get("recent_bullish_intel_score")))
    bearish = max(0.0, _float(features.get("recent_bearish_intel_score")))
    score = 0.0
    score += min(return_5m / 0.05, 1.0) * 0.28
    score += min(volume_ratio / 5.0, 1.0) * 0.22
    score += 0.16 if bool(features.get("intraday_high_break")) else 0.0
    score += min(bullish / 1.5, 1.0) * 0.12
    score += min(theme_strength / 0.04, 1.0) * 0.12
    score += 0.08 if bool(features.get("theme_confirmation")) else 0.0
    score -= min(bearish / 1.0, 1.0) * 0.2
    if market_state.risk_mode != "normal":
        score -= 0.2
    if premarket.get("blocks_new_entry"):
        score -= 0.45
    return round(max(0.0, min(1.0, score)), 3)


def _symbol_reasons(
    *,
    snapshot: FeatureSnapshot | None,
    candidates: list[SignalCandidate],
    filtered_reasons: dict[str, str],
    signals: list[IntradaySignalAnalysis],
    intents: list[TradeIntent],
    premarket: dict[str, Any],
) -> list[str]:
    reasons: list[object] = []
    if snapshot is None:
        reasons.append("暂无行情数据")
    else:
        features = snapshot.features
        if _float(features.get("return_5m")) > 0.02:
            reasons.append("5分钟涨幅超过2%")
        if _float(features.get("volume_ratio_5m")) > 3:
            reasons.append("成交量明显放大")
        if bool(features.get("intraday_high_break")):
            reasons.append("突破日内高点")
        if features.get("primary_theme"):
            reasons.append(f"所属板块: {features['primary_theme']}")
        if bool(features.get("theme_confirmation")):
            reasons.append("盘前板块已确认")
    for candidate in candidates:
        reasons.extend(candidate.reasons)
        reason = filtered_reasons.get(candidate.signal_id)
        if reason:
            reasons.append(FILTER_REASON_LABELS.get(reason, reason))
    for intent in intents:
        reasons.extend(intent.entry_reason)
    for reason in premarket.get("reasons", []):
        reasons.append(f"盘前: {reason}")
    if not signals and not intents and snapshot is not None:
        reasons.append("暂无满足策略阈值的盘中信号")
    return _unique(reasons)


def _status(
    score: float,
    signals: list[IntradaySignalAnalysis],
    intents: list[TradeIntent],
    premarket: dict[str, Any],
) -> str:
    if intents:
        return "tradable"
    if premarket.get("blocks_new_entry"):
        return "blocked"
    if signals and all(signal.status == "filtered" for signal in signals):
        return "blocked"
    if signals or score >= 0.45:
        return "watch"
    return "no_signal"


def _risk_flags(intents: list[TradeIntent]) -> list[str]:
    flags: list[object] = []
    for intent in intents:
        flags.extend(intent.metadata.get("risk_flags", []))
    return _unique(flags)


def _build_theme_analysis(symbols: list[IntradaySymbolAnalysis]) -> list[IntradayThemeAnalysis]:
    grouped: dict[str, list[IntradaySymbolAnalysis]] = defaultdict(list)
    for symbol in symbols:
        theme = symbol.features.get("primary_theme")
        if theme:
            grouped[str(theme)].append(symbol)
    themes = []
    for theme_name, members in grouped.items():
        avg_score = sum(member.score for member in members) / len(members)
        avg_strength = sum(_float(member.features.get("theme_strength")) for member in members) / len(members)
        confirmed = any(bool(member.features.get("theme_confirmation")) for member in members)
        reasons = [f"{len(members)}只观察标的归属该板块"]
        if confirmed:
            reasons.append("盘前/开盘雷达确认")
        if avg_strength > 0:
            reasons.append(f"板块强度 {avg_strength:.2%}")
        themes.append(
            IntradayThemeAnalysis(
                theme_name=theme_name,
                symbol_count=len(members),
                avg_score=round(avg_score, 3),
                avg_theme_strength=round(avg_strength, 6),
                confirmed=confirmed,
                symbols=[member.symbol for member in members],
                reasons=reasons,
            )
        )
    return sorted(themes, key=lambda item: (item.confirmed, item.avg_score, item.avg_theme_strength), reverse=True)


def _summary(
    market_state: MarketState,
    symbols: list[IntradaySymbolAnalysis],
    themes: list[IntradayThemeAnalysis],
    intents: list[TradeIntent],
) -> str:
    tradable = [item.symbol for item in symbols if item.status == "tradable"]
    blocked_count = sum(1 for item in symbols if item.status == "blocked")
    top_theme = themes[0].theme_name if themes else "无明显板块"
    return (
        f"市场状态 {market_state.risk_mode}/{market_state.data_quality}，"
        f"重点板块 {top_theme}，"
        f"生成 {len(intents)} 条交易意图，"
        f"可交易 {len(tradable)} 只，受限 {blocked_count} 只。"
    )


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
