from datetime import date, datetime, timezone

from trading_agent_system.agents.premarket_agent.rag.embeddings import DeterministicEmbeddingProvider
from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument
from trading_agent_system.agents.premarket_agent.rag.stores.qdrant_vector_store import QdrantVectorStore


def test_qdrant_vector_store_upserts_and_searches_documents(tmp_path):
    provider = DeterministicEmbeddingProvider(dimension=32)
    store = QdrantVectorStore(path=tmp_path / "qdrant", collection_name="premarket_hot", vector_size=32)
    document = RAGDocument(
        doc_id="doc_chip",
        title="半导体并购重组",
        content="半导体 并购 重组 政策支持",
        content_type="event_card",
        source="央视财经",
        source_type="authorized_news",
        source_rank=0.8,
        fetched_at=datetime.now(timezone.utc),
        trading_day=date(2026, 6, 10),
        premarket_window_id="pmw_20260610",
        themes=["半导体"],
        content_hash="hash_chip",
    )

    store.upsert_documents([document], provider)
    results = store.search(
        query_vector=provider.embed_text("半导体 并购"),
        trading_day=date(2026, 6, 10),
        premarket_window_id="pmw_20260610",
        top_k=3,
    )

    assert results[0].doc_id == "doc_chip"
    assert results[0].score > 0
