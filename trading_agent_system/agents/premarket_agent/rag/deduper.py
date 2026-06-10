from __future__ import annotations

from collections import defaultdict

from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalResult


class EventClusterDeduper:
    def __init__(self, max_per_cluster: int = 1) -> None:
        self.max_per_cluster = max_per_cluster

    def dedup(self, results: list[RetrievalResult]) -> tuple[list[RetrievalResult], int]:
        grouped: dict[str, list[RetrievalResult]] = defaultdict(list)
        for result in results:
            key = result.event_cluster_id or result.event_id or result.doc_id
            grouped[key].append(result)
        selected: list[RetrievalResult] = []
        dropped = 0
        for items in grouped.values():
            ordered = sorted(items, key=lambda item: item.final_score or item.raw_score, reverse=True)
            selected.extend(ordered[: self.max_per_cluster])
            dropped += max(0, len(ordered) - self.max_per_cluster)
        return sorted(selected, key=lambda item: item.final_score or item.raw_score, reverse=True), dropped
