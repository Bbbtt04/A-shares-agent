from __future__ import annotations

from datetime import timezone

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalTask

from .base import BaseListRetriever


class RecencyRetriever(BaseListRetriever):
    retrieval_method = "recency"

    def score(self, task: RetrievalTask, document: RAGDocument) -> float:
        if document.published_at is None:
            return 0.45
        now = document.published_at.astimezone(timezone.utc)
        age_seconds = max(0.0, (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds())
        return min(1.0, 0.4 + age_seconds / 86400 * 0.4 + document.source_rank * 0.2)
