from __future__ import annotations

from datetime import date

from trading_agent_system.agents.premarket_agent.rag.context_budgeter import ContextBudgeter
from trading_agent_system.agents.premarket_agent.rag.deduper import EventClusterDeduper
from trading_agent_system.agents.premarket_agent.rag.schemas import EvidenceItem, EvidencePack, RetrievalResult


class EvidencePackBuilder:
    def __init__(self, max_tokens: int = 2000, max_per_event_cluster: int = 1) -> None:
        self.max_tokens = max_tokens
        self.max_per_event_cluster = max_per_event_cluster

    def build(
        self,
        *,
        trading_day: date,
        premarket_window_id: str,
        section: str,
        query: str,
        results: list[RetrievalResult],
    ) -> EvidencePack:
        deduped, dropped_duplicates = EventClusterDeduper(self.max_per_event_cluster).dedup(results)
        fitted, token_total, dropped_low_confidence = ContextBudgeter(self.max_tokens).fit(deduped)
        items = [self._to_item(result) for result in fitted]
        return EvidencePack(
            trading_day=trading_day,
            premarket_window_id=premarket_window_id,
            section=section,
            query=query,
            items=items,
            dropped_duplicates=dropped_duplicates,
            dropped_low_confidence=dropped_low_confidence,
            token_estimate=token_total,
            coverage={
                "result_count": len(results),
                "deduped_count": len(deduped),
                "evidence_count": len(items),
            },
        )

    def _to_item(self, result: RetrievalResult) -> EvidenceItem:
        evidence_id = result.evidence_ids[0] if result.evidence_ids else result.doc_id
        return EvidenceItem(
            evidence_id=evidence_id,
            event_id=result.event_id,
            event_cluster_id=result.event_cluster_id,
            source_id=result.evidence_ids[-1] if result.evidence_ids else result.doc_id,
            source=result.source,
            source_type=result.source_type,
            source_rank=result.source_rank,
            published_at=result.published_at,
            title=result.title,
            excerpt=result.content[:350],
            symbols=result.symbols,
            event_type=result.event_type,
            importance=result.importance,
            confidence=result.confidence,
            risk_flags=result.risk_flags,
            citation_label=f"[{evidence_id}]",
        )
