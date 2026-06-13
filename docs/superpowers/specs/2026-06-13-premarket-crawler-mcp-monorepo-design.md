# Premarket Crawler MCP Monorepo Design

## Goal

将盘前爬虫能力从主业务 agent 中抽离为独立 MCP 服务，并把当前单体仓库改造成 monorepo 多包架构。第一阶段目标是形成清晰的包边界和可运行的 MCP contract，让 `PremarketAgent` 继续负责 RAG、知识库、盘前研判和下游约束，爬虫包只负责采集、标准化和来源状态。

## Current State

当前仓库是一个 Python 包加一个前端目录：

```text
trading_agent_system/
web/
configs/
scripts/
tests/
```

盘前爬虫集中在 `trading_agent_system/agents/premarket_agent/news_provider.py`。`scripts/run_premarket_agent.py` 根据 `configs/app.yaml` 的 `premarket.providers` 构造 provider，再把 provider 注入 `PremarketAgent`。`PremarketAgent` 负责调用 provider、过滤 fetch window、去重、RAG 入库、事件抽取、聚类、摘要、雷达和指令输出。

这个边界能跑通，但爬虫和主业务 agent 耦合太紧：

- `TradingCalendarService.build_fetch_window()` 运行时依赖 `news_provider.FetchWindow`。
- provider 类型和配置构造逻辑在主系统脚本里。
- 测试直接从主系统导入各个 provider。
- 前端调试链路看到的是 agent 事件，但无法区分本地 provider 和未来远端爬虫服务。

## Architecture Choice

采用 monorepo 多包架构作为第一阶段，而不是立即拆多个 GitHub 仓库。

推荐原因：

- 当前爬虫边界还在快速变化，monorepo 能减少跨仓版本同步和 PR 编排成本。
- MCP contract、主系统 adapter、测试 fixture 可以在一个提交链里一起演进。
- 目录边界稳定后，`packages/premarket-crawler-mcp` 可以平滑拆成独立仓库。

不采用立即真实多仓的原因：

- 需要同时维护多个仓库、多个 CI、多个版本号和跨仓 PR。
- 主仓当前还依赖未合入 `origin/main` 的多源爬虫变更，真实拆仓会放大基线同步成本。
- 第一阶段更重要的是先建立可靠 contract，而不是先优化仓库治理。

## Target Monorepo Layout

长期目标结构：

```text
agu_agent/
  apps/
    agent-api/
    web-console/
  packages/
    agent-core/
    premarket-contracts/
    premarket-crawler-mcp/
  configs/
  docs/
  tests/
```

第一阶段落地结构：

```text
agu_agent/
  packages/
    premarket-contracts/
      pyproject.toml
      premarket_contracts/
        __init__.py
        schemas.py
        windows.py
    premarket-crawler-mcp/
      pyproject.toml
      premarket_crawler_mcp/
        __init__.py
        providers/
        registry.py
        server.py
        service.py
  trading_agent_system/
  web/
  configs/
  scripts/
  tests/
```

`trading_agent_system` 和 `web` 第一阶段不搬到 `packages`/`apps`，只通过 adapter 接入新 MCP 包。这样能把风险控制在爬虫边界，不把前端、API、RAG 和风控一起迁移。

## Package Boundaries

### `packages/premarket-contracts`

共享 contract 包，负责 MCP 服务和主系统之间的稳定数据模型。

包含：

- `FetchWindowContract`
- `PremarketNewsItemContract`
- `PremarketSourceStatusContract`
- `CrawlerProviderResultContract`
- `CrawlerRequest`
- `CrawlerResponse`
- `SourceDescriptor`

这个包不依赖 `trading_agent_system`，也不依赖 MCP SDK。它只依赖 Python 标准库和 Pydantic。

### `packages/premarket-crawler-mcp`

独立盘前爬虫 MCP 包，负责外部来源采集和标准化。

包含：

- provider 实现：证监会、东方财富、新浪、同花顺、财联社、开盘啦、雪球、RSS、demo。
- provider registry：根据配置构造 provider。
- crawler service：统一执行 fetch、窗口过滤、状态汇总。
- MCP server：把 crawler service 暴露为 MCP tools。

这个包依赖 `premarket-contracts` 和 MCP Python SDK，不依赖 `trading_agent_system`。

### `trading_agent_system`

主业务系统保留 agent、RAG、知识库、API、风控和审计。

改动边界：

- 删除主脚本中直接构造具体爬虫 provider 的职责。
- 新增 `McpPremarketCrawlerProvider` adapter。
- `PremarketAgent` 继续消费 `NewsProviderResult` 或兼容 provider protocol。
- `TradingCalendarService` 只产出共享 contract 的 fetch window，避免反向依赖 provider 模块。

## MCP Tool Contract

第一阶段 MCP server 暴露四个 tools。

### `health`

输入：

```json
{}
```

输出：

```json
{
  "status": "ok",
  "service": "premarket-crawler-mcp",
  "version": "0.1.0"
}
```

### `list_sources`

输入：

```json
{}
```

输出：

```json
{
  "sources": [
    {
      "name": "tonghuashun",
      "display_name": "同花顺7x24",
      "layer": "finance_news",
      "tier": "professional",
      "enabled_by_default": true,
      "auth_required": false
    }
  ]
}
```

### `fetch_source_news`

输入：

```json
{
  "source": "tonghuashun",
  "limit": 80,
  "window": {
    "mode": "premarket",
    "trading_day": "2026-06-15",
    "previous_trading_day": "2026-06-12",
    "timezone": "Asia/Shanghai",
    "window_start": "2026-06-12T15:00:00+08:00",
    "window_end": "2026-06-15T09:30:00+08:00"
  }
}
```

输出：

```json
{
  "source": "同花顺7x24",
  "provider_name": "tonghuashun",
  "status": "ok",
  "fetched_count": 80,
  "used_count": 80,
  "error": null,
  "items": []
}
```

`items` 使用 `PremarketNewsItemContract` 列表。示例中留空仅表示结构位置，实际成功返回时必须包含抓取到的标准化新闻。

### `fetch_premarket_news`

输入：

```json
{
  "sources": ["csrc", "eastmoney", "sina_finance", "tonghuashun", "kaipanla", "xueqiu"],
  "limit_per_source": 80,
  "window": {
    "mode": "premarket",
    "trading_day": "2026-06-15",
    "previous_trading_day": "2026-06-12",
    "timezone": "Asia/Shanghai",
    "window_start": "2026-06-12T15:00:00+08:00",
    "window_end": "2026-06-15T09:30:00+08:00"
  }
}
```

输出：

```json
{
  "status": "ok",
  "window": {
    "mode": "premarket",
    "trading_day": "2026-06-15",
    "previous_trading_day": "2026-06-12",
    "timezone": "Asia/Shanghai",
    "window_start": "2026-06-12T15:00:00+08:00",
    "window_end": "2026-06-15T09:30:00+08:00"
  },
  "source_status": [],
  "items": [],
  "warnings": []
}
```

`status` 为 `ok`、`partial` 或 `failed`。只要至少一个 provider 成功返回数据，整体状态就是 `ok` 或 `partial`，不因为单个来源失败中断整轮盘前分析。

## Data Flow

第一阶段运行链路：

```text
configs/app.yaml
  -> scripts/run_premarket_agent.py
  -> TradingCalendarService.build_fetch_window()
  -> McpPremarketCrawlerProvider.fetch()
  -> premarket-crawler-mcp.fetch_premarket_news
  -> provider registry
  -> source providers
  -> CrawlerResponse
  -> adapter maps contracts to PremarketNewsItem / PremarketSourceStatus
  -> PremarketAgent existing pipeline
  -> KnowledgeStore / RAG / report / debug API
```

`PremarketAgent` 不知道具体来源是本地 provider 还是 MCP server。它只看到兼容的 `NewsProviderResult`。

## Configuration

`configs/app.yaml` 第一阶段新增 MCP 配置，并保留本地 fallback：

```yaml
premarket:
  crawler:
    mode: mcp
    transport: stdio
    command: python
    args:
      - -m
      - premarket_crawler_mcp.server
    fallback_to_local: true
  limit_per_source: 80
  providers:
    - csrc
    - eastmoney
    - sina_finance
    - sina_stock
    - sina_global
    - tonghuashun
    - cailianpress
    - kaipanla
    - xueqiu
```

`mode` 支持：

- `local`：使用包内本地 crawler service，不走 MCP transport，用于测试和无 MCP 运行环境。
- `mcp`：通过 MCP client 调用独立服务。
- `legacy`：临时回退到当前 `news_provider.py` provider 构造逻辑，迁移完成后删除。

## Migration Strategy

### Phase 1: Monorepo Skeleton And Contracts

新增 `packages/premarket-contracts` 和 `packages/premarket-crawler-mcp`。先把共享模型和 provider registry 建起来，并让测试能直接调用 crawler service。

### Phase 2: Provider Move

把 `news_provider.py` 中 provider 实现迁入 `packages/premarket-crawler-mcp/premarket_crawler_mcp/providers/`。主系统暂时保留兼容导入层，避免一次性修改所有测试。

### Phase 3: MCP Server And Host Adapter

实现 MCP tools 和 `McpPremarketCrawlerProvider`。`scripts/run_premarket_agent.py` 优先构造 MCP adapter，失败时按配置回退 local 或 legacy。

### Phase 4: Debug And Observability

盘前 debug API 继续展示 `premarket.crawled_documents` 和 `source_status`。新增 MCP metadata：

- `crawler_mode`
- `crawler_transport`
- `mcp_tool`
- `mcp_elapsed_ms`
- `source_provider_name`

### Phase 5: Cleanup

当 MCP adapter 和 crawler service 测试稳定后，移除主系统中的具体 provider 构造逻辑，只保留 adapter、contract mapper 和 demo provider。

## Error Handling

- MCP server 启动失败：如果 `fallback_to_local=true`，使用 local crawler service 并添加 warning；否则本轮盘前任务失败。
- 单个 provider 失败：返回对应 `PremarketSourceStatusContract(status="failed")`，不影响其他 provider。
- provider 返回页面壳或反爬错误：记录 `failed` 和错误详情，不做高频重试。
- MCP contract 校验失败：adapter 将该来源标记为 failed，并在 report warnings 中提示 schema mismatch。
- 所有 provider 失败：`PremarketAgent` 生成谨慎结论和人工确认约束，不生成积极催化。

## Testing

新增和迁移测试覆盖：

- contract schema round trip：datetime、date、source status、news item 能稳定 JSON 序列化和反序列化。
- crawler service：按 sources 配置调用 provider，单源失败不影响其他来源。
- provider registry：`csrc`、`eastmoney`、`sina_finance`、`sina_stock`、`sina_global`、`tonghuashun`、`cailianpress`、`kaipanla`、`xueqiu` 都能注册。
- MCP tools：`health`、`list_sources`、`fetch_source_news`、`fetch_premarket_news` 返回 contract JSON。
- host adapter：MCP response 能映射为 `NewsProviderResult` 和 `PremarketNewsItem`。
- integration：`PremarketAgent` 使用 MCP adapter 时仍产生 crawled documents、knowledge records、RAG evidence 和 report。
- fallback：MCP 不可用且 `fallback_to_local=true` 时仍能跑完整盘前流程。

现有测试范围继续保留：

- `tests/premarket`
- `tests/premarket_rag`
- `tests/frontend/test_premarket_debug_tab.py`
- `npm run build`

## Acceptance Criteria

1. 仓库中存在 `packages/premarket-contracts` 和 `packages/premarket-crawler-mcp`，并各自有独立 `pyproject.toml`。
2. 盘前爬虫 provider 不再只存在于 `trading_agent_system/agents/premarket_agent/news_provider.py`。
3. MCP 服务能通过 tool contract 返回来源列表、单源新闻和多源盘前新闻。
4. 主系统能通过 adapter 调用 MCP crawler，并继续生成原有 `PremarketReport`、RAG、知识库和 debug API 数据。
5. `PremarketAgent` 不直接依赖具体第三方爬虫 provider 类。
6. `TradingCalendarService` 不再从 provider 模块导入 `FetchWindow`。
7. 单个来源失败只影响该来源状态，不中断整轮盘前分析。
8. 第一阶段无需搬迁 `web` 到 `apps/web-console`，但设计和 README 明确 monorepo 目标结构。
9. 新增测试和现有后端、前端测试通过。

## Future Split To Real Multi-Repo

当 MCP 服务稳定后，可以把 `packages/premarket-crawler-mcp` 拆到独立仓库 `agu-premarket-crawler-mcp`。拆仓前必须满足：

- `premarket-crawler-mcp` 不从主仓导入任何 `trading_agent_system` 模块。
- 所有共享模型都来自 `premarket-contracts` 或已发布的 contract 包。
- 主仓只通过 MCP contract 和 adapter 消费爬虫结果。
- CI 能分别验证 crawler package 和 host adapter。

拆仓时，`premarket-contracts` 可以继续留在 monorepo，也可以独立发布为 `agu-premarket-contracts`。是否拆 contract 仓库取决于是否有第二个外部消费者。
