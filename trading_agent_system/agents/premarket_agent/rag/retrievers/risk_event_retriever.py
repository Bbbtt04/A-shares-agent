from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, RetrievalTask

from .base import BaseListRetriever


CRITICAL_RISK_FLAGS = {
    "regulatory_penalty",
    "regulatory_inquiry",
    "delisting_risk",
    "suspension",
    "suspension_resumption",
    "debt_risk",
    "litigation",
    "shareholder_reduction",
    "pledge",
    "performance_loss",
    "unverified",
    "rumor",
}


class RiskEventRetriever(BaseListRetriever):
    retrieval_method = "risk_event"

    def matches(self, task: RetrievalTask, document: RAGDocument) -> bool:
        filters = task.filters
        if filters.trading_day and document.trading_day != filters.trading_day:
            return False
        if filters.premarket_window_id and document.premarket_window_id != filters.premarket_window_id:
            return False
        if filters.symbols and not set(filters.symbols).intersection(document.symbols):
            return False
        if filters.risk_flags_exclude and set(filters.risk_flags_exclude).intersection(document.risk_flags):
            return False
        if filters.risk_flags_include:
            return bool(set(filters.risk_flags_include).intersection(document.risk_flags))
        return bool(CRITICAL_RISK_FLAGS.intersection(document.risk_flags))

    def score(self, task: RetrievalTask, document: RAGDocument) -> float:
        severity = 1.0 if {"regulatory_penalty", "delisting_risk", "suspension"}.intersection(document.risk_flags) else 0.75
        return min(1.0, severity + document.source_rank * 0.1)
