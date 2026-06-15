# One-Pick Multi-Agent Runtime And Strategy Learning Spec

## Goal

Build a controlled multi-agent experiment loop that recommends exactly one A-share stock from premarket information, paper-buys it, forces an exit on the next trading day, and uses the two-day result to update a versioned strategy learning state.

The system must be observable, budget-controlled, permissioned, auditable, checkpointed, and rollbackable before the trading loop is allowed to run.

## Non-Goals

- No real broker integration.
- No live trading.
- No automatic edits to Python strategy code.
- No direct LLM calls inside business agents.
- No unbounded autonomous agent loop.
- No learned-state update without a versioned rollback record.

## Required Infrastructure Upgrade

The current infrastructure has trace logging, metrics, durable JSONL events, audit records, LLM Gateway, Tool Registry, and sandbox permission profiles. It does not yet have a first-class runtime checkpoint store, hard budget guard, idempotent step runner, or rollbackable learning state.

Before implementing the one-pick agents, add a lightweight runtime layer:

```text
trading_agent_system/core/runtime/
  __init__.py
  context.py
  checkpoint.py
  budget.py
  step_runner.py
```

### AgentRunContext

Every agent step receives an `AgentRunContext`.

Required fields:

- `run_id`
- `trading_day`
- `agent`
- `correlation_id`
- `permission_profile`
- `budget`
- `metadata`

### CheckpointStore

Checkpoints are durable step state records.

Required fields:

- `checkpoint_id`
- `run_id`
- `trading_day`
- `agent`
- `step`
- `status`: `pending`, `running`, `success`, `failed`, `invalidated`
- `input_refs`
- `output_refs`
- `payload`
- `error`
- `created_at`
- `updated_at`

Required behavior:

- Save checkpoint after every successful step.
- Save failed checkpoint when a step raises.
- Load checkpoint by `run_id + step`.
- Load latest checkpoint for a run.
- Mark a checkpoint or run invalidated.
- Support idempotent resume: a completed step with the same run and step can be skipped unless `force=True`.

Initial storage can be JSONL plus in-memory index. A SQLite implementation can be added later.

### BudgetGuard

The runtime must enforce hard budgets, not just record usage.

Required budget fields:

- `max_llm_calls`
- `max_llm_tokens`
- `max_llm_cost`
- `max_tool_calls`
- `spent_llm_calls`
- `spent_llm_tokens`
- `spent_llm_cost`
- `spent_tool_calls`

Required behavior:

- Reject LLM calls when budget would be exceeded.
- Reject tool calls when budget would be exceeded.
- Record LLM usage after every Gateway response.
- Record tool calls after every ToolExecutor result.
- Emit metrics for spent and remaining budget.

### StepRunner

All new multi-agent steps must run through `StepRunner`.

StepRunner must:

- Check if checkpoint already succeeded.
- Check budget before step execution.
- Open a trace span.
- Execute the step.
- Write audit record.
- Write durable event if configured.
- Save checkpoint.
- Record metrics.
- Save failed checkpoint on exception.

## Strategy Files

The existing strategy registry remains the safety and enablement boundary:

```text
configs/strategy_registry.yaml
```

Add a strategy entry:

```yaml
  - strategy_id: one_pick_two_day_v1
    version: 1.0.0
    enabled: true
    mode: paper
    allowed_symbols:
      - "*"
    allowed_sides:
      - buy
      - sell
    max_confidence_cap: 0.85
    requires_intel_confirmation: true
    blocked_risk_flags:
      - unverified
      - rumor
      - regulatory_inquiry
      - delisting_risk
```

Add a dedicated configurable strategy file:

```text
configs/one_pick_two_day.yaml
```

Required sections:

- `strategy_id`
- `version`
- `mode`
- `selection`
- `scoring_weights`
- `confidence_model`
- `risk_reward`
- `entry_rule`
- `exit_rule`
- `learning`
- `runtime_budget`

The strategy learning state is not written back into config. It is stored separately:

```text
data/strategy_learning/one_pick_state.json
```

## Effective Strategy

Each run loads:

```text
base strategy config + versioned learning state = effective strategy
```

The effective score is:

```text
candidate_score =
  catalyst_strength * effective_weight.catalyst_strength
+ source_quality * effective_weight.source_quality
+ theme_strength * effective_weight.theme_strength
+ stock_relevance * effective_weight.stock_relevance
+ liquidity * effective_weight.liquidity
+ opening_confirmation * effective_weight.opening_confirmation
+ historical_similarity * effective_weight.historical_similarity
+ risk_penalty * effective_weight.risk_penalty
```

Confidence is separate from the score:

```text
confidence =
  base
+ evidence_coverage_adjustment
+ source_quality_adjustment
+ agreement_adjustment
+ historical_similarity_adjustment
- risk_adjustment
+ confidence_calibration.bias
- confidence_calibration.overconfidence_penalty
```

Risk reward is:

```text
risk_reward_ratio = expected_upside_pct / expected_downside_pct
```

## Multi-Agent Components

Add a bounded package:

```text
trading_agent_system/agents/one_pick_agent/
  __init__.py
  schemas.py
  strategy_loader.py
  candidate_generator.py
  stock_selector.py
  trade_plan.py
  next_day_exit.py
  review_learning.py
  agent.py
```

### PremarketIntelAgent

May initially be an adapter over existing premarket outputs and RAG evidence packs.

Responsibilities:

- Read premarket reports, events, RAG evidence packs, market snapshots, and watchlist data.
- Produce normalized premarket intelligence for candidate generation.
- Use Tool Registry for data access.
- Use checkpoints and trace.

### CandidateGenerationAgent

Responsibilities:

- Map catalysts and themes to A-share candidates.
- Produce feature scores for each candidate.
- Include evidence IDs and risk flags.
- Filter untradeable or blocked symbols.

### StockSelectionAgent

Responsibilities:

- Load the effective strategy.
- Rank candidates.
- Select exactly one stock when `force_pick_one=true`.
- Mark whether thresholds passed.
- Produce structured reasons.

### TradePlanAgent

Responsibilities:

- Produce buy plan with confidence, expected upside, expected downside, risk reward, entry rule, exit rule, and evidence.
- Use LLM Gateway only if explanation or structured reasoning requires model help.
- Never call a model directly.
- Validate structured output.

### PaperExecutionService

Responsibilities:

- Convert the selected plan into paper buy intent/instruction.
- Submit through existing RiskGateway and PaperBroker flow where possible.
- Enforce idempotency by `run_id + symbol + side + trading_day`.

### NextDayExitAgent

Responsibilities:

- Force exit on next trading day.
- Sell if take-profit hit.
- Sell if stop-loss hit.
- Otherwise sell at configured forced exit time.
- Always leave no position from this experiment after the exit day.

### ReviewLearningAgent

Responsibilities:

- Compute outcome from buy fill, sell fill, and two-day bars.
- Produce attribution and learning update.
- Write a new version of learning state.
- Allow rollback to any previous learning state version.
- Never modify Python strategy code.
- Never modify base config automatically.

## Required Schemas

Add structured models for:

- `OnePickCandidate`
- `OnePickSelection`
- `OnePickTradePlan`
- `OnePickExecutionRecord`
- `OnePickExitPlan`
- `OnePickOutcome`
- `LearningState`
- `LearningUpdate`
- `EffectiveOnePickStrategy`

Every model must use Pydantic and strict validation.

## Runtime Checkpoints For This Loop

Required checkpoint names:

```text
premarket_intel_collected
candidates_generated
stock_selected
trade_plan_created
buy_order_submitted
buy_filled
next_day_exit_planned
sell_order_submitted
sell_filled
outcome_reviewed
learning_state_updated
```

## Rollback Requirements

Rollback applies to learning state, not to market events.

Required behavior:

- Every learning update creates a new immutable version.
- The current learning state points to a version ID.
- Rollback switches the current pointer to a previous version.
- Rollback writes an audit record.
- Rollback writes a checkpoint/event.
- Past events and fills remain append-only.

## Observability Requirements

Every agent step must emit:

- Trace span
- Step metric
- Success/failure metric
- Durable event
- Audit record
- Checkpoint

Minimum metrics:

- `one_pick_run_total`
- `one_pick_step_duration_ms`
- `one_pick_candidate_count`
- `one_pick_selected_confidence`
- `one_pick_risk_reward_ratio`
- `one_pick_threshold_passed`
- `one_pick_entry_fill_price`
- `one_pick_exit_fill_price`
- `one_pick_pnl_pct`
- `one_pick_learning_update_abs_delta`
- `runtime_budget_llm_tokens_spent`
- `runtime_budget_llm_cost_spent`
- `runtime_budget_tool_calls_spent`

## Acceptance Criteria

- New runtime layer has tests for checkpoint save/load/resume/failure/invalidation.
- New budget layer has tests for hard LLM and tool budget rejection.
- StepRunner has tests for success, failure, idempotent skip, and force rerun.
- One-pick strategy loader merges base config and learning state.
- Learning state is versioned and rollbackable.
- One-pick agents never direct-call LLMs; they use LLM Gateway.
- One-pick agents access external capabilities through Tool Registry where practical.
- Every one-pick step records trace, metrics, audit, event, and checkpoint.
- A full demo can run: premarket input -> select one stock -> paper buy -> next-day sell -> outcome -> learning update.
