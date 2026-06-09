# Agent Observability and RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version production-style agent runtime layer with durable events, trace logging, lightweight RAG, observability APIs, and a React dashboard.

**Architecture:** Keep the project framework-light. Implement local equivalents of LangGraph-style checkpoints, Haystack-style explicit retrieval, and Langfuse/Phoenix-style traces using JSONL and SQLite so the system remains easy to inspect and can later migrate to external tools.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite, JSONL, FastAPI, React/Vite.

---

## File Structure

- Create `trading_agent_system/core/events/envelope.py`: typed event envelope used by all durable event records.
- Create `trading_agent_system/core/events/__init__.py`: exports event envelope helpers.
- Modify `trading_agent_system/core/event_bus/bus.py`: protocol accepts topic, event, metadata and returns an envelope.
- Modify `trading_agent_system/core/event_bus/memory_bus.py`: preserves in-memory behavior while storing envelopes.
- Create `trading_agent_system/core/event_bus/durable_bus.py`: publishes to memory and JSONL storage.
- Modify `trading_agent_system/core/event_bus/__init__.py`: exports durable bus.
- Modify `trading_agent_system/core/storage/repositories.py`: add envelope-oriented event loading and filtering.
- Create `trading_agent_system/core/observability/traces.py`: trace event model and step context manager.
- Create `trading_agent_system/core/observability/metrics.py`: JSONL metrics recorder.
- Create `trading_agent_system/core/observability/__init__.py`: exports observability helpers.
- Create `trading_agent_system/core/knowledge/schemas.py`: knowledge record and search result models.
- Create `trading_agent_system/core/knowledge/store.py`: SQLite/FTS-backed local knowledge store.
- Create `trading_agent_system/core/knowledge/indexer.py`: converts agent outputs into knowledge records.
- Create `trading_agent_system/core/knowledge/retriever.py`: metadata-aware search interface.
- Create `trading_agent_system/core/knowledge/__init__.py`: exports knowledge APIs.
- Modify `trading_agent_system/agents/premarket_agent/agent.py`: add optional runtime services and index/publish traceable outputs.
- Modify `scripts/run_premarket_agent.py`: instantiate durable event bus, trace logger, metrics recorder, and knowledge store.
- Modify `trading_agent_system/api/app.py`: add observability and knowledge endpoints.
- Modify `web/src/api.js`: add observability API calls.
- Modify `web/src/main.jsx`: add observability panels.
- Modify `web/src/styles.css`: style observability panels.
- Add tests under `tests/observability/` and `tests/knowledge/`.

## Task 1: Event Envelope and Durable Event Bus

**Files:**
- Create: `trading_agent_system/core/events/envelope.py`
- Create: `trading_agent_system/core/events/__init__.py`
- Modify: `trading_agent_system/core/event_bus/bus.py`
- Modify: `trading_agent_system/core/event_bus/memory_bus.py`
- Create: `trading_agent_system/core/event_bus/durable_bus.py`
- Modify: `trading_agent_system/core/storage/repositories.py`
- Test: `tests/observability/test_event_bus.py`

- [ ] Write failing tests for envelope creation, memory publishing, durable JSONL persistence, and topic filtering.
- [ ] Run `pytest tests/observability/test_event_bus.py -q` and verify failures are due to missing code.
- [ ] Implement `EventEnvelope`, `MemoryEventBus` metadata support, `DurableEventBus`, and repository filters.
- [ ] Run `pytest tests/observability/test_event_bus.py -q` and verify pass.

## Task 2: Trace Logger and Metrics

**Files:**
- Create: `trading_agent_system/core/observability/traces.py`
- Create: `trading_agent_system/core/observability/metrics.py`
- Create: `trading_agent_system/core/observability/__init__.py`
- Test: `tests/observability/test_traces_metrics.py`

- [ ] Write failing tests for trace step success, trace step failure, and metrics recording.
- [ ] Run `pytest tests/observability/test_traces_metrics.py -q` and verify failures are due to missing code.
- [ ] Implement `TraceLogger`, `TraceEvent`, `MetricsRecorder`, and JSONL readers.
- [ ] Run `pytest tests/observability/test_traces_metrics.py -q` and verify pass.

## Task 3: Knowledge Store and Retriever

**Files:**
- Create: `trading_agent_system/core/knowledge/schemas.py`
- Create: `trading_agent_system/core/knowledge/store.py`
- Create: `trading_agent_system/core/knowledge/retriever.py`
- Create: `trading_agent_system/core/knowledge/indexer.py`
- Create: `trading_agent_system/core/knowledge/__init__.py`
- Test: `tests/knowledge/test_knowledge_store.py`

- [ ] Write failing tests for indexing records, keyword search, trading-day filter, theme filter, and source-rank filter.
- [ ] Run `pytest tests/knowledge/test_knowledge_store.py -q` and verify failures are due to missing code.
- [ ] Implement SQLite tables, FTS fallback search, metadata filters, and result ordering.
- [ ] Run `pytest tests/knowledge/test_knowledge_store.py -q` and verify pass.

## Task 4: Premarket Agent Integration

**Files:**
- Modify: `trading_agent_system/agents/premarket_agent/agent.py`
- Modify: `scripts/run_premarket_agent.py`
- Test: `tests/premarket/test_premarket_integration.py`

- [ ] Extend integration test to verify durable event topics, traces, metrics, and knowledge records are produced.
- [ ] Run `pytest tests/premarket/test_premarket_integration.py -q` and verify failure before integration.
- [ ] Wire optional `trace_logger`, `metrics`, and `knowledge_indexer` into `PremarketAgent`.
- [ ] Instantiate durable bus and runtime services in `scripts/run_premarket_agent.py`.
- [ ] Run `pytest tests/premarket/test_premarket_integration.py -q` and verify pass.

## Task 5: Observability API

**Files:**
- Modify: `trading_agent_system/api/app.py`
- Test: `tests/observability/test_observability_api.py`

- [ ] Write failing API tests for `/api/observability/events`, `/api/observability/traces`, `/api/observability/metrics`, and `/api/observability/knowledge/search`.
- [ ] Run `pytest tests/observability/test_observability_api.py -q` and verify failure before API implementation.
- [ ] Implement endpoints using JSONL readers and `KnowledgeStore`.
- [ ] Run `pytest tests/observability/test_observability_api.py -q` and verify pass.

## Task 6: React Observability Dashboard

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/main.jsx`
- Modify: `web/src/styles.css`

- [ ] Add API client functions for observability endpoints.
- [ ] Add Event Stream, Trace Timeline, Metrics Summary, and Knowledge Search panels.
- [ ] Keep dashboard read-only; no trading action controls.
- [ ] Run `npm run build` in `web/` and verify pass.

## Task 7: End-to-End Verification

**Files:**
- No new files unless fixes are required.

- [ ] Run `.venv/bin/python -m pytest tests/premarket tests/observability tests/knowledge -q`.
- [ ] Run `.venv/bin/python scripts/run_premarket_agent.py --date 2026-06-10 --config configs/app.yaml --limit 8`.
- [ ] Run `npm run build` in `web/`.
- [ ] Confirm generated local data exists under `data/events`, `data/traces`, `data/metrics`, and `data/knowledge.sqlite`.
- [ ] Summarize verification output.

