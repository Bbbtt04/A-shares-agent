# One-Pick Multi-Agent Runtime And Strategy Learning Implementation Plan

> For future Codex workers: use SDD by default. Implement this plan task-by-task, with tests first where possible. Keep changes small, observable, and rollbackable.

## Goal

Implement the runtime foundation required for the one-pick two-day paper-trading multi-agent loop, then implement the loop itself.

The feature recommends one concrete A-share stock from premarket information, gives confidence and risk/reward data, paper-buys it, forces a next-day exit, and uses the two-day result to update a versioned learning state.

## Architecture Rule

Do not implement the one-pick agents before the runtime layer exists.

Required order:

```text
M14 Runtime checkpoint and budget layer
-> M15 Strategy learning state
-> M16 One-pick multi-agent loop
-> M17 API/Web/debug integration
```

---

## M14 Runtime Checkpoint And Budget Layer

### Files

Create:

- `trading_agent_system/core/runtime/__init__.py`
- `trading_agent_system/core/runtime/context.py`
- `trading_agent_system/core/runtime/checkpoint.py`
- `trading_agent_system/core/runtime/budget.py`
- `trading_agent_system/core/runtime/step_runner.py`
- `tests/runtime/test_checkpoint_store.py`
- `tests/runtime/test_budget_guard.py`
- `tests/runtime/test_step_runner.py`

### Task 1: Checkpoint Store

- [ ] Write failing tests in `tests/runtime/test_checkpoint_store.py`.

Tests must cover:

- save successful checkpoint
- load checkpoint by `run_id + step`
- load latest checkpoint
- save failed checkpoint with error
- invalidate a checkpoint
- idempotent resume skips a completed step

Suggested model fields:

```python
class RuntimeCheckpoint(StrictBaseModel):
    checkpoint_id: str
    run_id: str
    trading_day: date | None
    agent: str
    step: str
    status: Literal["pending", "running", "success", "failed", "invalidated"]
    input_refs: list[str]
    output_refs: list[str]
    payload: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] Implement `CheckpointStore`.
- [ ] Store checkpoints as JSONL under `data/runtime/checkpoints`.
- [ ] Keep a small in-memory index for tests and fast lookup.
- [ ] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_checkpoint_store.py -q --basetemp=.tmp\pytest -p no:cacheprovider
```

### Task 2: Budget Guard

- [ ] Write failing tests in `tests/runtime/test_budget_guard.py`.

Tests must cover:

- LLM call allowed under budget
- LLM token budget exceeded raises
- LLM cost budget exceeded raises
- tool call budget exceeded raises
- usage recording updates spent totals
- remaining budget is exported

Suggested models:

```python
class RuntimeBudget(StrictBaseModel):
    max_llm_calls: int | None = None
    max_llm_tokens: int | None = None
    max_llm_cost: float | None = None
    max_tool_calls: int | None = None
    spent_llm_calls: int = 0
    spent_llm_tokens: int = 0
    spent_llm_cost: float = 0
    spent_tool_calls: int = 0
```

- [ ] Implement `BudgetGuard`.
- [ ] Integrate with `TokenUsage` from LLM Gateway.
- [ ] Emit metrics-compatible fields, but do not require MetricsRecorder in the guard itself.
- [ ] Run focused tests.

### Task 3: Agent Run Context

- [ ] Add `AgentRunContext` in `context.py`.
- [ ] Include `run_id`, `trading_day`, `agent`, `correlation_id`, `permission_profile`, `budget`, and `metadata`.
- [ ] Add tests in `test_step_runner.py` or a dedicated context test if needed.

### Task 4: Step Runner

- [ ] Write failing tests in `tests/runtime/test_step_runner.py`.

Tests must cover:

- successful step writes trace, metric, audit, event, and checkpoint
- failed step writes failed checkpoint and trace error
- completed step is skipped on rerun
- `force=True` reruns the step
- budget failure prevents step execution

- [ ] Implement `StepRunner`.
- [ ] Dependencies should be injected:

```python
StepRunner(
    checkpoint_store,
    trace_logger,
    metrics_recorder,
    audit_ledger,
    event_bus,
    budget_guard,
)
```

- [ ] Step function signature should receive `AgentRunContext`.
- [ ] Run runtime tests.

---

## M15 Strategy Learning State

### Files

Create:

- `configs/one_pick_two_day.yaml`
- `trading_agent_system/core/strategy_learning/__init__.py`
- `trading_agent_system/core/strategy_learning/store.py`
- `trading_agent_system/core/strategy_learning/updater.py`
- `tests/strategy_learning/test_learning_store.py`
- `tests/strategy_learning/test_learning_updater.py`

Modify:

- `configs/strategy_registry.yaml`

### Task 5: Add Strategy Registry Entry

- [ ] Add `one_pick_two_day_v1` to `configs/strategy_registry.yaml`.
- [ ] Keep it paper-only.
- [ ] Block `unverified`, `rumor`, `regulatory_inquiry`, and `delisting_risk`.

### Task 6: Add Base Strategy Config

- [ ] Create `configs/one_pick_two_day.yaml`.

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

Include conservative defaults:

```yaml
selection:
  force_pick_one: true
  min_confidence_to_buy: 0.60
  min_risk_reward_ratio: 1.80
  max_candidates: 20

runtime_budget:
  max_llm_calls: 3
  max_llm_tokens: 6000
  max_llm_cost: 1.00
  max_tool_calls: 40
```

### Task 7: Learning State Store

- [ ] Write failing tests for:

- initial empty state
- create first version
- create next version
- get current version
- rollback to previous version
- rollback audit payload shape

- [ ] Implement `LearningStateStore`.
- [ ] Store immutable versions under `data/strategy_learning/one_pick_versions.jsonl`.
- [ ] Store current pointer in `data/strategy_learning/one_pick_current.json`.
- [ ] Do not overwrite old versions.

### Task 8: Learning Updater

- [ ] Write failing tests for bounded updates.

Tests must cover:

- profitable outcome increases contributing positive feature weights
- losing outcome decreases contributing feature weights
- high-open-chase losing tag increases risk penalty or confidence penalty
- single update is capped by `max_weight_step`
- total weight delta is capped by min/max bounds

- [ ] Implement `LearningUpdater`.

Update formula:

```text
delta_weight(feature) =
  clamp(learning_rate * outcome_score * normalized_feature_score, -max_weight_step, max_weight_step)
```

Outcome score:

```text
outcome_score =
  pnl_pct
+ 0.5 * max_favorable_excursion_pct
- 0.7 * abs(max_adverse_excursion_pct)
+ 0.02 if hit_take_profit
- 0.03 if hit_stop_loss
```

---

## M16 One-Pick Multi-Agent Loop

### Files

Create:

- `trading_agent_system/agents/one_pick_agent/__init__.py`
- `trading_agent_system/agents/one_pick_agent/schemas.py`
- `trading_agent_system/agents/one_pick_agent/strategy_loader.py`
- `trading_agent_system/agents/one_pick_agent/candidate_generator.py`
- `trading_agent_system/agents/one_pick_agent/stock_selector.py`
- `trading_agent_system/agents/one_pick_agent/trade_plan.py`
- `trading_agent_system/agents/one_pick_agent/next_day_exit.py`
- `trading_agent_system/agents/one_pick_agent/review_learning.py`
- `trading_agent_system/agents/one_pick_agent/agent.py`
- `scripts/run_one_pick_agent.py`
- `tests/one_pick/test_schemas.py`
- `tests/one_pick/test_strategy_loader.py`
- `tests/one_pick/test_candidate_generator.py`
- `tests/one_pick/test_stock_selector.py`
- `tests/one_pick/test_trade_plan.py`
- `tests/one_pick/test_next_day_exit.py`
- `tests/one_pick/test_review_learning.py`
- `tests/one_pick/test_agent_runtime_integration.py`

### Task 9: Schemas

- [ ] Write schema tests.
- [ ] Implement:

```text
OnePickCandidate
OnePickSelection
OnePickTradePlan
OnePickExecutionRecord
OnePickExitPlan
OnePickOutcome
LearningState
LearningUpdate
EffectiveOnePickStrategy
```

Validation requirements:

- confidence between 0 and 1
- risk_reward_ratio positive
- expected downside positive
- selected symbol required
- trade plan must have at least one buy reason
- outcome must include entry and exit price

### Task 10: Strategy Loader

- [ ] Write tests for merging base config and learning state.
- [ ] Implement `OnePickStrategyLoader`.
- [ ] Load base config from `configs/one_pick_two_day.yaml`.
- [ ] Load learning state from `LearningStateStore`.
- [ ] Produce `EffectiveOnePickStrategy`.

### Task 11: Candidate Generator

- [ ] Write tests using premarket events and evidence packs.
- [ ] Implement deterministic first version.
- [ ] Inputs:

- premarket events
- event clusters
- RAG evidence packs
- market snapshots when available

- [ ] Output `OnePickCandidate` records with:

- feature scores
- evidence IDs
- risk flags
- strategy tags
- source rank

### Task 12: Stock Selector

- [ ] Write tests for ranking and forced one-pick behavior.
- [ ] Implement selection formula using effective weights.
- [ ] Return exactly one selection if `force_pick_one=true`.
- [ ] Mark `threshold_passed=false` if confidence/risk reward fail.

### Task 13: Trade Plan

- [ ] Write tests for confidence, risk/reward, and reasons.
- [ ] Implement `TradePlanAgent`.
- [ ] If LLM is used, call only through `LLMGateway`.
- [ ] Use structured output schema validation.
- [ ] Include:

- buy reasons
- risk reasons
- confidence
- expected upside
- expected downside
- risk reward ratio
- entry plan
- exit plan
- evidence IDs

### Task 14: Paper Buy Integration

- [ ] Write tests proving idempotent buy submission.
- [ ] Convert trade plan into `TradeIntent`.
- [ ] Use existing RiskGateway and PaperBroker where possible.
- [ ] Publish:

```text
one_pick.trade_plan_created
one_pick.buy_order_submitted
one_pick.buy_filled
```

### Task 15: Next-Day Exit

- [ ] Write tests for:

- take-profit exit
- stop-loss exit
- forced time exit
- no remaining position invariant

- [ ] Implement `NextDayExitAgent`.
- [ ] Publish:

```text
one_pick.next_day_exit_planned
one_pick.sell_order_submitted
one_pick.sell_filled
```

### Task 16: Review Learning

- [ ] Write tests for outcome calculation and learning update creation.
- [ ] Implement `ReviewLearningAgent`.
- [ ] Compute:

- pnl_pct
- max_favorable_excursion_pct
- max_adverse_excursion_pct
- hit_take_profit
- hit_stop_loss
- direction_correct
- selected_feature_scores
- tag performance

- [ ] Create a new learning state version.
- [ ] Publish:

```text
one_pick.outcome_reviewed
one_pick.learning_state_updated
```

### Task 17: Orchestrating Agent

- [ ] Implement `OnePickAgent`.
- [ ] Every step must run through `StepRunner`.
- [ ] Required checkpoints:

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

- [ ] Add `scripts/run_one_pick_agent.py`.
- [ ] Script modes:

```text
--phase premarket
--phase exit
--phase review
--phase full-demo
--run-id
--date
--config
--force
```

---

## M17 API And Debug Surface

### Files

Modify:

- `trading_agent_system/api/app.py`
- `web/src/main.jsx`
- `web/src/styles.css`

Create:

- `tests/one_pick/test_one_pick_api.py`
- optional frontend IA tests if UI labels are added

### Task 18: API

- [ ] Add:

```text
GET /api/one-pick/latest
GET /api/one-pick/run/{run_id}
GET /api/one-pick/learning-state
POST /api/one-pick/learning-state/rollback
```

- [ ] API must expose checkpoints, trace refs, evidence refs, selected stock, trade plan, fills, outcome, and learning version.

### Task 19: Web Debug

- [ ] Add a one-pick debug panel.
- [ ] Show:

- selected symbol
- confidence
- risk/reward
- buy reasons
- risk reasons
- entry/exit prices
- pnl_pct
- checkpoint timeline
- budget usage
- learning update delta
- rollback target

---

## Verification Commands

Use repo-local pytest temp directory to avoid Windows temp permission issues:

```powershell
New-Item -ItemType Directory -Force .tmp\pytest | Out-Null
.\.venv\Scripts\python.exe -m pytest tests\runtime tests\strategy_learning tests\one_pick -q --basetemp=.tmp\pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\infrastructure tests\observability tests\risk -q --basetemp=.tmp\pytest -p no:cacheprovider
git diff --check
```

Frontend build, if Node is available:

```powershell
cd web
npm run build
```

## Completion Criteria

- Runtime tests pass.
- Strategy learning tests pass.
- One-pick tests pass.
- Existing infrastructure/observability/risk tests pass.
- Every new agent step uses `StepRunner`.
- No direct LLM calls outside `LLMGateway`.
- Learning state can be rolled back.
- A failed run can resume from its latest successful checkpoint.
- A repeated run does not duplicate buy/sell orders unless `--force` is supplied.
- Budget overruns stop execution before extra LLM/tool calls.
- Final output is fully traceable through run ID, checkpoints, audit records, events, evidence IDs, and metrics.
