from __future__ import annotations

import json
from datetime import date, datetime, timezone

from trading_agent_system.agents.premarket_agent.schemas import Actionability, Bias, Importance, PreMarketEvent, SourceRank
from trading_agent_system.agents.premarket_agent.semantic_review import PremarketSemanticReviewAgent
from trading_agent_system.core.llm_gateway import LLMGateway, MockModelClient


def _event(
    event_id: str,
    symbol: str,
    *,
    bias: Bias = Bias.BULLISH,
    actionability: Actionability = Actionability.CANDIDATE,
    confidence: float = 0.9,
    risk_flags: list[str] | None = None,
) -> PreMarketEvent:
    seen_at = datetime(2026, 6, 19, 8, 20, tzinfo=timezone.utc)
    return PreMarketEvent(
        event_id=event_id,
        source_ids=[f"src-{event_id}"],
        source_rank=SourceRank.OFFICIAL,
        title=f"{symbol} catalyst",
        summary=f"{symbol} receives material catalyst",
        first_seen_at=seen_at,
        last_updated_at=seen_at,
        symbols=[symbol],
        companies=[symbol],
        event_type="policy",
        related_themes=["AI"],
        importance=Importance.A,
        bias=bias,
        confidence=confidence,
        actionability=actionability,
        evidence=[{"id": f"ev-{event_id}", "source": "official"}],
        risk_flags=risk_flags or [],
    )


def test_deterministic_review_prefers_high_confidence_bullish_candidates_and_rejects_block_risk() -> None:
    agent = PremarketSemanticReviewAgent()

    result = agent.review(
        [
            _event("e1", "688001.SH"),
            _event("e2", "300001.SZ", bias=Bias.BEARISH, actionability=Actionability.BLOCK, risk_flags=["regulatory"]),
        ],
        trading_day=date(2026, 6, 19),
    )

    assert result.trading_day == date(2026, 6, 19)
    assert len(result.reviews) == 2
    bullish = result.reviews[0]
    bearish = result.reviews[1]
    assert bullish.symbol == "688001.SH"
    assert bullish.theme == "AI"
    assert bullish.semantic_verdict in {"candidate", "watch"}
    assert bullish.catalyst_relevance > 0.7
    assert bullish.positive_reasons
    assert bullish.evidence_ids == ["e1", "ev-e1"]
    assert bearish.symbol == "300001.SZ"
    assert bearish.semantic_verdict in {"reject", "watch_only"}
    assert bearish.hype_risk >= 0.5
    assert bearish.negative_reasons


class FakeLLM:
    def __init__(self, content: object) -> None:
        self.content = json.dumps(content)
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return type("LLMResponse", (), {"content": self.content})()


def test_llm_review_path_parses_json_clamps_scores_and_falls_back_per_invalid_symbol() -> None:
    llm = FakeLLM(
        {
            "reviews": [
                {
                    "symbol": "688001.SH",
                    "theme": "AI chips",
                    "catalyst_relevance": 1.4,
                    "company_fit": 0.8,
                    "event_novelty": 0.7,
                    "evidence_consistency": 0.6,
                    "source_reliability": 0.9,
                    "crowding_risk": -0.2,
                    "stale_news_risk": 0.1,
                    "hype_risk": 0.3,
                    "semantic_verdict": "candidate",
                    "positive_reasons": ["official policy maps to the company"],
                    "negative_reasons": [],
                    "evidence_ids": ["llm-evidence"],
                },
                {
                    "symbol": "300001.SZ",
                    "theme": "Bad JSON member is missing required score fields",
                    "semantic_verdict": "candidate",
                },
            ]
        }
    )
    agent = PremarketSemanticReviewAgent(llm_gateway=llm)

    result = agent.review(
        [
            _event("e1", "688001.SH"),
            _event("e2", "300001.SZ", bias=Bias.BEARISH, actionability=Actionability.BLOCK, risk_flags=["regulatory"]),
        ],
        trading_day=date(2026, 6, 19),
    )

    assert len(llm.calls) == 1
    assert "json" in json.dumps(llm.calls[0], default=str).lower()
    assert len(result.reviews) == 2
    llm_review = result.reviews[0]
    fallback_review = result.reviews[1]
    assert llm_review.symbol == "688001.SH"
    assert llm_review.theme == "AI chips"
    assert llm_review.catalyst_relevance == 1.0
    assert llm_review.crowding_risk == 0.0
    assert llm_review.evidence_ids == ["llm-evidence"]
    assert fallback_review.symbol == "300001.SZ"
    assert fallback_review.semantic_verdict in {"reject", "watch_only"}
    assert fallback_review.negative_reasons


def test_llm_review_path_uses_gateway_response_schema() -> None:
    client = MockModelClient(
        outputs=[
            {
                "reviews": [
                    {
                        "symbol": "688001.SH",
                        "theme": "AI chips",
                        "catalyst_relevance": 0.9,
                        "company_fit": 0.8,
                        "event_novelty": 0.7,
                        "evidence_consistency": 0.8,
                        "source_reliability": 0.9,
                        "crowding_risk": 0.2,
                        "stale_news_risk": 0.1,
                        "hype_risk": 0.3,
                        "semantic_verdict": "candidate",
                        "positive_reasons": ["official policy maps to the company"],
                        "negative_reasons": [],
                        "evidence_ids": ["llm-evidence"],
                    }
                ]
            }
        ]
    )
    gateway = LLMGateway(clients={"mock": client})
    agent = PremarketSemanticReviewAgent(llm_gateway=gateway)

    result = agent.review([_event("e1", "688001.SH")], trading_day=date(2026, 6, 19))

    assert result.reviews[0].theme == "AI chips"
    assert client.requests[0].response_schema == {"required": ["reviews"]}
    assert client.requests[0].metadata["agent"] == "premarket_semantic_review"


def test_semantic_review_classes_are_exported_from_premarket_package() -> None:
    from trading_agent_system.agents.premarket_agent import (  # noqa: PLC0415
        PremarketSemanticReview,
        PremarketSemanticReviewAgent as ExportedAgent,
        PremarketSemanticReviewSet,
    )

    assert ExportedAgent is PremarketSemanticReviewAgent
    assert PremarketSemanticReview.__name__ == "PremarketSemanticReview"
    assert PremarketSemanticReviewSet.__name__ == "PremarketSemanticReviewSet"
