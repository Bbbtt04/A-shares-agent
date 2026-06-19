from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import Field

from .schemas import Actionability, Importance, PreMarketEvent, SourceRank, StrictModel


Recommendation = Literal["candidate", "watch", "reject"]


DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "source_quality": 0.15,
    "catalyst_strength": 0.15,
    "company_fit": 0.15,
    "evidence_consistency": 0.15,
    "event_novelty": 0.10,
    "theme_heat": 0.10,
    "market_confirmation": 0.10,
    "crowding_risk": -0.05,
    "stale_news_risk": -0.05,
    "hype_risk": -0.05,
}

SOURCE_QUALITY = {
    SourceRank.OFFICIAL.value: 0.95,
    SourceRank.AUTHORIZED_NEWS.value: 0.75,
    SourceRank.MARKET_DATA.value: 0.65,
    SourceRank.OVERSEAS.value: 0.60,
    SourceRank.INTERNAL.value: 0.80,
    SourceRank.SOCIAL.value: 0.25,
}

IMPORTANCE_SCORE = {
    Importance.S.value: 1.0,
    Importance.A.value: 0.8,
    Importance.B.value: 0.55,
    Importance.C.value: 0.25,
}

MARKET_CONFIRMATION = {
    Actionability.CANDIDATE.value: 0.175,
    Actionability.WATCH.value: 0.15,
    Actionability.WATCH_ONLY.value: 0.10,
    Actionability.BLOCK.value: 0.0,
}


class PremarketFactorScore(StrictModel):
    symbol: str
    theme: str
    signal_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    recommendation: Recommendation
    factor_scores: dict[str, float] = Field(default_factory=dict)
    factor_contributions: dict[str, float] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class PremarketFactorScoreSet(StrictModel):
    score_id: str
    trading_day: date
    generated_at: datetime
    scores: list[PremarketFactorScore] = Field(default_factory=list)


class PremarketFactorScorer:
    def __init__(
        self,
        factor_weights: dict[str, float] | None = None,
        generated_at: datetime | None = None,
    ) -> None:
        self.default_factor_weights = {**DEFAULT_FACTOR_WEIGHTS, **(factor_weights or {})}
        self.generated_at = generated_at

    def score(
        self,
        events: list[PreMarketEvent],
        semantic_reviews: Any | None = None,
        learning_state: dict[str, Any] | None = None,
        trading_day: date | None = None,
    ) -> PremarketFactorScoreSet:
        generated_at = self.generated_at or datetime.now(timezone.utc)
        day = trading_day or generated_at.date()
        weights = self._weights(learning_state)
        by_symbol = self._events_by_symbol(events)
        theme_counts = Counter(self._theme(event) for event in events if self._theme(event))

        scores = [
            self._score_symbol(symbol, symbol_events, theme_counts, weights, semantic_reviews, learning_state)
            for symbol, symbol_events in by_symbol.items()
        ]
        return PremarketFactorScoreSet(
            score_id=f"premarket-factor-scores-{day.isoformat()}",
            trading_day=day,
            generated_at=generated_at,
            scores=sorted(scores, key=lambda item: item.signal_score, reverse=True),
        )

    def _events_by_symbol(self, events: list[PreMarketEvent]) -> dict[str, list[PreMarketEvent]]:
        by_symbol: dict[str, list[PreMarketEvent]] = defaultdict(list)
        for event in events:
            for symbol in event.symbols:
                by_symbol[symbol].append(event)
        return dict(by_symbol)

    def _score_symbol(
        self,
        symbol: str,
        events: list[PreMarketEvent],
        theme_counts: Counter[str],
        weights: dict[str, float],
        semantic_reviews: Any | None,
        learning_state: dict[str, Any] | None,
    ) -> PremarketFactorScore:
        primary = max(events, key=lambda event: (IMPORTANCE_SCORE.get(str(event.importance), 0.0), event.confidence))
        semantic_review = self._semantic_review(symbol, semantic_reviews)
        theme = self._read(semantic_review, "theme") or self._theme(primary)
        factors = {
            "source_quality": self._source_quality(primary, learning_state),
            "catalyst_strength": self._catalyst_strength(events),
            "company_fit": self._company_fit(events),
            "evidence_consistency": self._evidence_consistency(events),
            "event_novelty": self._event_novelty(events),
            "theme_heat": self._theme_heat(theme, theme_counts, learning_state),
            "market_confirmation": self._market_confirmation(events),
            "crowding_risk": self._risk_factor(events, "crowding"),
            "stale_news_risk": self._risk_factor(events, "stale"),
            "hype_risk": self._risk_factor(events, "hype"),
        }
        self._apply_semantic_factors(factors, semantic_review)
        contributions = {name: round(factors[name] * weights[name], 6) for name in DEFAULT_FACTOR_WEIGHTS}
        signal_score = self._clamp(sum(contributions.values()))
        recommendation = self._recommendation(signal_score)
        reasons = self._reasons(factors, contributions)
        if semantic_review is not None:
            reasons.append("semantic review adjusted premarket factor values")

        semantic_reject_reasons = self._semantic_reject_reasons(semantic_review)
        if semantic_reject_reasons:
            recommendation = "reject"
            reasons.extend(f"semantic reject: {reason}" for reason in semantic_reject_reasons)

        return PremarketFactorScore(
            symbol=symbol,
            theme=theme,
            signal_score=round(signal_score, 6),
            confidence=round(sum(event.confidence for event in events) / len(events), 6),
            recommendation=recommendation,
            factor_scores=factors,
            factor_contributions=contributions,
            risk_flags=self._unique(flag for event in events for flag in event.risk_flags),
            evidence_ids=self._unique([*self._evidence_ids(events), *self._semantic_evidence_ids(semantic_review)]),
            reasons=reasons,
        )

    def _weights(self, learning_state: dict[str, Any] | None) -> dict[str, float]:
        weights = dict(self.default_factor_weights)
        for name, adjustment in (learning_state or {}).get("factor_weights", {}).items():
            if name in weights:
                weights[name] = max(-1.0, min(1.0, weights[name] + float(adjustment)))
        for name, adjustment in (learning_state or {}).get("risk_penalties", {}).items():
            if name in weights:
                weights[name] = max(-1.0, min(1.0, weights[name] + float(adjustment)))
        return weights

    def _source_quality(self, event: PreMarketEvent, learning_state: dict[str, Any] | None) -> float:
        value = SOURCE_QUALITY.get(str(event.source_rank), 0.5)
        value += float((learning_state or {}).get("source_adjustments", {}).get(str(event.source_rank), 0.0))
        return value

    def _catalyst_strength(self, events: list[PreMarketEvent]) -> float:
        return max(IMPORTANCE_SCORE.get(str(event.importance), 0.3) for event in events)

    def _company_fit(self, events: list[PreMarketEvent]) -> float:
        if any(event.is_holding_related or event.is_watchlist_related for event in events):
            return 1.0
        return 0.7

    def _evidence_consistency(self, events: list[PreMarketEvent]) -> float:
        return sum(event.confidence for event in events) / len(events)

    def _event_novelty(self, events: list[PreMarketEvent]) -> float:
        if any("stale" in flag.lower() for event in events for flag in event.risk_flags):
            return 0.2
        return 0.5

    def _theme_heat(
        self,
        theme: str,
        theme_counts: Counter[str],
        learning_state: dict[str, Any] | None,
    ) -> float:
        base = min(1.0, 0.75 + 0.25 * theme_counts.get(theme, 0))
        return base + float((learning_state or {}).get("theme_adjustments", {}).get(theme, 0.0))

    def _market_confirmation(self, events: list[PreMarketEvent]) -> float:
        return max(MARKET_CONFIRMATION.get(str(event.actionability), 0.0) for event in events)

    def _risk_factor(self, events: list[PreMarketEvent], risk_name: str) -> float:
        return 1.0 if any(risk_name in flag.lower() for event in events for flag in event.risk_flags) else 0.0

    def _semantic_review(self, symbol: str, semantic_reviews: Any | None) -> Any | None:
        if isinstance(semantic_reviews, dict):
            return semantic_reviews.get(symbol)
        if isinstance(semantic_reviews, list):
            return next(
                (
                    item
                    for item in semantic_reviews
                    if self._read(item, "symbol") == symbol
                    or symbol in (self._read(item, "symbols") or [])
                ),
                None,
            )
        if hasattr(semantic_reviews, "reviews"):
            return self._semantic_review(symbol, getattr(semantic_reviews, "reviews"))
        return None

    def _apply_semantic_factors(self, factors: dict[str, float], review: Any | None) -> None:
        if review is None:
            return
        mapping = {
            "source_quality": "source_reliability",
            "catalyst_strength": "catalyst_relevance",
            "company_fit": "company_fit",
            "evidence_consistency": "evidence_consistency",
            "event_novelty": "event_novelty",
            "crowding_risk": "crowding_risk",
            "stale_news_risk": "stale_news_risk",
            "hype_risk": "hype_risk",
        }
        for factor_name, review_name in mapping.items():
            value = self._read(review, review_name)
            if isinstance(value, int | float):
                factors[factor_name] = max(0.0, min(1.0, float(value)))

    def _semantic_reject_reasons(self, review: Any | None) -> list[str]:
        if not review or self._read(review, "semantic_verdict") != "reject":
            return []
        reasons = (
            self._read(review, "negative_reasons")
            or self._read(review, "reasons")
            or self._read(review, "reason")
            or []
        )
        if isinstance(reasons, str):
            return [reasons]
        return list(reasons)

    def _semantic_evidence_ids(self, review: Any | None) -> list[str]:
        if review is None:
            return []
        values = self._read(review, "evidence_ids") or []
        return [str(value) for value in values]

    def _recommendation(self, signal_score: float) -> Recommendation:
        if signal_score >= 0.65:
            return "candidate"
        if signal_score >= 0.45:
            return "watch"
        return "reject"

    def _reasons(self, factors: dict[str, float], contributions: dict[str, float]) -> list[str]:
        ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
        return [f"{name} contribution {value:.3f} from factor {factors[name]:.2f}" for name, value in ranked[:3]]

    def _theme(self, event: PreMarketEvent) -> str:
        return event.related_themes[0] if event.related_themes else event.event_type

    def _evidence_ids(self, events: list[PreMarketEvent]) -> list[str]:
        ids: list[str] = []
        for event in events:
            ids.append(event.event_id)
            for evidence in event.evidence:
                evidence_id = evidence.get("id") or evidence.get("evidence_id") or evidence.get("source_id")
                if evidence_id:
                    ids.append(str(evidence_id))
        return self._unique(ids)

    def _read(self, item: Any, name: str) -> Any:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    def _unique(self, values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))
