from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalTask

from .base import BaseListRetriever, keyword_score, matches_filter


class KeywordRetriever(BaseListRetriever):
    retrieval_method = "keyword"

    def matches(self, task: RetrievalTask, document: RAGDocument) -> bool:
        return matches_filter(task, document) and keyword_score(task.query, document) > 0

    def score(self, task: RetrievalTask, document: RAGDocument) -> float:
        return keyword_score(task.query, document)
