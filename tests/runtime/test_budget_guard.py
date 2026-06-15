import pytest

from trading_agent_system.core.llm_gateway import TokenUsage
from trading_agent_system.core.runtime import BudgetExceeded, BudgetGuard, RuntimeBudget


def test_llm_call_allowed_under_budget():
    guard = BudgetGuard(RuntimeBudget(max_llm_calls=2, max_llm_tokens=100, max_llm_cost=1.0))

    guard.assert_llm_allowed(estimated_tokens=20, estimated_cost=0.25)

    assert guard.remaining()["llm_calls"] == 2


def test_llm_token_budget_exceeded_raises():
    guard = BudgetGuard(RuntimeBudget(max_llm_tokens=10))

    with pytest.raises(BudgetExceeded, match="LLM token budget exceeded"):
        guard.assert_llm_allowed(estimated_tokens=11)


def test_llm_cost_budget_exceeded_raises():
    guard = BudgetGuard(RuntimeBudget(max_llm_cost=0.5))

    with pytest.raises(BudgetExceeded, match="LLM cost budget exceeded"):
        guard.assert_llm_allowed(estimated_cost=0.51)


def test_tool_call_budget_exceeded_raises():
    guard = BudgetGuard(RuntimeBudget(max_tool_calls=0))

    with pytest.raises(BudgetExceeded, match="tool call budget exceeded"):
        guard.assert_tool_allowed()


def test_usage_recording_updates_spent_totals():
    guard = BudgetGuard(RuntimeBudget(max_llm_calls=3, max_llm_tokens=100, max_llm_cost=1.0, max_tool_calls=2))

    guard.record_llm_usage(TokenUsage(prompt_tokens=10, completion_tokens=5, estimated_cost=0.2))
    guard.record_tool_call()

    assert guard.budget.spent_llm_calls == 1
    assert guard.budget.spent_llm_tokens == 15
    assert guard.budget.spent_llm_cost == 0.2
    assert guard.budget.spent_tool_calls == 1


def test_remaining_budget_is_exported():
    guard = BudgetGuard(RuntimeBudget(max_llm_calls=3, max_llm_tokens=100, max_llm_cost=1.0, max_tool_calls=2))
    guard.record_llm_usage(TokenUsage(total_tokens=25, estimated_cost=0.4))
    guard.record_tool_call()

    assert guard.remaining() == {
        "llm_calls": 2,
        "llm_tokens": 75,
        "llm_cost": 0.6,
        "tool_calls": 1,
    }


def test_metrics_fields_export_current_usage_and_remaining_budget():
    guard = BudgetGuard(RuntimeBudget(max_llm_calls=3, max_llm_tokens=100, max_llm_cost=1.0, max_tool_calls=2))
    guard.record_llm_usage(TokenUsage(total_tokens=25, estimated_cost=0.4))

    fields = guard.metrics_fields()

    assert fields["spent_llm_calls"] == 1
    assert fields["spent_llm_tokens"] == 25
    assert fields["spent_llm_cost"] == 0.4
    assert fields["remaining_llm_calls"] == 2
