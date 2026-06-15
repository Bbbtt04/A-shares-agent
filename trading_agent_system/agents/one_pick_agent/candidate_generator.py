from __future__ import annotations

from typing import Any

from .schemas import OnePickCandidate


IMPORTANCE_SCORE = {"S": 1.0, "A": 0.8, "B": 0.6, "C": 0.4}
SOURCE_QUALITY = {
    "official": 1.0,
    "authorized_news": 0.85,
    "professional": 0.80,
    "market_data": 0.75,
    "internal": 0.70,
    "overseas": 0.65,
    "unknown": 0.50,
    "social": 0.35,
}
SOURCE_RANK = {
    "official": 1,
    "authorized_news": 2,
    "professional": 3,
    "market_data": 4,
    "internal": 5,
    "overseas": 6,
    "unknown": 7,
    "social": 8,
}
BIAS_MULTIPLIER = {"bullish": 1.0, "mixed": 0.55, "neutral": 0.35, "unclear": 0.25, "bearish": -0.8}


class CandidateGenerator:
    def generate(
        self,
        *,
        events: list[Any],
        event_clusters: list[Any] | None = None,
        evidence_packs: list[Any] | None = None,
        market_snapshots: dict[str, Any] | None = None,
    ) -> list[OnePickCandidate]:
        symbol_state: dict[str, dict[str, Any]] = {}
        for item in [*events, *(event_clusters or [])]:
            self._accumulate_event(symbol_state, item)
        for pack in evidence_packs or []:
            self._accumulate_evidence_pack(symbol_state, pack)
        for symbol, snapshot in (market_snapshots or {}).items():
            state = symbol_state.setdefault(symbol, _empty_state(symbol))
            if _get(snapshot, "last_price") or _get(snapshot, "price"):
                state["market_confirmation"] = max(state["market_confirmation"], 0.6)

        candidates = [self._candidate(symbol, state) for symbol, state in symbol_state.items()]
        candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.source_rank, candidate.symbol))
        return candidates

    def _accumulate_event(self, symbol_state: dict[str, dict[str, Any]], event: Any) -> None:
        symbols = list(_get(event, "symbols", []) or [])
        if not symbols:
            return
        confidence = float(_get(event, "confidence", 0.5) or 0.5)
        importance = str(_get(event, "importance", "C") or "C")
        if "." in importance:
            importance = importance.rsplit(".", 1)[-1]
        importance = importance.upper()
        bias = str(_get(event, "bias", "unclear") or "unclear")
        if "." in bias:
            bias = bias.rsplit(".", 1)[-1]
        source_rank_name = str(_get(event, "source_rank", "unknown") or "unknown")
        if "." in source_rank_name:
            source_rank_name = source_rank_name.rsplit(".", 1)[-1]
        source_rank_name = source_rank_name.lower()
        catalyst = max(0.0, IMPORTANCE_SCORE.get(importance, 0.4) * confidence * BIAS_MULTIPLIER.get(bias, 0.25))
        source_quality = SOURCE_QUALITY.get(source_rank_name, 0.5)
        evidence_id = str(_get(event, "event_id", _get(event, "cluster_id", "")) or "")
        risk_flags = [str(flag) for flag in (_get(event, "risk_flags", []) or [])]
        themes = [str(theme) for theme in (_get(event, "related_themes", []) or [])]
        title = str(_get(event, "title", "") or "")

        for symbol in symbols:
            state = symbol_state.setdefault(str(symbol), _empty_state(str(symbol)))
            state["name"] = _get(event, "name", state.get("name"))
            state["catalyst_strength"] = max(state["catalyst_strength"], catalyst)
            state["source_quality_total"] += source_quality
            state["source_quality_count"] += 1
            state["source_quality"] = state["source_quality_total"] / state["source_quality_count"]
            state["source_rank"] = min(state["source_rank"], SOURCE_RANK.get(source_rank_name, 99))
            state["risk_flags"].update(risk_flags)
            state["strategy_tags"].update(themes)
            if evidence_id:
                state["evidence_ids"].append(evidence_id)
            if title:
                state["reasons"].append(title)

    def _accumulate_evidence_pack(self, symbol_state: dict[str, dict[str, Any]], pack: Any) -> None:
        evidence_id = str(_get(pack, "evidence_id", _get(pack, "pack_id", "")) or "")
        score = float(_get(pack, "score", _get(pack, "support_score", 0.5)) or 0.5)
        for symbol in list(_get(pack, "symbols", []) or []):
            state = symbol_state.setdefault(str(symbol), _empty_state(str(symbol)))
            state["evidence_support"] = max(state["evidence_support"], min(1.0, score))
            if evidence_id:
                state["evidence_ids"].append(evidence_id)

    def _candidate(self, symbol: str, state: dict[str, Any]) -> OnePickCandidate:
        risk_penalty = min(0.35, 0.08 * len(state["risk_flags"]))
        catalyst = float(state["catalyst_strength"])
        source = float(state["source_quality"])
        evidence = float(state["evidence_support"])
        market = float(state["market_confirmation"])
        confidence = _clamp(0.30 + 0.35 * catalyst + 0.20 * source + 0.10 * evidence + 0.05 * market - risk_penalty)
        expected_upside = max(0.01, 0.02 + 0.04 * catalyst + 0.01 * evidence)
        expected_downside = max(0.005, 0.015 + 0.01 * len(state["risk_flags"]))
        return OnePickCandidate(
            symbol=symbol,
            name=state.get("name"),
            feature_scores={
                "catalyst_strength": round(catalyst, 6),
                "source_quality": round(source, 6),
                "evidence_support": round(evidence, 6),
                "market_confirmation": round(market, 6),
            },
            evidence_ids=_unique(state["evidence_ids"]),
            risk_flags=sorted(state["risk_flags"]),
            strategy_tags=sorted(state["strategy_tags"]),
            source_rank=int(state["source_rank"]),
            confidence=round(confidence, 6),
            expected_upside_pct=round(expected_upside, 6),
            expected_downside_pct=round(expected_downside, 6),
            risk_reward_ratio=round(expected_upside / expected_downside, 6),
        )


def _empty_state(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": None,
        "catalyst_strength": 0.0,
        "source_quality": 0.0,
        "source_quality_total": 0.0,
        "source_quality_count": 0,
        "evidence_support": 0.0,
        "market_confirmation": 0.0,
        "source_rank": 99,
        "evidence_ids": [],
        "risk_flags": set(),
        "strategy_tags": set(),
        "reasons": [],
    }


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
