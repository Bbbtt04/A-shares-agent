# Daily Premarket Strategy Automation And Learning Design

## Goal

Build a daily automated paper-strategy loop for the premarket agent:

- Before 09:15 on each trading day, produce today's strategy target and full decision trace.
- After the market opens at 09:30, settle yesterday's target using the next trading day's 09:30 open price.
- Persist every decision, score, price, outcome, and learning update into a database, not RAG.
- Provide a visualization layer for today's strategy, yesterday's settlement, factor learning, and decision replay.

This design does not implement real broker trading. It is a paper-trading and learning loop used to make the premarket agent measurable before a trading agent is ready.

## Non-Goals

- No real order placement.
- No broker account integration.
- No automatic Python strategy-code mutation.
- No RAG storage for decision records or outcomes.
- No unrestricted LLM authority to decide buy/sell alone.
- No learning update without versioned rollback.
- No dependency on intraday exit logic in the first version.

## Core Daily Jobs

The system runs two independent jobs every trading day.

### Job 1: Today's Premarket Recommendation

Target completion time: before 09:15.

Input:

- Today's premarket news, announcements, themes, market context, and structured events.
- Active factor-weight version.
- Optional LLM semantic review.

Output:

- Today's selected symbol or explicit no-trade state.
- Action: `buy`, `watch`, `avoid`, or `no_trade`.
- Signal score, confidence, factor contributions, risk notes, entry conditions, avoid conditions.
- Full decision audit trail.

### Job 2: Yesterday's Settlement And Learning

Target start time: after 09:30 when open prices are available.

Input:

- Yesterday's recommendation.
- Yesterday's 09:30 open price as paper buy price.
- Today's 09:30 open price as paper sell price.
- Active factor weights used by yesterday's recommendation.

Output:

- Paper return.
- Outcome label.
- Attribution against yesterday's factor scores.
- New factor-weight version if learning update is eligible.
- Full settlement and learning audit trail.

These two jobs are logically parallel. On trading day `T`, recommendation handles `T`, while settlement handles `T-1`.

## Daily Timeline

```text
08:45  Start data collection for trading day T
08:50  Normalize premarket events and evidence
08:55  Run LLM semantic review or deterministic fallback
09:00  Score factors using active weight version
09:05  Generate strategy recommendation
09:10  Persist decision records and publish latest API state
09:12  Deadline guard: if LLM is not done, degrade to deterministic scoring
09:15  Latest strategy must be available: buy/watch/avoid/no_trade

09:31  Fetch 09:30 open prices for T-1 recommendation and T sell date
09:33  Calculate paper outcome
09:35  Run learning update
09:36  Persist outcome, weight version, and visualization records
```

## Scheduling Model

First version can use a Python scheduler script:

```text
scripts/daily_premarket_scheduler.py
```

Recommended jobs:

```text
08:45  run_today_recommendation
09:31  run_yesterday_settlement
```

The scheduler must be idempotent:

- Running the same job twice for the same `trading_day` must not duplicate final recommendations.
- A failed run can be retried with the same `run_id` or a new retry `run_id`.
- Each job writes a `strategy_runs` row before starting and updates status on completion.

Recommended CLI entry points:

```text
scripts/run_daily_premarket_recommendation.py --date YYYY-MM-DD
scripts/run_daily_strategy_settlement.py --date YYYY-MM-DD
scripts/daily_premarket_scheduler.py
```

## Trading Calendar

The loop must use an A-share trading calendar, not simple weekdays.

Required behavior:

- Skip non-trading days.
- For settlement on day `T`, resolve `previous_trading_day(T)`.
- If previous recommendation does not exist, write a successful no-op settlement run.
- If today's 09:30 price is missing, mark settlement as `pending_price` instead of failed.

## Price And Return Definition

First-version paper-trading price policy:

```text
buy_price  = recommendation day T 09:30 open price
sell_price = next trading day T+1 09:30 open price
return_pct = (sell_price - buy_price) / buy_price
```

Eligibility:

- Only `action=buy` enters official learning.
- `action=watch` can be recorded as observation but should not update factor weights.
- `action=avoid` and `action=no_trade` do not create settlement positions.

Missing or abnormal prices:

- Suspended stock: outcome status `invalid_untradable`.
- Missing 09:30 open: outcome status `pending_price`.
- Zero or negative price: outcome status `invalid_price`.
- One-limit or no executable auction assumption: record `execution_warning`, but keep the price if data source marks it as valid open.

## LLM Role Boundary

The LLM can participate in semantic interpretation, but it must not be the sole decision maker.

Allowed LLM responsibilities:

- Judge whether a catalyst is genuinely relevant to a listed company.
- Detect stale news, repeated hype, weak source quality, or crowded narrative.
- Produce positive and negative reasons with evidence references.
- Summarize why a candidate is buy/watch/avoid for human review.

Not allowed:

- Directly choose final buy target without factor scoring.
- Directly modify factor weights.
- Invent market prices.
- Override risk controls.

Recommended boundary:

```text
LLM = semantic factor producer + explanation generator
Factor scorer = decision engine
Learning module = weight-version updater
Database = durable source of truth
RAG = optional evidence retrieval, not decision ledger
```

## Database Design

Use a relational database as the decision ledger.

Recommended production target: PostgreSQL.

Local development can start with SQLite if the repository layer keeps SQL portable.

### strategy_runs

One row per automated job run.

```sql
CREATE TABLE strategy_runs (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE,
  trading_day TEXT NOT NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_message TEXT,
  code_version TEXT,
  config_version TEXT,
  weight_version TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

`run_type` values:

- `premarket_recommend`
- `settlement_learning`

`status` values:

- `running`
- `success`
- `failed`
- `degraded`
- `skipped`
- `pending_price`

### premarket_events

Stores normalized premarket events used by the decision.

```sql
CREATE TABLE premarket_events (
  id INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  trading_day TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  symbol TEXT,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  theme TEXT,
  bias TEXT,
  confidence REAL,
  actionability TEXT,
  raw_payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### semantic_reviews

Stores LLM or fallback semantic review output.

```sql
CREATE TABLE semantic_reviews (
  id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  trading_day TEXT NOT NULL,
  symbol TEXT NOT NULL,
  theme TEXT,
  catalyst_relevance REAL NOT NULL,
  company_fit REAL NOT NULL,
  event_novelty REAL NOT NULL,
  evidence_consistency REAL NOT NULL,
  source_reliability REAL NOT NULL,
  crowding_risk REAL NOT NULL,
  stale_news_risk REAL NOT NULL,
  hype_risk REAL NOT NULL,
  semantic_verdict TEXT NOT NULL,
  positive_reasons_json TEXT NOT NULL,
  negative_reasons_json TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  llm_model TEXT,
  llm_prompt_hash TEXT,
  llm_response_json TEXT,
  created_at TEXT NOT NULL
);
```

### factor_scores

Stores factor values, weights, contributions, and final signal score.

```sql
CREATE TABLE factor_scores (
  id INTEGER PRIMARY KEY,
  score_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  trading_day TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal_score REAL NOT NULL,
  confidence REAL NOT NULL,
  recommendation TEXT NOT NULL,
  factor_scores_json TEXT NOT NULL,
  factor_weights_json TEXT NOT NULL,
  factor_contributions_json TEXT NOT NULL,
  risk_flags_json TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### strategy_recommendations

Stores the final handoff payload for the future trading agent.

```sql
CREATE TABLE strategy_recommendations (
  id INTEGER PRIMARY KEY,
  recommendation_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  trading_day TEXT NOT NULL,
  symbol TEXT,
  action TEXT NOT NULL,
  priority INTEGER NOT NULL,
  confidence REAL NOT NULL,
  signal_score REAL NOT NULL,
  expected_risk_reward REAL,
  entry_conditions_json TEXT NOT NULL,
  avoid_conditions_json TEXT NOT NULL,
  risk_notes_json TEXT NOT NULL,
  handoff_payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### strategy_prices

Stores the exact prices used for paper execution and settlement.

```sql
CREATE TABLE strategy_prices (
  id INTEGER PRIMARY KEY,
  trading_day TEXT NOT NULL,
  symbol TEXT NOT NULL,
  price_type TEXT NOT NULL,
  price_time TEXT NOT NULL,
  price REAL NOT NULL,
  source TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (trading_day, symbol, price_type, price_time, source)
);
```

`price_type` values:

- `buy_open`
- `sell_open`

### strategy_outcomes

Stores paper outcome for each official recommendation.

```sql
CREATE TABLE strategy_outcomes (
  id INTEGER PRIMARY KEY,
  outcome_id TEXT NOT NULL UNIQUE,
  recommendation_id TEXT NOT NULL,
  buy_trading_day TEXT NOT NULL,
  sell_trading_day TEXT NOT NULL,
  symbol TEXT NOT NULL,
  buy_price REAL,
  sell_price REAL,
  return_pct REAL,
  hit_result TEXT NOT NULL,
  outcome_label TEXT NOT NULL,
  attribution_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

`hit_result` values:

- `win`
- `loss`
- `flat`
- `invalid`
- `pending_price`

### factor_weight_versions

Stores versioned learning state and supports rollback.

```sql
CREATE TABLE factor_weight_versions (
  id INTEGER PRIMARY KEY,
  version TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  created_by_run_id TEXT NOT NULL,
  previous_version TEXT,
  is_active INTEGER NOT NULL,
  weights_json TEXT NOT NULL,
  learning_summary_json TEXT NOT NULL
);
```

Only one row should have `is_active = 1`.

### decision_audit_logs

Stores replayable decision steps.

```sql
CREATE TABLE decision_audit_logs (
  id INTEGER PRIMARY KEY,
  audit_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  trading_day TEXT NOT NULL,
  symbol TEXT,
  stage TEXT NOT NULL,
  input_json TEXT NOT NULL,
  output_json TEXT NOT NULL,
  reasoning_summary TEXT NOT NULL,
  model_name TEXT,
  latency_ms REAL,
  created_at TEXT NOT NULL
);
```

`stage` values:

- `collect`
- `semantic_review`
- `factor_scoring`
- `recommendation`
- `price_fetch`
- `settlement`
- `learning`
- `rollback`

## Storage Layer

Create a database repository layer instead of writing SQL directly in agents.

Suggested files:

```text
trading_agent_system/storage/strategy_db.py
trading_agent_system/storage/repositories/strategy_run_repository.py
trading_agent_system/storage/repositories/premarket_event_repository.py
trading_agent_system/storage/repositories/semantic_review_repository.py
trading_agent_system/storage/repositories/factor_score_repository.py
trading_agent_system/storage/repositories/recommendation_repository.py
trading_agent_system/storage/repositories/price_repository.py
trading_agent_system/storage/repositories/outcome_repository.py
trading_agent_system/storage/repositories/factor_weight_repository.py
trading_agent_system/storage/repositories/decision_audit_repository.py
```

The agent layer should receive repository interfaces or a unit-of-work object.

## Recommendation Pipeline

Pseudo-flow:

```python
def run_today_recommendation(trading_day):
    run = strategy_runs.start(
        run_type="premarket_recommend",
        trading_day=trading_day,
    )

    events = collect_and_normalize_premarket_events(trading_day)
    premarket_events.save_many(run.run_id, events)
    decision_audit.log(stage="collect", input={}, output=events)

    reviews = semantic_review_agent.review(
        events=events,
        trading_day=trading_day,
        llm_deadline="09:12",
    )
    semantic_reviews.save_many(run.run_id, reviews)
    decision_audit.log(stage="semantic_review", input=events, output=reviews)

    active_weights = factor_weight_versions.load_active()
    scores = factor_scorer.score(
        events=events,
        semantic_reviews=reviews,
        weights=active_weights,
    )
    factor_scores.save_many(run.run_id, scores)
    decision_audit.log(stage="factor_scoring", input=reviews, output=scores)

    recommendation = recommendation_agent.recommend(scores)
    strategy_recommendations.save(run.run_id, recommendation)
    decision_audit.log(stage="recommendation", input=scores, output=recommendation)

    strategy_runs.finish(run.run_id, status="success")
    return recommendation
```

Deadline behavior:

- If LLM review completes before the deadline, use LLM semantic factors.
- If LLM times out or fails, use deterministic semantic review and set run status `degraded`.
- If data collection fails completely, output `no_trade` with status `failed` or `degraded`, depending on available fallback data.

## Settlement And Learning Pipeline

Pseudo-flow:

```python
def run_yesterday_settlement(today):
    previous_day = trading_calendar.previous_trading_day(today)
    run = strategy_runs.start(
        run_type="settlement_learning",
        trading_day=today,
    )

    recommendation = recommendations.load_official_buy(previous_day)
    if recommendation is None:
        strategy_runs.finish(run.run_id, status="skipped")
        return None

    buy_price = prices.get_or_fetch_open(
        trading_day=previous_day,
        symbol=recommendation.symbol,
        price_type="buy_open",
        price_time="09:30",
    )
    sell_price = prices.get_or_fetch_open(
        trading_day=today,
        symbol=recommendation.symbol,
        price_type="sell_open",
        price_time="09:30",
    )

    outcome = outcome_evaluator.evaluate(
        recommendation=recommendation,
        buy_price=buy_price,
        sell_price=sell_price,
    )
    outcomes.save(outcome)
    decision_audit.log(stage="settlement", input=recommendation, output=outcome)

    if outcome.hit_result in {"win", "loss", "flat"}:
        learning_state = factor_learning_agent.update(outcome)
        factor_weight_versions.save_new_active_version(learning_state)
        decision_audit.log(stage="learning", input=outcome, output=learning_state)

    strategy_runs.finish(run.run_id, status="success")
    return outcome
```

## Learning Policy

First version should update factor weights conservatively.

Principles:

- Learn from official `buy` recommendations only.
- Do not learn from `watch`, `avoid`, `no_trade`, or invalid price outcomes.
- Do not let one day dominate the model.
- Always create a new rollbackable weight version.

Recommended controls:

```text
max_daily_weight_change = 0.03
min_factor_weight = 0.03
max_factor_weight = 0.25
minimum_samples_for_full_update = 20
small_sample_learning_multiplier = min(1.0, sample_count / 20)
```

Example update intuition:

```text
Winning sample:
  increase positive-contributing factors that were high
  decrease risk penalties only if risk did not materialize

Losing sample:
  decrease positive factors that were high but failed
  increase risk penalties if crowding, stale news, or hype risk were high

Flat sample:
  make smaller updates
  mostly reduce overconfident factors
```

The LLM should not directly update weights. It can write a learning note, but the deterministic learning agent decides the numeric update.

## API Surface

Recommended API endpoints:

```text
GET  /api/daily-strategy/latest
GET  /api/daily-strategy/runs
GET  /api/daily-strategy/runs/{run_id}
GET  /api/daily-strategy/recommendations/{trading_day}
GET  /api/daily-strategy/outcomes/{trading_day}
GET  /api/daily-strategy/factor-weights/active
GET  /api/daily-strategy/factor-weights/history
POST /api/daily-strategy/factor-weights/rollback
GET  /api/daily-strategy/audit/{run_id}
```

The existing premarket endpoints can remain as compatibility aliases if the frontend already uses them.

## Visualization Design

### Page 1: Today Strategy

Purpose: answer "What should I do before the open?"

Fields:

- Trading day.
- Run status and deadline status.
- Recommended symbol.
- Action.
- Signal score.
- Confidence.
- Expected risk-reward.
- Entry conditions.
- Avoid conditions.
- Risk notes.
- Evidence ids.

Charts:

- Factor contribution waterfall.
- Positive vs negative reason list.
- LLM semantic factor radar chart.

### Page 2: Decision Replay

Purpose: explain how the agent reached the decision.

Timeline:

```text
collect -> semantic_review -> factor_scoring -> recommendation
```

Each stage displays:

- Input summary.
- Output summary.
- Raw JSON expansion.
- Model name if LLM was used.
- Latency.
- Error or degradation reason.

### Page 3: Yesterday Settlement

Purpose: show whether yesterday's strategy worked.

Fields:

- Yesterday's symbol.
- Buy open price at yesterday 09:30.
- Sell open price at today 09:30.
- Return percentage.
- Hit result.
- Outcome label.
- Attribution.

Charts:

- Return card.
- Factor attribution table.
- Buy/sell price comparison.

### Page 4: Factor Learning

Purpose: show how the loop is adapting.

Fields:

- Active weight version.
- Previous version.
- Created by run.
- Learning summary.
- Rollback action.

Charts:

- Weight comparison bar chart.
- Weight change heatmap.
- Recent sample performance by factor.

### Page 5: History

Purpose: audit all daily decisions.

Table columns:

- Trading day.
- Symbol.
- Action.
- Signal score.
- Confidence.
- Buy price.
- Sell price.
- Return percentage.
- Weight version.
- Run status.

Filters:

- Date range.
- Action.
- Hit result.
- Weight version.
- Run status.

## Observability And Audit

Every job should emit:

- Structured logs.
- `strategy_runs` state transitions.
- Decision audit rows.
- LLM usage records through the existing LLM gateway audit.
- Error messages and degraded-mode reasons.

Each final recommendation must be reproducible from:

- `strategy_recommendations`
- `factor_scores`
- `semantic_reviews`
- `premarket_events`
- `factor_weight_versions`
- `decision_audit_logs`

## Failure Handling

Expected failure modes:

| Failure | Behavior |
| --- | --- |
| LLM timeout | Use deterministic review, mark recommendation run `degraded` |
| Missing premarket data | Produce `no_trade` if no reliable input remains |
| Missing buy price | Mark settlement `pending_price`, retry later |
| Missing sell price | Mark settlement `pending_price`, retry later |
| Invalid price | Mark outcome `invalid_price`, exclude from learning |
| Database write failure | Fail run and do not publish partial final recommendation |
| Duplicate scheduler trigger | Reuse existing completed run or skip |
| Learning update error | Save outcome, fail learning stage, keep previous active weights |

## Security And Safety

- Store API keys outside the database.
- Store LLM prompt hash and response body for audit, but avoid storing secret config.
- Add a manual kill switch for scheduled jobs.
- Keep learning updates in paper mode until enough history exists.
- Require explicit human approval before using these recommendations for real trading.

## Implementation Phases

### Phase 1: Database Ledger

Create database connection and repositories.

Deliverables:

- Schema migration.
- Repository tests.
- Ability to persist runs, recommendations, prices, outcomes, and audit logs.

### Phase 2: Recommendation Job

Wire existing premarket factor pipeline into the database.

Deliverables:

- `run_daily_premarket_recommendation.py`
- Persisted events, semantic reviews, factor scores, recommendation, audit logs.
- Latest API reads from database.

### Phase 3: Settlement Job

Add open-price fetch and paper settlement.

Deliverables:

- `run_daily_strategy_settlement.py`
- Price repository.
- Outcome calculation.
- Pending-price retry behavior.

### Phase 4: Learning Versioning

Move factor learning state into the database.

Deliverables:

- Active weight version.
- New weight version creation.
- Rollback.
- Learning audit trail.

### Phase 5: Scheduler

Add daily automation.

Deliverables:

- Trading-calendar-aware scheduler.
- Idempotent job execution.
- Deadline/degraded mode.

### Phase 6: Visualization

Build UI views backed by database APIs.

Deliverables:

- Today strategy page.
- Decision replay page.
- Settlement page.
- Factor learning page.
- History page.

## Open Decisions

1. Production database choice: PostgreSQL now, or SQLite first with repository abstraction.
2. Market data source for official 09:30 open prices.
3. Whether `watch` recommendations should be paper-settled as observations.
4. Minimum sample size before full learning updates are enabled.
5. Whether the scheduler runs inside the API service, as a standalone process, or via external cron.

## Recommended First Implementation Choice

Start with SQLite-compatible repositories and a standalone scheduler process.

Reason:

- Fast local iteration.
- Easy migration to PostgreSQL later.
- Avoids coupling scheduled jobs to the web API process.
- Keeps the decision ledger separate from RAG and JSONL events.

The first production-like milestone should be:

```text
Every trading day:
  before 09:15 -> one persisted recommendation or no_trade
  after 09:30  -> one persisted settlement for yesterday if eligible
  after settlement -> one auditable learning decision, with rollbackable version
```
