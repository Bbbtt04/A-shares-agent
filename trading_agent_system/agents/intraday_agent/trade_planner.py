from __future__ import annotations

from trading_agent_system.core.premarket import PremarketContext
from trading_agent_system.schemas import FeatureSnapshot, IntelBrief, MarketState, SignalCandidate, TradeIntent


class TradePlanner:
    def __init__(self, min_confidence: float = 0.55, default_quantity: int = 100) -> None:
        self.min_confidence = min_confidence
        self.default_quantity = default_quantity

    def plan(
        self,
        candidate: SignalCandidate,
        snapshot: FeatureSnapshot,
        market_state: MarketState,
        intel: list[IntelBrief],
        premarket_context: PremarketContext | None = None,
    ) -> TradeIntent | None:
        if candidate.confidence < self.min_confidence:
            return None
        if market_state.data_quality != "ok" and candidate.side == "buy":
            return None
        if market_state.risk_mode == "halt_new_entries" and candidate.side == "buy":
            return None
        premarket_metadata = {}
        if premarket_context is not None:
            premarket_metadata = premarket_context.metadata_for(candidate.symbol)
            if candidate.side == "buy" and premarket_metadata["blocks_new_entry"]:
                return None
        related = [brief for brief in intel if brief.event_id in candidate.evidence_ids]
        risk_flags = sorted({flag for brief in related for flag in brief.risk_flags})
        if candidate.side == "buy" and any(flag in {"unverified", "rumor"} for flag in risk_flags):
            return None
        quantity = candidate.suggested_quantity or self.default_quantity
        evidence_ids = _unique([*candidate.evidence_ids, *premarket_metadata.get("evidence_ids", [])])
        entry_reason = list(candidate.reasons)
        for reason in premarket_metadata.get("reasons", []):
            entry_reason.append(f"盘前约束: {reason}")
        return TradeIntent(
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=quantity,
            order_type="limit",
            limit_price=candidate.suggested_limit_price,
            confidence=candidate.confidence,
            entry_reason=entry_reason,
            evidence_ids=evidence_ids,
            feature_snapshot_id=snapshot.snapshot_id,
            invalidation=candidate.invalidation,
            metadata={
                "risk_flags": risk_flags,
                "spread_bps": snapshot.features.get("spread_bps", 0),
                "premarket": premarket_metadata,
            },
        )


def _unique(values: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
