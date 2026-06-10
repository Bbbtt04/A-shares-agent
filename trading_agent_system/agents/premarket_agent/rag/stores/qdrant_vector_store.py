from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from trading_agent_system.agents.premarket_agent.rag.embeddings import EmbeddingProvider
from trading_agent_system.agents.premarket_agent.rag.schemas import RAGDocument, VectorSearchHit


class QdrantVectorStore:
    def __init__(self, path: str | Path, collection_name: str, vector_size: int) -> None:
        self.path = Path(path)
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.client = QdrantClient(path=str(self.path))
        self._ensure_collection()

    def upsert_documents(self, documents: list[RAGDocument], embeddings: EmbeddingProvider) -> None:
        if not documents:
            return
        points = []
        for document in documents:
            payload = document.model_dump(mode="json")
            points.append(
                models.PointStruct(
                    id=_point_id(document.doc_id),
                    vector=embeddings.embed_text(_embedding_text(document)),
                    payload=payload,
                )
            )
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        *,
        query_vector: list[float],
        trading_day: object | None = None,
        premarket_window_id: str | None = None,
        top_k: int = 10,
    ) -> list[VectorSearchHit]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=_query_filter(trading_day=trading_day, premarket_window_id=premarket_window_id),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        return [
            VectorSearchHit(
                doc_id=str(point.payload["doc_id"]),
                score=float(point.score),
                document=RAGDocument.model_validate(point.payload),
            )
            for point in response.points
            if point.payload
        ]

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
        )


def _embedding_text(document: RAGDocument) -> str:
    return " ".join(
        [
            document.title,
            document.content,
            " ".join(document.symbols),
            " ".join(document.themes),
            document.event_type or "",
        ]
    )


def _query_filter(trading_day: object | None, premarket_window_id: str | None) -> models.Filter | None:
    must = []
    if trading_day is not None:
        must.append(models.FieldCondition(key="trading_day", match=models.MatchValue(value=str(trading_day))))
    if premarket_window_id:
        must.append(models.FieldCondition(key="premarket_window_id", match=models.MatchValue(value=premarket_window_id)))
    if not must:
        return None
    return models.Filter(must=must)


def _point_id(doc_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agu-agent-rag:{doc_id}"))
