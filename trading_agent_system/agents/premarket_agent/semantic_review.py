from __future__ import annotations

import json
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from trading_agent_system.agents.premarket_agent.schemas import Actionability, Bias, StrictModel
from trading_agent_system.schemas import make_id, utc_now


SCORE_FIELDS: tuple[str, ...] = (
    "catalyst_relevance",
    "company_fit",
    "event_novelty",
    "evidence_consistency",
    "source_reliability",
    "crowding_risk",
    "stale_news_risk",
    "hype_risk",
)


class PremarketSemanticReview(StrictModel):
    symbol: str
    theme: str | None = None
    catalyst_relevance: float = Field(ge=0, le=1)
    company_fit: float = Field(ge=0, le=1)
    event_novelty: float = Field(ge=0, le=1)
    evidence_consistency: float = Field(ge=0, le=1)
    source_reliability: float = Field(ge=0, le=1)
    crowding_risk: float = Field(ge=0, le=1)
    stale_news_risk: float = Field(ge=0, le=1)
    hype_risk: float = Field(ge=0, le=1)
    semantic_verdict: Literal["candidate", "watch", "watch_only", "reject"]
    positive_reasons: list[str] = Field(default_factory=list)
    negative_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator(*SCORE_FIELDS, mode="before")
    @classmethod
    def clamp_score(cls, value: object) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        return max(0.0, min(1.0, score))


class PremarketSemanticReviewSet(StrictModel):
    review_id: str = Field(default_factory=lambda: make_id("premarket_semantic_review"))
    trading_day: date
    generated_at: datetime = Field(default_factory=utc_now)
    reviews: list[PremarketSemanticReview] = Field(default_factory=list)


class PremarketSemanticReviewAgent:
    def __init__(self, llm_gateway: object | None = None) -> None:
        self.llm_gateway = llm_gateway

    def review(
        self,
        events: list[object],
        evidence_packs: list[object] | None = None,
        trading_day: date | None = None,
        top_n: int = 5,
    ) -> PremarketSemanticReviewSet:
        selected = self._select_events(events, top_n)
        fallback_by_symbol = {self._symbol(event): self._deterministic_review(event) for event in selected}
        llm_reviews = self._llm_reviews(selected, evidence_packs or []) if self.llm_gateway is not None else {}
        reviews = [
            llm_reviews.get(symbol) or fallback
            for symbol, fallback in fallback_by_symbol.items()
        ]
        return PremarketSemanticReviewSet(
            trading_day=trading_day or date.today(),
            reviews=reviews,
        )

    def _select_events(self, events: list[object], top_n: int) -> list[object]:
        selected: list[object] = []
        seen: set[str] = set()
        for event in events:
            symbol = self._symbol(event)
            if not symbol or symbol in seen:
                continue
            selected.append(event)
            seen.add(symbol)
            if len(selected) >= top_n:
                break
        return selected

    def _llm_reviews(self, events: list[object], evidence_packs: list[object]) -> dict[str, PremarketSemanticReview]:
        response = self.llm_gateway.complete(
            messages=self._messages(events, evidence_packs),
            response_schema={"required": ["reviews"]},
            metadata={"agent": "premarket_semantic_review"},
        )
        payload = self._parse_json(getattr(response, "content", response))
        items = payload.get("reviews", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return {}
        reviews: dict[str, PremarketSemanticReview] = {}
        known_symbols = {self._symbol(event) for event in events}
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            if symbol not in known_symbols or not self._has_required_llm_fields(item):
                continue
            try:
                reviews[symbol] = PremarketSemanticReview.model_validate(item)
            except ValueError:
                continue
        return reviews

    def _messages(self, events: list[object], evidence_packs: list[object]) -> list[dict[str, str]]:
        payload = {
            "events": [self._event_payload(event) for event in events],
            "evidence_packs": [self._jsonable(pack) for pack in evidence_packs],
            "required_schema": {
                "reviews": [
                    {
                        "symbol": "string",
                        "theme": "string",
                        "score_fields": list(SCORE_FIELDS),
                        "semantic_verdict": "candidate|watch|watch_only|reject",
                        "positive_reasons": ["string"],
                        "negative_reasons": ["string"],
                        "evidence_ids": ["string"],
                    }
                ]
            },
        }
        return [
            {
                "role": "system",
                "content": "Return only valid JSON for premarket semantic review. Clamp scores conceptually to 0..1.",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]

    def _deterministic_review(self, event: object) -> PremarketSemanticReview:
        confidence = self._confidence(event)
        bias = self._enum_value(self._field(event, "bias", Bias.UNCLEAR))
        actionability = self._enum_value(self._field(event, "actionability", Actionability.WATCH))
        risk_flags = self._list_field(event, "risk_flags")
        bearish_or_blocked = bias == Bias.BEARISH.value or actionability == Actionability.BLOCK.value
        verdict: Literal["candidate", "watch", "watch_only", "reject"]
        if bearish_or_blocked and (actionability == Actionability.BLOCK.value or confidence >= 0.7):
            verdict = "reject"
        elif bearish_or_blocked:
            verdict = "watch_only"
        elif actionability == Actionability.CANDIDATE.value and confidence >= 0.75:
            verdict = "candidate"
        else:
            verdict = "watch"

        positive_reasons = []
        negative_reasons = []
        if verdict in {"candidate", "watch"}:
            positive_reasons.append(f"{bias or 'unclear'} event with confidence {confidence:.2f}")
        if bearish_or_blocked:
            negative_reasons.append(f"{bias or 'unclear'} event marked {actionability or 'watch'}")
        if risk_flags:
            negative_reasons.append("risk flags: " + ", ".join(str(flag) for flag in risk_flags))

        return PremarketSemanticReview(
            symbol=self._symbol(event),
            theme=self._theme(event),
            catalyst_relevance=confidence if not bearish_or_blocked else max(0.2, confidence * 0.5),
            company_fit=0.75 if self._symbol(event) in self._list_field(event, "symbols") else 0.5,
            event_novelty=0.7 if confidence >= 0.7 else 0.5,
            evidence_consistency=max(0.3, confidence),
            source_reliability=self._source_reliability(event),
            crowding_risk=0.5 if risk_flags else 0.25,
            stale_news_risk=0.2,
            hype_risk=0.65 if bearish_or_blocked or risk_flags else 0.3,
            semantic_verdict=verdict,
            positive_reasons=positive_reasons,
            negative_reasons=negative_reasons,
            evidence_ids=self._evidence_ids(event),
        )

    def _source_reliability(self, event: object) -> float:
        rank = self._enum_value(self._field(event, "source_rank", ""))
        if rank in {"official", "authorized_news", "market_data"}:
            return 0.9
        if rank in {"overseas", "internal"}:
            return 0.75
        if rank == "social":
            return 0.45
        return 0.6

    def _evidence_ids(self, event: object) -> list[str]:
        ids = [str(self._field(event, "event_id", ""))]
        for item in self._list_field(event, "evidence"):
            if isinstance(item, dict):
                evidence_id = item.get("id") or item.get("evidence_id") or item.get("source_id")
                if evidence_id:
                    ids.append(str(evidence_id))
        return [item for index, item in enumerate(ids) if item and item not in ids[:index]]

    def _event_payload(self, event: object) -> dict[str, object]:
        return {
            "event_id": self._field(event, "event_id", ""),
            "symbol": self._symbol(event),
            "title": self._field(event, "title", ""),
            "summary": self._field(event, "summary", ""),
            "theme": self._theme(event),
            "bias": self._enum_value(self._field(event, "bias", "")),
            "confidence": self._confidence(event),
            "actionability": self._enum_value(self._field(event, "actionability", "")),
            "risk_flags": self._list_field(event, "risk_flags"),
            "evidence_ids": self._evidence_ids(event),
        }

    def _has_required_llm_fields(self, item: dict[str, object]) -> bool:
        required = {
            "symbol",
            "theme",
            "semantic_verdict",
            "positive_reasons",
            "negative_reasons",
            "evidence_ids",
            *SCORE_FIELDS,
        }
        return required.issubset(item)

    def _parse_json(self, content: object) -> object:
        if isinstance(content, (dict, list)):
            return content
        try:
            return json.loads(str(content))
        except json.JSONDecodeError:
            return {}

    def _symbol(self, event: object) -> str:
        symbols = self._list_field(event, "symbols")
        if symbols:
            return str(symbols[0])
        return str(self._field(event, "symbol", ""))

    def _theme(self, event: object) -> str | None:
        themes = self._list_field(event, "related_themes")
        if themes:
            return str(themes[0])
        value = self._field(event, "theme", None)
        return str(value) if value else None

    def _confidence(self, event: object) -> float:
        try:
            return max(0.0, min(1.0, float(self._field(event, "confidence", 0.5))))
        except (TypeError, ValueError):
            return 0.5

    def _list_field(self, source: object, name: str) -> list[object]:
        value = self._field(source, name, [])
        return value if isinstance(value, list) else []

    def _field(self, source: object, name: str, default: object) -> object:
        if isinstance(source, dict):
            return source.get(name, default)
        return getattr(source, name, default)

    def _enum_value(self, value: object) -> str:
        return str(getattr(value, "value", value))

    def _jsonable(self, value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value
