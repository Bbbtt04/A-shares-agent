from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalTask

from .keyword_retriever import KeywordRetriever


class ThemeRetriever(KeywordRetriever):
    retrieval_method = "theme"

    def matches(self, task: RetrievalTask, document: RAGDocument) -> bool:
        return bool(document.themes) and super().matches(task, document)
