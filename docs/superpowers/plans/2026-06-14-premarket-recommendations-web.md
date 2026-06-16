# Premarket Recommendations Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first risk-reward based premarket stock recommendation engine and display conservative, opportunity, and watch-mode recommendations in the Web dashboard.

**Architecture:** Reuse the existing premarket `watchlist` as the v1 candidate pool, compute deterministic risk-reward price plans and score breakdowns in a focused `PremarketRecommendationEngine`, attach the recommendation set to `PremarketReport`, and render it in `PremarketPanel`. The LLM remains out of the pricing path; this v1 is rule-based and debuggable.

**Tech Stack:** Python 3.11+, Pydantic schemas, existing `PremarketAgent`, pytest, React/Vite frontend tests.

---

### Task 1: Recommendation Schemas

**Files:**
- Modify: `trading_agent_system/schemas.py`
- Test: `tests/premarket/test_premarket_recommendation_engine.py`

- [ ] Add `PremarketPricePlan`, `PremarketRecommendation`, and `PremarketRecommendationSet` schema classes.
- [ ] Add `recommendations: PremarketRecommendationSet | None = None` to `PremarketReport`.
- [ ] Write tests that assert the engine output can be serialized through `PremarketReport.model_dump(mode="json")`.

### Task 2: Rule-Based Recommendation Engine

**Files:**
- Create: `trading_agent_system/agents/premarket_agent/recommendation_engine.py`
- Test: `tests/premarket/test_premarket_recommendation_engine.py`

- [ ] Write a failing test for a priced watchlist item producing a recommendation with entry range, stop loss, two targets, risk-reward ratios, expected R, and decision trace.
- [ ] Implement minimal deterministic price-plan and scoring logic.
- [ ] Write a failing test for mode classification into conservative, opportunity, and watch lists.
- [ ] Implement mode thresholds and stable sorting.

### Task 3: Agent Integration

**Files:**
- Modify: `trading_agent_system/agents/premarket_agent/agent.py`
- Test: `tests/premarket/test_a_stock_data_integration.py`

- [ ] Write a failing integration test that `PremarketAgent.run()` returns `report.recommendations`.
- [ ] Integrate `PremarketRecommendationEngine` after watchlist creation.
- [ ] Enrich quote-candidate watchlist plans with price fields by matching `AStockDataAdapter` candidates when available.

### Task 4: Web Rendering

**Files:**
- Modify: `web/src/main.jsx`
- Modify: `web/src/styles.css`
- Test: `tests/frontend/test_premarket_panel.py`

- [ ] Write a failing frontend source test asserting the premarket panel renders `今日荐股计划`, `稳健型`, `机会型`, and `观察型`.
- [ ] Render the three recommendation groups above the existing catalyst/watchlist/source columns.
- [ ] Show symbol, rating, entry range, stop loss, target prices, risk-reward ratio, expected R, and reason.

### Task 5: Verification

**Files:**
- No code changes.

- [ ] Run `pytest tests/premarket/test_premarket_recommendation_engine.py tests/premarket/test_a_stock_data_integration.py tests/frontend/test_premarket_panel.py -q`.
- [ ] Run `pytest -q`.
- [ ] Run `npm run build` in `web`.
- [ ] If browser tooling is available, validate the premarket panel visually; otherwise document the fallback reason.
