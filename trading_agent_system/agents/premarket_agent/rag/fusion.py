from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalResult


DEFAULT_RETRIEVER_WEIGHTS = {
    "structured": 1.4,
    "risk_event": 1.5,
    "portfolio": 1.6,
    "keyword": 1.2,
    "vector": 1.0,
    "theme": 1.1,
    "recency": 1.0,
}


def rrf_fuse(
    results_by_retriever: dict[str, list[RetrievalResult]],
    *,
    weights: dict[str, float] | None = None,
    k: int = 60,
) -> list[RetrievalResult]:
    weights = weights or DEFAULT_RETRIEVER_WEIGHTS
    scores: dict[str, float] = {}
    best: dict[str, RetrievalResult] = {}
    for retriever_name, results in results_by_retriever.items():
        weight = weights.get(retriever_name, 1.0)
        for rank, result in enumerate(results, start=1):
            scores[result.doc_id] = scores.get(result.doc_id, 0.0) + weight * (1.0 / (k + rank))
            current = best.get(result.doc_id)
            if current is None or (result.final_score or result.raw_score) > (current.final_score or current.raw_score):
                best[result.doc_id] = result
    fused = []
    for doc_id, score in scores.items():
        result = best[doc_id]
        business = business_score(result)
        fused_score = round(score, 6)
        final_score = round(0.6 * fused_score + 0.4 * business, 6)
        fused.append(result.model_copy(update={"fused_score": fused_score, "business_score": business, "final_score": final_score}))
    return sorted(fused, key=lambda item: item.final_score or 0, reverse=True)


def business_score(result: RetrievalResult) -> float:
    source = result.source_rank * 0.25
    importance = {"S": 0.25, "A": 0.2, "B": 0.12, "C": 0.05}.get(str(result.importance or ""), 0.05)
    confidence = result.confidence * 0.2
    risk = 0.15 if result.risk_flags else 0.0
    symbol = 0.1 if result.symbols else 0.0
    penalty = 0.25 if {"rumor", "unverified"}.intersection(result.risk_flags) else 0.0
    return round(max(0.0, min(1.0, source + importance + confidence + risk + symbol - penalty)), 6)
