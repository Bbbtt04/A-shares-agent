# Premarket Crawler MCP Monorepo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable monorepo slice for extracting premarket crawler providers into an MCP-capable package.

**Architecture:** Add `packages/premarket-contracts` for shared Pydantic contracts and `packages/premarket-crawler-mcp` for provider registry, crawler service, and MCP tools. The host app keeps `trading_agent_system` in place and consumes the crawler through a provider adapter so RAG, knowledge indexing, reports, and debug APIs continue to work.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, setuptools editable install, MCP Python SDK through `mcp>=1.27,<2`.

---

### Task 1: Shared Contracts Package

**Files:**
- Create: `packages/premarket-contracts/pyproject.toml`
- Create: `packages/premarket-contracts/premarket_contracts/__init__.py`
- Create: `packages/premarket-contracts/premarket_contracts/schemas.py`
- Modify: `pyproject.toml`
- Test: `tests/premarket_mcp/test_contracts.py`

- [ ] **Step 1: Write the failing contract tests**

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import (
    CrawlerProviderResultContract,
    FetchWindowContract,
    PremarketNewsItemContract,
)


def test_fetch_window_filters_items_by_china_time_window():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    inside = PremarketNewsItemContract(
        source="同花顺7x24",
        source_tier="professional",
        title="窗口内新闻",
        published_at=datetime(2026, 6, 15, 8, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    outside = PremarketNewsItemContract(
        source="同花顺7x24",
        source_tier="professional",
        title="窗口外新闻",
        published_at=datetime(2026, 6, 15, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert window.filter_items([inside, outside]) == [inside]


def test_provider_result_builds_source_status():
    result = CrawlerProviderResultContract(
        source="同花顺7x24",
        provider_name="tonghuashun",
        items=[
            PremarketNewsItemContract(
                source="同花顺7x24",
                source_tier="professional",
                title="新闻",
            )
        ],
    )

    status = result.source_status(used_count=1)

    assert status.source == "同花顺7x24"
    assert status.provider_name == "tonghuashun"
    assert status.fetched_count == 1
    assert status.used_count == 1
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_contracts.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'premarket_contracts'`.

- [ ] **Step 3: Implement the contracts package**

Create `pyproject.toml` package discovery for the new package and implement Pydantic contracts with `contains()` and `filter_items()` on `FetchWindowContract`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_contracts.py -q`

Expected: PASS.

### Task 2: Crawler MCP Package Registry And Service

**Files:**
- Create: `packages/premarket-crawler-mcp/pyproject.toml`
- Create: `packages/premarket-crawler-mcp/premarket_crawler_mcp/__init__.py`
- Create: `packages/premarket-crawler-mcp/premarket_crawler_mcp/providers/news.py`
- Create: `packages/premarket-crawler-mcp/premarket_crawler_mcp/registry.py`
- Create: `packages/premarket-crawler-mcp/premarket_crawler_mcp/service.py`
- Modify: `pyproject.toml`
- Test: `tests/premarket_mcp/test_crawler_service.py`

- [ ] **Step 1: Write the failing crawler service tests**

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import FetchWindowContract, PremarketNewsItemContract
from premarket_crawler_mcp.service import PremarketCrawlerService


class StaticProvider:
    source = "测试源"
    provider_name = "static"

    def fetch(self, limit=30, window=None):
        from premarket_contracts import CrawlerProviderResultContract

        return CrawlerProviderResultContract(
            source=self.source,
            provider_name=self.provider_name,
            items=[
                PremarketNewsItemContract(
                    source=self.source,
                    source_tier="professional",
                    title="窗口内",
                    published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )
            ][:limit],
        )


class FailingProvider:
    source = "失败源"
    provider_name = "failing"

    def fetch(self, limit=30, window=None):
        raise RuntimeError("boom")


def test_service_fetches_sources_and_keeps_failed_source_status():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    service = PremarketCrawlerService(provider_factories={"static": StaticProvider, "failing": FailingProvider})

    response = service.fetch_premarket_news(["static", "failing"], limit_per_source=10, window=window)

    assert response.status == "partial"
    assert [item.title for item in response.items] == ["窗口内"]
    assert [(status.provider_name, status.status) for status in response.source_status] == [
        ("static", "ok"),
        ("failing", "failed"),
    ]
    assert response.warnings == ["failing: boom"]
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_crawler_service.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'premarket_crawler_mcp'`.

- [ ] **Step 3: Implement registry and service**

Implement a registry with provider factories for all configured source names and a service that returns `CrawlerResponseContract`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_crawler_service.py -q`

Expected: PASS.

### Task 3: MCP Tool Layer

**Files:**
- Create: `packages/premarket-crawler-mcp/premarket_crawler_mcp/server.py`
- Test: `tests/premarket_mcp/test_mcp_tools.py`

- [ ] **Step 1: Write failing MCP tool tests**

```python
from premarket_crawler_mcp.server import health, list_sources


def test_health_tool_returns_service_identity():
    assert health()["service"] == "premarket-crawler-mcp"
    assert health()["status"] == "ok"


def test_list_sources_tool_exposes_tonghuashun():
    names = {source["name"] for source in list_sources()["sources"]}
    assert "tonghuashun" in names
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_mcp_tools.py -q`

Expected: FAIL because `premarket_crawler_mcp.server` does not exist.

- [ ] **Step 3: Implement server functions and optional FastMCP registration**

Expose plain Python functions for tests and register them with `FastMCP` when the MCP SDK is importable.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_mcp_tools.py -q`

Expected: PASS.

### Task 4: Host Adapter And Config

**Files:**
- Create: `trading_agent_system/agents/premarket_agent/crawler_adapter.py`
- Modify: `scripts/run_premarket_agent.py`
- Modify: `configs/app.yaml`
- Test: `tests/premarket_mcp/test_host_adapter.py`

- [ ] **Step 1: Write failing host adapter tests**

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from premarket_contracts import CrawlerResponseContract, FetchWindowContract, PremarketNewsItemContract
from trading_agent_system.agents.premarket_agent.crawler_adapter import LocalPremarketCrawlerProvider


class StaticCrawlerService:
    def fetch_premarket_news(self, sources, limit_per_source, window):
        return CrawlerResponseContract(
            status="ok",
            window=window,
            items=[
                PremarketNewsItemContract(
                    source="同花顺7x24",
                    provider_name="tonghuashun",
                    source_tier="professional",
                    title="适配器新闻",
                    published_at=datetime(2026, 6, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )
            ],
            source_status=[],
            warnings=[],
        )


def test_local_crawler_provider_maps_contract_items_to_host_news_items():
    window = FetchWindowContract(
        mode="premarket",
        trading_day=date(2026, 6, 15),
        previous_trading_day=date(2026, 6, 12),
        timezone="Asia/Shanghai",
        window_start=datetime(2026, 6, 12, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        window_end=datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    provider = LocalPremarketCrawlerProvider(service=StaticCrawlerService(), sources=["tonghuashun"])

    result = provider.fetch(limit=80, window=window)

    assert result.source == "premarket-crawler-mcp"
    assert result.items[0].title == "适配器新闻"
    assert result.items[0].provider_name == "tonghuashun"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_host_adapter.py -q`

Expected: FAIL because `crawler_adapter.py` does not exist.

- [ ] **Step 3: Implement host adapter and config construction**

Add `LocalPremarketCrawlerProvider` and change `scripts/run_premarket_agent.py` to build it when `premarket.crawler.mode` is `local` or `mcp`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_host_adapter.py -q`

Expected: PASS.

### Task 5: Verification And Commit

**Files:**
- Modify: `README.md`
- Verify all changed packages and host integration.

- [ ] **Step 1: Run focused tests**

Run: `.venv/bin/python -m pytest tests/premarket_mcp tests/premarket/test_premarket_integration.py tests/premarket/test_premarket_provider_config.py -q`

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run: `cd web && npm run build`

Expected: PASS.

- [ ] **Step 4: Run whitespace check**

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 5: Commit implementation**

```bash
git add pyproject.toml configs/app.yaml README.md packages tests scripts trading_agent_system
git commit -m "【AI】feat: add premarket crawler mcp monorepo packages"
```

### Task 6: Stdio MCP Host Client

**Files:**
- Modify: `trading_agent_system/agents/premarket_agent/crawler_adapter.py`
- Modify: `scripts/run_premarket_agent.py`
- Modify: `configs/app.yaml`
- Test: `tests/premarket_mcp/test_host_adapter.py`

- [ ] **Step 1: Write the failing MCP provider test**

```python
class FakeMcpToolClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.response


def test_mcp_crawler_provider_calls_fetch_tool_and_maps_response():
    response = CrawlerResponseContract(
        status="ok",
        window=window,
        items=[PremarketNewsItemContract(source="同花顺7x24", provider_name="tonghuashun", title="MCP新闻")],
        source_status=[],
    ).model_dump(mode="json")
    client = FakeMcpToolClient(response)
    provider = McpPremarketCrawlerProvider(client=client, sources=["tonghuashun"])

    result = provider.fetch(limit=80, window=window)

    assert client.calls[0][0] == "fetch_premarket_news"
    assert client.calls[0][1]["sources"] == ["tonghuashun"]
    assert result.items[0].title == "MCP新闻"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_host_adapter.py::test_mcp_crawler_provider_calls_fetch_tool_and_maps_response -q`

Expected: FAIL because `McpPremarketCrawlerProvider` does not exist.

- [ ] **Step 3: Implement MCP provider and stdio client**

Add `McpPremarketCrawlerProvider` and `StdioMcpToolClient`. `StdioMcpToolClient` uses `mcp.client.stdio.stdio_client`, `StdioServerParameters`, and `ClientSession.call_tool()`.

- [ ] **Step 4: Run the host adapter test and a real stdio smoke test**

Run: `.venv/bin/python -m pytest tests/premarket_mcp/test_host_adapter.py -q`

Expected: PASS.

Run a Python smoke script that instantiates `StdioMcpToolClient(command=".venv/bin/python", args=["-m", "premarket_crawler_mcp.server"])` and calls `health`.

Expected: `{"status": "ok", "service": "premarket-crawler-mcp", ...}`.
