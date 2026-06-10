from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalTask

from .base import BaseListRetriever, matches_filter


class PortfolioRetriever(BaseListRetriever):
    retrieval_method = "portfolio"

    def matches(self, task: RetrievalTask, document: RAGDocument) -> bool:
        if not matches_filter(task, document):
            return False
        return document.is_holding_related or document.is_watchlist_related or bool(task.filters.symbols and set(task.filters.symbols).intersection(document.symbols))

    def score(self, task: RetrievalTask, document: RAGDocument) -> float:
        return min(1.0, 0.7 + document.source_rank * 0.2 + document.confidence * 0.1)
