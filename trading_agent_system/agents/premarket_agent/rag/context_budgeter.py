from __future__ import annotations

from math import ceil

from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalResult


class ContextBudgeter:
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    def fit(self, results: list[RetrievalResult]) -> tuple[list[RetrievalResult], int, int]:
        selected: list[RetrievalResult] = []
        token_total = 0
        dropped_low_confidence = 0
        ordered = sorted(results, key=lambda item: (item.final_score or item.raw_score, item.confidence), reverse=True)
        for result in ordered:
            estimate = token_estimate(f"{result.title} {result.content}")
            if token_total + estimate > self.max_tokens:
                if result.confidence < 0.5:
                    dropped_low_confidence += 1
                continue
            selected.append(result)
            token_total += estimate
        return selected, token_total, dropped_low_confidence


def token_estimate(text: str) -> int:
    return ceil(len(text) / 2)
