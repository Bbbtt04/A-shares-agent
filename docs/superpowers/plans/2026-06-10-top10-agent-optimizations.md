# Top 10 Agent Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first high-value optimization tranche for the A-share agent: premarket constraints flow into intraday decisions, risk can block or require approval, and the React console can inspect decision evidence and RAG context.

**Architecture:** Keep the MVP local-first and dependency-light. Premarket outputs become typed constraints and theme mappings; IntradayAgent consumes those constraints when creating intents; RiskGateway enforces them; observability and RAG APIs expose traceable evidence to the dashboard.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, JSONL/SQLite persistence, React/Vite.

---

## Priority Assessment

The top 10 tasks are ranked by immediate trading-assistant value and implementation risk:

1. **Premarket constraints into intraday**: prevents盘前 avoid/confirmation rules from being lost after the report is generated.
2. **Evidence-rich trade intents**: every intent must carry premarket/intraday reasons and evidence IDs for review.
3. **Risk check for premarket constraints**: risk gateway must reject blocked symbols and require approval when confidence is insufficient.
4. **Human approval queue**: decisions needing manual review should be queryable from the UI/API.
5. **Opening radar confirmation model**: expose 09:20-09:25 confirmation/rejection state, even with demo/partial data.
6. **Stock/theme mapping registry**: provide a maintainable local mapping for themes, symbols, and aliases.
7. **Intraday sector linkage scoring**: add theme/sector strength into feature snapshots and signal reasons.
8. **Decision trace detail API**: let the user inspect why an intent or risk decision happened.
9. **RAG debugger API**: show retrieved records, filters, and source quality for a query.
10. **Dashboard integration**: surface constraints, approval queue, radar, sector linkage, trace, and RAG debugger.

## File Map

- Create `trading_agent_system/core/premarket/context.py`: typed loader/extractor for latest premarket report constraints, radar, and theme context.
- Create `trading_agent_system/core/premarket/__init__.py`: export context helpers.
- Create `trading_agent_system/core/reference/theme_registry.py`: local stock/theme alias registry and scoring helpers.
- Modify `trading_agent_system/schemas.py`: add decision/evidence metadata models if needed without breaking existing payloads.
- Modify `trading_agent_system/agents/intraday_agent/agent.py`: accept optional premarket context, inject it into feature/signal/intent flow.
- Modify `trading_agent_system/agents/intraday_agent/feature_builder.py`: add theme and sector linkage features.
- Modify `trading_agent_system/agents/intraday_agent/signal_engine.py`: keep strategy behavior but add contextual reasons through candidate metadata path.
- Modify `trading_agent_system/agents/intraday_agent/trade_planner.py`: enrich `TradeIntent.metadata` with premarket constraints and evidence.
- Modify `trading_agent_system/core/risk_gateway/state.py`: store premarket constraints and approval queue.
- Modify `trading_agent_system/core/risk_gateway/checks.py`: add `PremarketConstraintCheck`.
- Modify `trading_agent_system/core/risk_gateway/gateway.py`: publish approval queue events for manual review decisions.
- Modify `trading_agent_system/api/app.py`: add endpoints for premarket context, approval queue, decision traces, and RAG debug.
- Modify `scripts/run_intraday_agent.py` and `scripts/run_risk_gateway.py`: wire demo flows to context and approval queue.
- Modify `web/src/api.js`, `web/src/main.jsx`, `web/src/styles.css`: add dashboard panels.
- Add focused tests under `tests/intraday`, `tests/risk`, and `tests/api` for the highest-risk behavior.

## Task 1: Premarket Context Loader

- [ ] Add failing tests for extracting watch/avoid/confirmation constraints from a report JSON payload.
- [ ] Implement `PremarketContext`, `PremarketConstraint`, and `PremarketContextLoader`.
- [ ] Verify with `pytest tests/premarket tests/intraday -q`.
- [ ] Commit as `feat: add premarket context loader`.

## Task 2: Intraday Agent Consumes Premarket Context

- [ ] Add failing tests that avoid symbols suppress buy intents and watch symbols enrich intent metadata.
- [ ] Wire optional context into `IntradayAgent`, `FeatureBuilder`, and `TradePlanner`.
- [ ] Verify with `pytest tests/intraday -q`.
- [ ] Commit as `feat: apply premarket context to intraday intents`.

## Task 3: Premarket Constraint Risk Check

- [ ] Add failing risk tests for `block`, `avoid_new_entry`, and `require_confirmation`.
- [ ] Implement `PremarketConstraintCheck` and add it before position sizing checks.
- [ ] Verify with `pytest tests/risk -q`.
- [ ] Commit as `feat: enforce premarket constraints in risk gateway`.

## Task 4: Human Approval Queue

- [ ] Add failing tests that manual-review decisions are stored and published.
- [ ] Add queue storage to `RiskGatewayState` and publish `risk.approval_queue`.
- [ ] Add `GET /api/risk/approval-queue`.
- [ ] Verify with `pytest tests/risk tests/observability -q`.
- [ ] Commit as `feat: add risk approval queue`.

## Task 5: Opening Radar Confirmation Model

- [ ] Add failing tests for radar-derived confirmed/failed/watch state.
- [ ] Implement context extraction for `opening_radar.confirmed_themes`, `failed_themes`, and watch items.
- [ ] Add `GET /api/premarket/context`.
- [ ] Verify with `pytest tests/premarket tests/observability -q`.
- [ ] Commit as `feat: expose opening radar context`.

## Task 6: Stock/Theme Registry

- [ ] Add failing tests for alias lookup and symbol-to-theme mapping.
- [ ] Implement static registry with A-share theme aliases.
- [ ] Wire registry into premarket enrichment and intraday feature building where possible.
- [ ] Verify with `pytest tests/premarket tests/intraday -q`.
- [ ] Commit as `feat: add theme registry`.

## Task 7: Intraday Sector Linkage Scoring

- [ ] Add failing tests for feature snapshot theme strength fields.
- [ ] Compute `theme_strength`, `theme_confirmation`, and related theme names from peer bars.
- [ ] Add reason text to candidate/intent metadata.
- [ ] Verify with `pytest tests/intraday -q`.
- [ ] Commit as `feat: add intraday sector linkage`.

## Task 8: Decision Trace Detail API

- [ ] Add failing API tests for intent/risk trace lookup by intent ID and run ID.
- [ ] Implement `GET /api/decisions/traces`.
- [ ] Pull from JSONL events and trace records; return compact timeline.
- [ ] Verify with `pytest tests/observability -q`.
- [ ] Commit as `feat: add decision trace api`.

## Task 9: RAG Debugger API

- [ ] Add failing API tests for query, filters, source ranks, and returned evidence.
- [ ] Implement `GET /api/rag/debug`.
- [ ] Include query, filters, result count, top records, themes, symbols, source rank.
- [ ] Verify with `pytest tests/knowledge tests/observability -q`.
- [ ] Commit as `feat: add rag debugger api`.

## Task 10: Dashboard Integration

- [ ] Add React API helpers for new endpoints.
- [ ] Add panels for premarket constraints, approval queue, decision trace, and RAG debug.
- [ ] Keep layout dense and operational; no marketing-style UI.
- [ ] Verify with `npm run build`.
- [ ] Commit as `feat: show agent optimization panels`.

## Final Verification

- [ ] Run `pytest tests -q`.
- [ ] Run `npm run build` in `web`.
- [ ] Run `scripts/run_premarket_agent.py --date 2026-06-10 --config configs/app.yaml --limit 5`.
- [ ] Run `scripts/run_intraday_agent.py --config configs/app.yaml --demo`.
- [ ] Run `scripts/run_risk_gateway.py --config configs/risk.paper.yaml --demo`.
- [ ] Push the branch after `git-guard pre-push`.
