from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalResult, RetrievalTask


class BaseListRetriever:
    retrieval_method = "base"

    def __init__(self, documents: list[RAGDocument]) -> None:
        self.documents = documents

    def retrieve(self, task: RetrievalTask) -> list[RetrievalResult]:
        results = [
            self._to_result(task, document, self.score(task, document))
            for document in self.documents
            if self.matches(task, document)
        ]
        return sorted(results, key=lambda item: item.raw_score, reverse=True)[: task.top_k_per_retriever]

    def matches(self, task: RetrievalTask, document: RAGDocument) -> bool:
        return matches_filter(task, document)

    def score(self, task: RetrievalTask, document: RAGDocument) -> float:
        return 0.5

    def _to_result(self, task: RetrievalTask, document: RAGDocument, score: float) -> RetrievalResult:
        evidence_ids = [
            item
            for item in [document.event_id, document.event_cluster_id, document.raw_document_id, document.doc_id]
            if item
        ]
        return RetrievalResult(
            result_id=document.doc_id,
            task_id=task.task_id,
            doc_id=document.doc_id,
            event_id=document.event_id,
            event_cluster_id=document.event_cluster_id,
            content=document.content,
            title=document.title,
            source=document.source,
            source_type=document.source_type,
            source_rank=document.source_rank,
            published_at=document.published_at,
            symbols=document.symbols,
            event_type=document.event_type,
            themes=document.themes,
            importance=document.importance,
            risk_flags=document.risk_flags,
            retrieval_method=self.retrieval_method,
            raw_score=max(0.0, min(1.0, score)),
            final_score=max(0.0, min(1.0, score)),
            evidence_ids=evidence_ids,
            confidence=document.confidence,
            metadata=document.metadata,
        )


def matches_filter(task: RetrievalTask, document: RAGDocument) -> bool:
    filters = task.filters
    if filters.trading_day and document.trading_day != filters.trading_day:
        return False
    if filters.premarket_window_id and document.premarket_window_id != filters.premarket_window_id:
        return False
    if filters.source_types and document.source_type not in filters.source_types:
        return False
    if filters.min_source_rank is not None and document.source_rank < filters.min_source_rank:
        return False
    if filters.symbols and not set(filters.symbols).intersection(document.symbols):
        return False
    if filters.themes and not set(filters.themes).intersection(document.themes):
        return False
    if filters.event_types and document.event_type not in filters.event_types:
        return False
    if filters.importance and document.importance not in filters.importance:
        return False
    if filters.risk_flags_include and not set(filters.risk_flags_include).intersection(document.risk_flags):
        return False
    if filters.risk_flags_exclude and set(filters.risk_flags_exclude).intersection(document.risk_flags):
        return False
    if filters.holding_related_only and not document.is_holding_related:
        return False
    if filters.watchlist_related_only and not document.is_watchlist_related:
        return False
    if filters.verified_only and not document.is_verified:
        return False
    if filters.published_after and document.published_at and document.published_at < filters.published_after:
        return False
    if filters.published_before and document.published_at and document.published_at > filters.published_before:
        return False
    return True


def keyword_score(query: str, document: RAGDocument) -> float:
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return 0.5
    haystack = " ".join(
        [
            document.title,
            document.content,
            " ".join(document.symbols),
            " ".join(document.themes),
            document.event_type or "",
            " ".join(document.risk_flags),
        ]
    ).lower()
    matched = sum(1 for term in terms if term in haystack)
    return min(1.0, matched / max(1, len(terms)) + document.source_rank * 0.2 + document.confidence * 0.1)
