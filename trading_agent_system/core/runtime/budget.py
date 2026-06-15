from __future__ import annotations

from pydantic import Field

from trading_agent_system.core.llm_gateway import TokenUsage
from trading_agent_system.schemas import StrictBaseModel


class BudgetExceeded(RuntimeError):
    """Raised before a runtime action would exceed its configured budget."""


class RuntimeBudget(StrictBaseModel):
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_llm_tokens: int | None = Field(default=None, ge=0)
    max_llm_cost: float | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    spent_llm_calls: int = Field(default=0, ge=0)
    spent_llm_tokens: int = Field(default=0, ge=0)
    spent_llm_cost: float = Field(default=0, ge=0)
    spent_tool_calls: int = Field(default=0, ge=0)


class BudgetGuard:
    def __init__(self, budget: RuntimeBudget | None = None) -> None:
        self.budget = budget or RuntimeBudget()

    def assert_llm_allowed(self, *, estimated_tokens: int = 0, estimated_cost: float = 0.0) -> None:
        if self._exceeds(self.budget.max_llm_calls, self.budget.spent_llm_calls + 1):
            raise BudgetExceeded("LLM call budget exceeded")
        if self._exceeds(self.budget.max_llm_tokens, self.budget.spent_llm_tokens + estimated_tokens):
            raise BudgetExceeded("LLM token budget exceeded")
        if self._exceeds(self.budget.max_llm_cost, self.budget.spent_llm_cost + estimated_cost):
            raise BudgetExceeded("LLM cost budget exceeded")

    def assert_tool_allowed(self) -> None:
        if self._exceeds(self.budget.max_tool_calls, self.budget.spent_tool_calls + 1):
            raise BudgetExceeded("tool call budget exceeded")

    def record_llm_usage(self, usage: TokenUsage) -> None:
        tokens = usage.total_tokens or usage.prompt_tokens + usage.completion_tokens
        self.budget.spent_llm_calls += 1
        self.budget.spent_llm_tokens += tokens
        self.budget.spent_llm_cost = self._rounded(self.budget.spent_llm_cost + usage.estimated_cost)

    def record_tool_call(self, count: int = 1) -> None:
        self.budget.spent_tool_calls += count

    def remaining(self) -> dict[str, int | float | None]:
        return {
            "llm_calls": self._remaining(self.budget.max_llm_calls, self.budget.spent_llm_calls),
            "llm_tokens": self._remaining(self.budget.max_llm_tokens, self.budget.spent_llm_tokens),
            "llm_cost": self._remaining(self.budget.max_llm_cost, self.budget.spent_llm_cost),
            "tool_calls": self._remaining(self.budget.max_tool_calls, self.budget.spent_tool_calls),
        }

    def metrics_fields(self) -> dict[str, int | float | None]:
        remaining = self.remaining()
        return {
            "spent_llm_calls": self.budget.spent_llm_calls,
            "spent_llm_tokens": self.budget.spent_llm_tokens,
            "spent_llm_cost": self.budget.spent_llm_cost,
            "spent_tool_calls": self.budget.spent_tool_calls,
            "remaining_llm_calls": remaining["llm_calls"],
            "remaining_llm_tokens": remaining["llm_tokens"],
            "remaining_llm_cost": remaining["llm_cost"],
            "remaining_tool_calls": remaining["tool_calls"],
        }

    @staticmethod
    def _exceeds(limit: int | float | None, value: int | float) -> bool:
        return limit is not None and value > limit

    @staticmethod
    def _remaining(limit: int | float | None, spent: int | float) -> int | float | None:
        if limit is None:
            return None
        return BudgetGuard._rounded(max(0, limit - spent))

    @staticmethod
    def _rounded(value: int | float) -> int | float:
        if isinstance(value, float):
            return round(value, 10)
        return value
