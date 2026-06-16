# Infrastructure Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the first infrastructure layer before any new business agents: public contracts/events, data governance, LLM Gateway, Tool Registry, sandbox permissions, and audit/metrics hooks.

**Architecture:** Keep business agents unchanged. Add focused core modules under `trading_agent_system/core/` and prove them with isolated unit tests in `tests/infrastructure/`. Existing `EventEnvelope`, `AuditLedger`, `TraceLogger`, and `MetricsRecorder` are reused instead of duplicated.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, existing JSONL audit/metrics/event infrastructure.

---

## Scope From Architecture Docs

Authoritative source: `docs/architecture/implementation-breakdown.md`, section M0-M3.

In scope for this pass:

- M0 public contracts and event topic conventions.
- M1 data source registry, entity mapping, data quality, lineage and source health.
- M2 LLM Gateway with model client abstraction, prompt templates, structured output validation, retry/fallback, cost and audit records.
- M3 Tool Registry plus sandbox permission profiles, tool execution audit, timeout/retry, rate limit and fallback.
- Plan/status documentation updates.

Out of scope for this pass:

- News intelligence agent.
- Announcement agent.
- Premarket strategy agent refactor.
- Intraday anomaly/explanation agent.
- State store, orchestration, evaluation, API/Web refactors.

## File Structure

- Create `trading_agent_system/core/contracts/`
  Public agent output contracts and evidence/conclusion schemas.
- Create `trading_agent_system/core/data_sources/`
  Source registration, provider health, source fallback metadata.
- Create `trading_agent_system/core/data_quality/`
  Data quality scoring and lineage records.
- Create `trading_agent_system/core/entities/`
  Symbol/name alias resolver for A-share entities.
- Create `trading_agent_system/core/llm_gateway/`
  Model request/response contracts, prompt registry, structured validator, gateway orchestration and mock model client.
- Create `trading_agent_system/core/sandbox/`
  Permission enum/profile and per-agent budget checks.
- Create `trading_agent_system/core/tools/`
  Tool definitions, registry, executor, call logs, rate limiter and fallback handling.
- Create `tests/infrastructure/`
  Focused unit tests for each infrastructure capability.
- Modify `docs/architecture/implementation-breakdown.md`
  Record execution status for M0-M3.

---

### Task 1: Public Contracts

**Files:**
- Create: `trading_agent_system/core/contracts/__init__.py`
- Create: `trading_agent_system/core/contracts/outputs.py`
- Test: `tests/infrastructure/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
from trading_agent_system.core.contracts import (
    AgentConclusion,
    AgentOutputEnvelope,
    EvidenceReference,
)


def test_agent_output_separates_facts_inferences_views_and_risks():
    output = AgentOutputEnvelope(
        agent="premarket_strategy",
        run_id="run_1",
        conclusions=[
            AgentConclusion(
                kind="fact",
                statement="Policy support was published before market open.",
                evidence=[EvidenceReference(evidence_id="ev_1", source="cs.com.cn")],
                confidence=0.9,
            ),
            AgentConclusion(
                kind="risk",
                statement="The theme may fail if volume does not confirm.",
                confidence=0.6,
            ),
        ],
    )

    assert output.agent == "premarket_strategy"
    assert output.conclusions[0].kind == "fact"
    assert output.conclusions[0].evidence[0].evidence_id == "ev_1"
    assert output.conclusions[1].evidence == []
```

- [ ] **Step 2: Run test to verify RED**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_contracts.py -q`

Expected: FAIL because `trading_agent_system.core.contracts` does not exist.

- [ ] **Step 3: Implement minimal contracts**

Implement Pydantic models:

```python
ConclusionKind = Literal["fact", "inference", "view", "risk"]

class EvidenceReference(StrictBaseModel):
    evidence_id: str
    source: str | None = None
    citation_label: str | None = None

class AgentConclusion(StrictBaseModel):
    kind: ConclusionKind
    statement: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)

class AgentOutputEnvelope(StrictBaseModel):
    output_id: str = Field(default_factory=lambda: make_id("agent_output"))
    agent: str
    run_id: str | None = None
    conclusions: list[AgentConclusion] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_contracts.py -q`

Expected: PASS.

---

### Task 2: Data Governance Layer

**Files:**
- Create: `trading_agent_system/core/data_sources/__init__.py`
- Create: `trading_agent_system/core/data_sources/registry.py`
- Create: `trading_agent_system/core/data_quality/__init__.py`
- Create: `trading_agent_system/core/data_quality/scoring.py`
- Create: `trading_agent_system/core/entities/__init__.py`
- Create: `trading_agent_system/core/entities/resolver.py`
- Test: `tests/infrastructure/test_data_governance.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timezone

from trading_agent_system.core.data_quality import DataQualityCheck, DataQualityScorer
from trading_agent_system.core.data_sources import DataSourceRegistry, SourceKind
from trading_agent_system.core.entities import EntityResolver, SecurityEntity


def test_data_source_registry_tracks_health_and_fallback_order():
    registry = DataSourceRegistry()
    registry.register("eastmoney", kind=SourceKind.MARKET, priority=10)
    registry.register("tencent", kind=SourceKind.MARKET, priority=20)
    registry.mark_failure("eastmoney", "timeout")

    candidates = registry.candidates(SourceKind.MARKET)

    assert [item.source_id for item in candidates] == ["tencent", "eastmoney"]
    assert candidates[1].health.status == "degraded"
    assert candidates[1].health.last_error == "timeout"


def test_entity_resolver_normalizes_symbol_and_aliases():
    resolver = EntityResolver()
    resolver.add(SecurityEntity(symbol="510300.SH", name="沪深300ETF", aliases=["300ETF"]))

    assert resolver.resolve("510300") == "510300.SH"
    assert resolver.resolve("300ETF") == "510300.SH"
    assert resolver.resolve("沪深300ETF") == "510300.SH"


def test_data_quality_score_penalizes_stale_and_missing_fields():
    scorer = DataQualityScorer(required_fields=["symbol", "price"])
    result = scorer.score(
        {"symbol": "510300.SH", "price": None},
        checks=[
            DataQualityCheck(name="freshness", passed=False, severity="warning", reason="stale"),
            DataQualityCheck(name="source", passed=True, severity="info"),
        ],
        observed_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
    )

    assert result.score < 1
    assert "price" in result.missing_fields
    assert result.checks[0].reason == "stale"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_data_governance.py -q`

Expected: FAIL because the three packages do not exist.

- [ ] **Step 3: Implement minimal governance models**

Implement:

- `SourceKind`: `market`, `news`, `announcement`, `knowledge`, `storage`.
- `SourceHealth`: `status`, `last_error`, `success_count`, `failure_count`, `last_checked_at`.
- `DataSourceRegistry.register()`, `.mark_success()`, `.mark_failure()`, `.candidates(kind)`.
- `SecurityEntity` and `EntityResolver.add()/resolve()` with symbol prefix matching for `510300 -> 510300.SH`.
- `DataQualityCheck`, `DataQualityResult`, `DataQualityScorer.score()` with deterministic penalties.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_data_governance.py -q`

Expected: PASS.

---

### Task 3: LLM Gateway

**Files:**
- Create: `trading_agent_system/core/llm_gateway/__init__.py`
- Create: `trading_agent_system/core/llm_gateway/schemas.py`
- Create: `trading_agent_system/core/llm_gateway/prompts.py`
- Create: `trading_agent_system/core/llm_gateway/validation.py`
- Create: `trading_agent_system/core/llm_gateway/gateway.py`
- Test: `tests/infrastructure/test_llm_gateway.py`

- [ ] **Step 1: Write failing tests**

```python
from trading_agent_system.core.llm_gateway import (
    LLMGateway,
    ModelMessage,
    ModelRequest,
    MockModelClient,
    PromptTemplateRegistry,
    StructuredOutputValidator,
)


def test_prompt_template_renders_required_variables():
    registry = PromptTemplateRegistry()
    registry.register("summary", "Summarize {symbol} with {tone}.")

    assert registry.render("summary", symbol="510300.SH", tone="caution") == "Summarize 510300.SH with caution."


def test_gateway_validates_structured_output_and_records_usage(tmp_path):
    client = MockModelClient(
        outputs=[{"content": '{"symbol":"510300.SH","score":0.8}', "input_tokens": 4, "output_tokens": 8}]
    )
    gateway = LLMGateway(
        clients={"mock": client},
        audit_path=tmp_path / "llm_audit.jsonl",
    )
    request = ModelRequest(
        task_type="summary",
        messages=[ModelMessage(role="user", content="score 510300")],
        response_schema={"required": ["symbol", "score"]},
    )

    response = gateway.complete(request)

    assert response.provider == "mock"
    assert response.structured_output == {"symbol": "510300.SH", "score": 0.8}
    assert response.usage.total_tokens == 12
    assert gateway.audit.records[0]["event_type"] == "llm.call"


def test_gateway_falls_back_when_primary_fails(tmp_path):
    primary = MockModelClient(errors=[TimeoutError("slow")])
    fallback = MockModelClient(outputs=[{"content": '{"ok": true}'}])
    gateway = LLMGateway(
        clients={"primary": primary, "fallback": fallback},
        route_order=["primary", "fallback"],
        audit_path=tmp_path / "llm_audit.jsonl",
    )

    response = gateway.complete(ModelRequest(messages=[ModelMessage(role="user", content="ping")]))

    assert response.provider == "fallback"
    assert response.structured_output == {"ok": True}
```

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_llm_gateway.py -q`

Expected: FAIL because `core.llm_gateway` does not exist.

- [ ] **Step 3: Implement minimal gateway**

Implement:

- `ModelMessage`, `TokenUsage`, `ModelRequest`, `ModelResponse`.
- `ModelClient` protocol with `complete(request)`.
- `MockModelClient` for deterministic tests.
- `PromptTemplateRegistry.register()/render()` with missing variable errors.
- `StructuredOutputValidator.validate(content, schema)` using `json.loads()` plus required-field checks.
- `LLMGateway.complete()` route order, retry once per client, fallback to next client, elapsed time, audit record `llm.call`, and token/cost usage.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_llm_gateway.py -q`

Expected: PASS.

---

### Task 4: Tool Registry And Sandbox

**Files:**
- Create: `trading_agent_system/core/sandbox/__init__.py`
- Create: `trading_agent_system/core/sandbox/permissions.py`
- Create: `trading_agent_system/core/tools/__init__.py`
- Create: `trading_agent_system/core/tools/registry.py`
- Create: `trading_agent_system/core/tools/executor.py`
- Test: `tests/infrastructure/test_tool_registry_sandbox.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest

from trading_agent_system.core.sandbox import Permission, PermissionProfile
from trading_agent_system.core.tools import (
    ToolDefinition,
    ToolExecutor,
    ToolPermissionError,
    ToolRegistry,
)


def test_tool_executor_denies_missing_permission(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write_agent_event",
            required_permissions={Permission.WRITE_STATE},
            handler=lambda payload: {"ok": True},
        )
    )
    executor = ToolExecutor(registry, audit_path=tmp_path / "tool_audit.jsonl")

    with pytest.raises(ToolPermissionError):
        executor.call("write_agent_event", {}, PermissionProfile.reader("analyst"))


def test_tool_executor_validates_input_and_audits_success(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_market_snapshot",
            required_permissions={Permission.READ_MARKET},
            input_schema={"required": ["symbol"]},
            output_schema={"required": ["symbol", "price"]},
            handler=lambda payload: {"symbol": payload["symbol"], "price": 3.12},
        )
    )
    executor = ToolExecutor(registry, audit_path=tmp_path / "tool_audit.jsonl")

    result = executor.call("get_market_snapshot", {"symbol": "510300.SH"}, PermissionProfile.reader("premarket"))

    assert result.output == {"symbol": "510300.SH", "price": 3.12}
    assert result.status == "success"
    assert executor.audit.records[0]["event_type"] == "tool.call"


def test_tool_executor_uses_fallback_after_failure(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="search_news",
            required_permissions={Permission.READ_NEWS},
            handler=lambda payload: (_ for _ in ()).throw(RuntimeError("primary down")),
            fallback=lambda payload, error: {"items": [], "fallback_reason": str(error)},
        )
    )
    executor = ToolExecutor(registry, audit_path=tmp_path / "tool_audit.jsonl")

    result = executor.call("search_news", {}, PermissionProfile.reader("news_agent"))

    assert result.status == "fallback"
    assert result.output["fallback_reason"] == "primary down"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_tool_registry_sandbox.py -q`

Expected: FAIL because `core.sandbox` and `core.tools` do not exist.

- [ ] **Step 3: Implement minimal sandbox and tool execution**

Implement:

- `Permission` enum: `READ_MARKET`, `READ_NEWS`, `READ_ANNOUNCEMENTS`, `READ_KNOWLEDGE`, `CALL_LLM`, `WRITE_STATE`, `SEND_ALERT`.
- `PermissionProfile` with static constructors `reader(agent)` and `analyst(agent)`.
- `ToolDefinition`: name, description, handler, required permissions, input/output schema, timeout, retries, cacheable, fallback.
- `ToolRegistry.register()/get()/list()`.
- `ToolExecutor.call()` permission check, required field validation, retries, fallback, audit event, elapsed time, and structured `ToolCallResult`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_tool_registry_sandbox.py -q`

Expected: PASS.

---

### Task 5: Integration Exports And Plan Status

**Files:**
- Modify: `docs/architecture/implementation-breakdown.md`
- Test: `tests/infrastructure/test_infrastructure_exports.py`

- [ ] **Step 1: Write failing export/status tests**

```python
from pathlib import Path


def test_infrastructure_packages_are_importable():
    import trading_agent_system.core.contracts as contracts
    import trading_agent_system.core.data_sources as data_sources
    import trading_agent_system.core.llm_gateway as llm_gateway
    import trading_agent_system.core.sandbox as sandbox
    import trading_agent_system.core.tools as tools

    assert contracts.AgentOutputEnvelope
    assert data_sources.DataSourceRegistry
    assert llm_gateway.LLMGateway
    assert sandbox.PermissionProfile
    assert tools.ToolExecutor


def test_implementation_plan_marks_m0_m3_in_progress_or_done():
    doc = Path("docs/architecture/implementation-breakdown.md").read_text(encoding="utf-8")

    assert "M0-M3 基建层执行状态" in doc
    assert "LLM Gateway" in doc
    assert "Tool Registry" in doc
    assert "DataSourceRegistry" in doc
```

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_infrastructure_exports.py -q`

Expected before Task 1-4: FAIL because packages/status are missing. Expected after Task 1-4 but before docs update: only docs assertion fails.

- [ ] **Step 3: Update package exports and docs**

Ensure every new package exports its public models from `__init__.py`. Add a dated M0-M3 status block near the top of `docs/architecture/implementation-breakdown.md`:

```markdown
## M0-M3 基建层执行状态（2026-06-14）

- M0 公共契约与事件层：已新增 `core/contracts`，复用 `core/events`。
- M1 数据源与数据治理层：已新增 `DataSourceRegistry`、`EntityResolver`、`DataQualityScorer`。
- M2 LLM Gateway：已新增统一 `LLMGateway`、Prompt 模板、结构化输出校验、审计记录。
- M3 Tool Registry 与沙盒：已新增 `ToolRegistry`、`ToolExecutor`、`PermissionProfile` 与工具调用审计。
- 未进入本轮：新闻 Agent、公告 Agent、盘前策略 Agent、盘中异动 Agent、状态仓库、编排层。
```

- [ ] **Step 4: Run infrastructure and full tests**

Run:

```powershell
C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest tests/infrastructure -q
C:\Users\admin\Documents\agu\A-shares-agent\.venv\Scripts\python.exe -m pytest
```

Expected: all infrastructure tests and the full existing suite pass.

---

## Completion Audit

The goal is complete only when current evidence proves all of the following:

- `docs/superpowers/plans/2026-06-14-infrastructure-layer.md` exists and matches M0-M3.
- Each infrastructure ability was implemented in its own sub-window/sub-agent or clearly isolated task.
- M0 public contracts exist and are tested.
- M1 data governance registry/entity/quality modules exist and are tested.
- M2 LLM Gateway exists and is tested for prompt render, structured validation, fallback, usage and audit.
- M3 Tool Registry and Sandbox exist and are tested for permission denial, validation, fallback and audit.
- `docs/architecture/implementation-breakdown.md` has an M0-M3 status block.
- `pytest tests/infrastructure -q` passes.
- Full `pytest` passes.
