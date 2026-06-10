from __future__ import annotations

from trading_agent_system.agents.premarket_agent.rag.embeddings import EmbeddingProvider
from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalResult, RetrievalTask
from trading_agent_system.agents.premarket_agent.rag.stores import QdrantVectorStore


class VectorRetriever:
    retrieval_method = "vector"

    def __init__(self, vector_store: QdrantVectorStore, embeddings: EmbeddingProvider) -> None:
        self.vector_store = vector_store
        self.embeddings = embeddings

    def retrieve(self, task: RetrievalTask) -> list[RetrievalResult]:
        hits = self.vector_store.search(
            query_vector=self.embeddings.embed_text(task.query),
            trading_day=task.filters.trading_day,
            premarket_window_id=task.filters.premarket_window_id,
            top_k=task.top_k_per_retriever,
        )
        results = []
        for hit in hits:
            document = hit.document
            evidence_ids = [
                item
                for item in [document.event_id, document.event_cluster_id, document.raw_document_id, document.doc_id]
                if item
            ]
            results.append(
                RetrievalResult(
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
                    raw_score=hit.score,
                    final_score=hit.score,
                    evidence_ids=evidence_ids,
                    confidence=document.confidence,
                    metadata=document.metadata,
                )
            )
        return results
