# 当前实现检查与功能拆分

本文档基于当前代码状态整理，目标是明确已经实现的能力、缺失待实现部分、需要调整的边界，以及后续可以独立推进的模块拆分。

## M0-M3 基建层执行状态（2026-06-14）

- 执行计划：`docs/superpowers/plans/2026-06-14-infrastructure-layer.md`。
- M0 公共契约与事件层：已新增 `core/contracts`，复用现有 `core/events` / `core/event_bus`。
- M1 数据源与数据治理层：已新增 `DataSourceRegistry`、`EntityResolver`、`DataQualityScorer`、`DataLineageRecord`。
- M2 LLM Gateway：已新增统一 `LLMGateway`、Prompt 模板、结构化输出校验、request cache、token/cost/失败审计。
- M3 Tool Registry 与沙盒：已新增 `ToolRegistry`、`ToolExecutor`、`PermissionProfile`、工具 rate limit、调用预算与工具调用审计。
- 本轮暂不进入：新闻 Agent、公告 Agent、盘前策略 Agent、盘中异动 Agent、状态仓库、编排层、API/Web 重构。

## 1. 当前代码已实现能力

### 1.1 盘前链路

当前盘前链路已经是仓库中最完整的部分。

已实现：

- 多源资讯 Provider：证监会、东方财富、新浪、财联社、开盘啦、雪球、同花顺、RSS、Demo Provider。
- 交易日历与盘前抓取窗口。
- 原始资讯抓取、窗口过滤、去重、简单实体识别与富化。
- 原始文档、标准事件、事件聚类。
- 主题候选、风险候选、情景计划。
- 盘前摘要、开盘雷达、盘前约束指令。
- 盘前报告 JSON 与 Markdown 输出。
- 盘前事件写入 JSONL 事件流。
- 盘前内容写入 SQLite 知识库。
- 盘前专用 RAG：本地 Qdrant、确定性 embedding、结构化/关键词/风险/组合/题材/时效/向量检索、RRF 融合、证据包与评估。

主要代码：

- `trading_agent_system/agents/premarket_agent/agent.py`
- `trading_agent_system/agents/premarket_agent/news_provider.py`
- `trading_agent_system/agents/premarket_agent/pipeline/`
- `trading_agent_system/agents/premarket_agent/builders/`
- `trading_agent_system/agents/premarket_agent/rag/`
- `scripts/run_premarket_agent.py`

### 1.2 盘中链路

当前盘中链路是规则与因子驱动的本地扫描器。

已实现：

- 盘中行情 bar ingest。
- intel brief ingest。
- 持仓与账户快照 ingest。
- 盘前上下文 ingest。
- 市场状态监控。
- 特征生成：短周期收益、量比、突破、近期情报、主题联动、盘前主题确认。
- 策略注册表接入。
- 信号生成。
- 交易意图规划。
- 盘前约束过滤。
- 盘中分析报告发布。
- 交易意图发布。

主要代码：

- `trading_agent_system/agents/intraday_agent/agent.py`
- `trading_agent_system/agents/intraday_agent/feature_builder.py`
- `trading_agent_system/agents/intraday_agent/signal_engine.py`
- `trading_agent_system/agents/intraday_agent/trade_planner.py`
- `trading_agent_system/agents/intraday_agent/analysis.py`
- `scripts/run_intraday_agent.py`

### 1.3 风控网关

当前风控是确定性规则服务，不调用 LLM，定位正确。

已实现检查项：

- 全局交易开关。
- Kill switch。
- 行情新鲜度。
- 策略允许列表。
- 标的允许列表。
- 盘前约束。
- 黑名单。
- 订单类型。
- 价格偏离。
- 一手数量。
- 现金检查。
- 单标的持仓限制。
- 总敞口限制。
- 日亏损限制。
- 下单频率。
- 重复意图。
- 未成交订单限制。
- 流动性检查。
- 人工审批检查。

主要代码：

- `trading_agent_system/core/risk_gateway/gateway.py`
- `trading_agent_system/core/risk_gateway/checks.py`
- `trading_agent_system/core/risk_gateway/state.py`
- `scripts/run_risk_gateway.py`

### 1.4 模拟交易

已实现：

- PaperBroker。
- 订单提交。
- 基于下一根 bar 的简单成交模型。
- 滑点和佣金。
- 订单过期。
- 持仓快照。
- 账户快照。
- 成交事件。

主要代码：

- `trading_agent_system/core/broker/paper_broker.py`
- `scripts/run_paper_broker.py`

### 1.5 盘后复盘

已实现：

- ReviewAgent 总入口。
- 数据集组装。
- PnL 归因。
- 执行质量评估。
- 信号质量评估。
- 情报质量评估。
- 风控复盘。
- 策略健康建议。
- 每日报告输出。

主要代码：

- `trading_agent_system/agents/review_agent/`
- `scripts/run_review_agent.py`

### 1.6 基建能力

已实现：

- Pydantic schema。
- 事件总线：内存事件总线与 JSONL 持久化事件总线。
- 事件 envelope。
- Audit ledger。
- SQLite 知识库。
- 轻量 RAG retriever。
- 盘前专用 Qdrant RAG。
- Trace logger。
- Metrics recorder。
- 配置加载。
- 策略注册表。
- 公开行情 Provider：东方财富、腾讯、新浪。
- FastAPI 控制台 API。
- React Web Console。

主要代码：

- `trading_agent_system/schemas.py`
- `trading_agent_system/core/event_bus/`
- `trading_agent_system/core/storage/`
- `trading_agent_system/core/audit/`
- `trading_agent_system/core/knowledge/`
- `trading_agent_system/core/observability/`
- `trading_agent_system/core/market_data/`
- `trading_agent_system/api/app.py`
- `web/src/`

## 2. 当前缺失待实现部分

### 2.1 LLM 网关缺失

目前没有统一 LLM Gateway。

缺失能力：

- 模型供应商统一适配。
- Prompt 模板管理。
- JSON schema 强校验。
- 成本、token、耗时统计。
- 请求缓存。
- 重试、超时、降级。
- 模型路由。
- 模型版本审计。

影响：

- 当前系统多数逻辑是规则驱动，还没有真正形成可控的 LLM Agent 调用基础。
- 后续如果直接在各 Agent 内调用模型，会导致成本、审计、权限和输出格式难以统一。

### 2.2 Tool Registry 与工具权限缺失

目前各模块直接调用 Provider、Store、EventBus，没有统一工具注册表。

缺失能力：

- 工具输入 schema。
- 工具输出 schema。
- 权限声明。
- 超时与重试配置。
- 频率限制。
- 可缓存声明。
- 失败 fallback。
- 工具调用审计。

影响：

- Agent 与工具耦合较强。
- 后续增加更多 Agent 时，工具复用、权限控制和可观测性会变散。

### 2.3 沙盒权限仍是局部实现

当前有一些安全边界，例如 IntradayAgent 限制 publish topic，RiskGateway 默认确定性规则，但还没有统一沙盒。

缺失能力：

- Agent permission profile。
- 数据读写权限控制。
- 工具级权限检查。
- 写入行为审计。
- 高危动作二次确认。
- per-agent 成本与调用预算。

### 2.4 数据治理层不足

当前有 Provider 与简单去重，但还没有独立数据治理层。

缺失能力：

- 统一数据源 registry。
- 股票代码、公司名称、简称、曾用名映射。
- 新闻、公告、行情时间对齐。
- 数据质量评分。
- 数据延迟监控。
- 数据血缘。
- 数据源健康状态。
- 数据源降级策略。

### 2.5 公告解读 Agent 缺失

当前盘前资讯链路可以处理“新闻类信息”，但公告没有成为独立 Agent。

缺失能力：

- 公告专用抓取。
- 公告类型识别。
- 关键字段抽取。
- 定期报告、减持、回购、重组、监管函等分类。
- 与历史公告和财务数据对比。
- 公告影响分级。

### 2.6 新闻情报 Agent 边界不清

当前新闻抓取、事件抽取、聚类、主题、风险都在 PremarketAgent 内部完成。

缺失能力：

- 独立新闻情报 Agent。
- 新闻事件库。
- 事件生命周期。
- 跨盘前、盘中复用的事件聚类。
- 事件可信度评级。

### 2.7 盘中实时数据链路不足

当前 IntradayAgent 使用手动 ingest 和 demo bars，缺少真实盘中流式任务。

缺失能力：

- 实时行情轮询或订阅。
- 异动触发器。
- 板块联动实时监控。
- 盘中新闻/公告增量监听。
- 盘中任务调度。
- 低延迟超时控制。

### 2.8 状态管理不够独立

当前状态散落在报告文件、事件 JSONL、内存对象、SQLite 知识库中。

缺失能力：

- 今日状态仓库。
- Watchlist 状态流转。
- 个股状态机。
- 盘前假设状态。
- 盘中提醒去重。
- 用户反馈记录。

### 2.9 编排层缺失

目前主要靠脚本串联和 API `run-all` 顺序执行。

缺失能力：

- 任务 DAG。
- 定时任务。
- 事件触发。
- 失败重试。
- 并发控制。
- 任务状态查询。
- 人工确认节点。

### 2.10 评测体系不足

当前测试覆盖不错，但偏工程单测和 API 行为测试，缺少业务评测。

缺失能力：

- 新闻事件聚类黄金样本。
- 公告抽取黄金样本。
- 盘中异动解释评测。
- RAG 证据充分性评测。
- 提醒命中率统计。
- 盘前观点验证率。
- 人工打分闭环。

## 3. 需要调整的部分

### 3.1 PremarketAgent 过重

当前 PremarketAgent 同时承担：

- 数据抓取。
- 数据过滤。
- 事件抽取。
- 事件聚类。
- 主题识别。
- 风险识别。
- RAG 索引。
- RAG 检索。
- 指令生成。
- 报告生成。
- 事件发布。

建议拆分为：

- NewsCollector。
- EventNormalizer。
- EventClusterService。
- ThemeRiskService。
- PremarketStrategyAgent。
- PremarketReportService。
- PremarketRAGIndexer。

### 3.2 IntelAgent 目前过薄

当前 IntelAgent 只是手工 publish brief 的壳。

建议调整为通用情报入口：

- 接收新闻事件、公告事件、研报事件、社媒事件。
- 做事件标准化。
- 输出统一 IntelBrief 或 IntelligenceEvent。
- 给盘前与盘中共用。

### 3.3 IntradayAgent 更像交易信号扫描器

当前 IntradayAgent 会生成 `trading.intents`，但我们新的业务目标更偏“股票情报 Agent”。

建议拆分：

- IntradayAnomalyDetector：发现异动。
- IntradayExplanationAgent：解释异动。
- IntradayAlertService：提醒分级与去重。
- TradeIntentPlanner：保留在模拟交易模块，不作为情报主链路默认输出。

### 3.4 RAG 有两套体系

当前有：

- `core/knowledge`：SQLite 轻量知识库。
- `premarket_agent/rag`：盘前专用 Qdrant RAG。

建议调整：

- 将通用知识模型沉到 `core/knowledge`。
- 将盘前 RAG 作为 domain adapter。
- 后续公告、个股画像、题材知识共用统一 Knowledge API。

### 3.5 Web API 职责偏混合

当前 API 同时负责：

- 运行脚本。
- 读取报告。
- 读取事件。
- 查询知识库。
- 拉行情。
- 拼 debug 视图。

建议后续拆成 router：

- run router。
- premarket router。
- intraday router。
- market router。
- observability router。
- risk router。
- knowledge router。

### 3.6 中文编码与文案需要统一

当前多个文件在 PowerShell 输出中出现乱码，说明历史文件可能存在编码或终端显示不一致问题。

建议：

- 所有源码与文档统一 UTF-8。
- API 返回文案集中到常量或前端展示层。
- 后端内部尽量用英文 reason code，前端负责中文展示。

## 4. 推荐模块拆分

### M0. 公共协议与事件层

目标：稳定所有模块之间的数据契约。

范围：

- Schema 整理。
- EventEnvelope。
- 事件主题命名规范。
- Agent 输出格式规范。
- 事实、推断、观点、风险字段规范。

建议目录：

- `trading_agent_system/core/contracts/`
- `trading_agent_system/core/events/`

可独立实现。

### M1. 数据源与数据治理层

目标：把数据接入从 Agent 中拆出来。

范围：

- DataSourceRegistry。
- 行情 Provider 管理。
- 新闻 Provider 管理。
- 公告 Provider 管理。
- 标的映射。
- 数据质量检查。
- 数据血缘记录。

建议目录：

- `trading_agent_system/core/data_sources/`
- `trading_agent_system/core/data_quality/`
- `trading_agent_system/core/entities/`

优先级：最高。

### M2. LLM Gateway

目标：统一所有模型调用。

范围：

- ModelClient。
- PromptTemplateRegistry。
- StructuredOutputValidator。
- CostTracker。
- Retry/timeout/fallback。
- MockLLMProvider 用于测试。

建议目录：

- `trading_agent_system/core/llm_gateway/`

优先级：最高。

### M3. Tool Registry 与沙盒

目标：让 Agent 通过受控工具访问外部能力。

范围：

- ToolDefinition。
- ToolRegistry。
- ToolExecutor。
- PermissionProfile。
- ToolCallLog。
- RateLimit 与 timeout。

建议目录：

- `trading_agent_system/core/tools/`
- `trading_agent_system/core/sandbox/`

优先级：最高。

### M4. 知识库统一层

目标：合并 SQLite 知识库与盘前 RAG 的边界。

范围：

- KnowledgeRecord 扩展。
- EvidenceRecord。
- RetrievalService。
- VectorStore 接口。
- SourceRank 与时效过滤。
- RAG 评估通用化。

建议目录：

- `trading_agent_system/core/knowledge/`

优先级：高。

### M5. 新闻情报 Agent

目标：把新闻抓取、事件抽取、聚类从 PremarketAgent 拆出。

范围：

- NewsCollector。
- NewsNormalizer。
- EventExtractor。
- EventClusterer。
- EventScorer。
- NewsIntelligenceAgent。

建议目录：

- `trading_agent_system/agents/news_agent/`

优先级：高。

### M6. 公告解读 Agent

目标：补齐 A 股关键情报来源。

范围：

- AnnouncementCollector。
- AnnouncementParser。
- AnnouncementTypeClassifier。
- KeyFieldExtractor。
- AnnouncementImpactScorer。
- AnnouncementAgent。

建议目录：

- `trading_agent_system/agents/announcement_agent/`

优先级：高。

### M7. 个股画像与题材模块

目标：提供跨盘前、盘中、复盘共用的公司与题材上下文。

范围：

- StockProfile。
- ThemeProfile。
- ConceptMapping。
- HistoricalBehavior。
- RiskTags。
- ThemeRegistry 扩展。

建议目录：

- `trading_agent_system/domain/stocks/`
- `trading_agent_system/domain/themes/`

优先级：中高。

### M8. 盘前策略 Agent 收敛

目标：让 PremarketAgent 专注策略判断，而不是底层数据处理。

范围：

- 读取新闻事件。
- 读取公告事件。
- 读取行情摘要。
- 读取知识证据。
- 生成盘前假设。
- 生成关注池、回避池、观察条件。

建议目录：

- `trading_agent_system/agents/premarket_strategy_agent/`

优先级：高。

### M9. 盘中异动解释 Agent

目标：从“交易意图扫描”转向“情报解释与提醒”。

范围：

- AnomalyDetector。
- IntradayContextBuilder。
- ExplanationAgent。
- AlertDeduper。
- AlertSeverityScorer。
- AlertPublisher。

建议目录：

- `trading_agent_system/agents/intraday_intel_agent/`

优先级：高。

### M10. 状态仓库

目标：统一今日状态和用户反馈。

范围：

- TodayStateStore。
- WatchlistStateStore。
- HypothesisStore。
- AlertStore。
- UserFeedbackStore。

建议目录：

- `trading_agent_system/core/state_store/`

优先级：中高。

### M11. 任务编排层

目标：替代脚本手工串联。

范围：

- JobDefinition。
- JobRunner。
- Schedule。
- EventTrigger。
- RetryPolicy。
- JobStatus。

建议目录：

- `trading_agent_system/core/orchestration/`

优先级：中。

### M12. 评测与复盘闭环

目标：让系统质量可量化。

范围：

- GoldenDataset。
- NewsEval。
- AnnouncementEval。
- RAGEval。
- IntradayAlertEval。
- PremarketHypothesisEval。
- HumanFeedbackEval。

建议目录：

- `trading_agent_system/evaluation/`

优先级：中。

### M13. API 与 Web Console 拆分

目标：让产品入口清晰稳定。

范围：

- API router 拆分。
- 前端页面按盘前、盘中、复盘、知识库、观测拆分。
- 中文展示文案前端化。
- Debug 页面保留但与生产页面分离。

建议目录：

- `trading_agent_system/api/routers/`
- `web/src/pages/`
- `web/src/components/`

优先级：中。

## 5. 推荐实施顺序

建议按以下顺序推进：

1. M0 公共协议与事件层。
2. M1 数据源与数据治理层。
3. M2 LLM Gateway。
4. M3 Tool Registry 与沙盒。
5. M5 新闻情报 Agent 拆分。
6. M6 公告解读 Agent。
7. M8 盘前策略 Agent 收敛。
8. M9 盘中异动解释 Agent。
9. M10 状态仓库。
10. M4 知识库统一层。
11. M11 任务编排层。
12. M12 评测与复盘闭环。
13. M13 API 与 Web Console 拆分。

其中 M0-M3 是基础设施前置模块，建议先做；M5-M9 是业务价值模块，建议紧跟；M10-M13 是规模化与产品化模块，可以边跑边补。

## 6. 当前测试状态

当前测试结果：

```text
70 passed
```

测试覆盖范围包括：

- 前端信息架构。
- 盘前 Provider、事件聚类、盘前上下文、交易日历。
- 盘前 RAG。
- 盘中分析与主题联动。
- 风控盘前约束。
- 知识库。
- 事件总线。
- 观测 API。

后续新增模块时，建议每个模块都配套：

- schema 单测。
- 工具/服务单测。
- Agent 输出结构测试。
- 至少一个端到端 smoke test。
