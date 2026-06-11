# RAG Knowledge Optimization Design

## Goal

优化盘前 RAG 和知识库闭环，让 `PremarketAgent` 的证据包不仅包含当日热数据，还能引用规则、历史案例和人工反馈。第一阶段目标是提高证据可追溯性和反幻觉约束，不改变交易、风控、执行的核心行为。

## Current State

当前项目已有两套相关能力：

- `trading_agent_system/agents/premarket_agent/rag/`：负责 Qdrant local、确定性 embedding、混合检索、RRF 融合、去重、EvidencePack 和 RAG evaluation。
- `trading_agent_system/core/knowledge/`：负责 SQLite `KnowledgeStore`、`RagIndexer`、`RagRetriever`，已能存 raw document、event、event cluster、theme、decision、report 等结构化记录。

当前缺口：

- RAG evidence pack 和 `KnowledgeStore` 还是平行链路。
- 知识库没有 typed record type 表达规则、历史案例和人工反馈。
- RAG evaluation 主要看 evidence/citation 覆盖，没有统计规则/案例/反馈覆盖。
- 盘前报告没有展示“这条判断受哪些规则、历史案例或人工反馈约束”。

## Non-Goals

本阶段不做以下事情：

- 不新增三方信息源抓取。
- 不替换 Qdrant 或 embedding provider。
- 不引入 LLM 自动生成交易结论。
- 不让规则或案例直接改变买卖判断。
- 不新建第二套 `premarket_agent/knowledge` 包，避免和 `core/knowledge` 分裂。
- 不做数据库迁移框架；SQLite schema 只做向后兼容扩展。

## Recommended Approach

采用 `core/knowledge` 作为唯一知识库边界，扩展它支持知识型记录，并增加一个桥接层把知识检索结果转换成 RAG retrieval result。

### Approach A: KnowledgeStore Enhances RAG

这是推荐路径。

优点：

- 复用现有 SQLite store、API 和测试。
- 避免新增重复知识系统。
- 可以直接提升 EvidencePack 的规则/案例/反馈覆盖。
- 第一阶段只增强证据，不改变交易行为，风险较低。

代价：

- 需要扩展 `KnowledgeRecord.record_type` 和 RAG schemas。
- 需要给 EvidencePack 增加知识覆盖指标。

### Approach B: Add A Separate Premarket Knowledge Package

这个方案接近早先计划中的 `premarket_agent/knowledge` 包。

优点：

- 领域模型更贴近盘前业务。
- PlaybookRule、HistoricalCase、HumanFeedback 可以有专属 schema。

代价：

- 会形成第二套知识库边界。
- API、检索、UI 需要再次接入。
- 和现有 `core/knowledge` 的职责重叠。

### Approach C: Frontend-Only Knowledge Panel

优点：

- 可见效果最快。

代价：

- 后端证据闭环仍弱。
- 不能解决 RAG 幻觉和证据约束问题。

## Architecture

本阶段新增一个桥接层：

```text
KnowledgeStore
  -> KnowledgeRetriever
  -> KnowledgeEvidenceBridge
  -> RetrievalResult
  -> EvidencePackBuilder
  -> Premarket RAG Evidence Event
```

现有热数据链路保持不变：

```text
RawDocument / Event / EventCluster
  -> PreMarketRAGIndexingPipeline
  -> Qdrant + local document cache
  -> retrievers
  -> EvidencePackBuilder
```

最终 EvidencePack 同时包含两类证据：

- 当日热数据证据：公告、新闻、事件、聚类。
- 知识库证据：规则、历史案例、人工反馈。

## Data Model

扩展 `KnowledgeRecord.record_type`：

```text
playbook_rule
historical_case
human_feedback
```

这些类型仍使用现有 `KnowledgeRecord` 字段：

- `title`：规则名、案例标题、反馈摘要。
- `summary`：短说明。
- `content`：完整规则、案例复盘或反馈正文。
- `themes` / `symbols` / `event_ids` / `cluster_ids`：用于检索过滤。
- `metadata`：保存结构化细节，例如 rule priority、case market regime、feedback action。
- `confidence`：人工确认程度或适用强度。
- `source_rank`：默认 `internal`。

不新增独立 SQLite 表。原因是第一阶段主要做检索和 evidence enrichment，单表足够，测试成本低。

## Components

### KnowledgeEvidenceBridge

新增模块：

```text
trading_agent_system/agents/premarket_agent/rag/knowledge_bridge.py
```

责任：

- 接收 `KnowledgeSearchResult`。
- 转换为 `RetrievalResult`。
- 给 result 增加 metadata：
  - `knowledge_record_type`
  - `knowledge_record_id`
  - `knowledge_source_rank`
- 根据 record type 生成稳定 evidence id：
  - `rule_<record_id>`
  - `case_<record_id>`
  - `feedback_<record_id>`

### Knowledge-Aware RAG Service

扩展 `PreMarketRAGService`：

- 可选注入 `knowledge_retriever: RagRetriever | None`。
- `retrieve()` 保持当前行为。
- 新增 `retrieve_with_knowledge(task)` 或内部私有增强方法，用于在 evidence pack 构建前混入知识结果。
- 第一阶段每个 task 最多混入少量知识结果，避免规则/案例淹没热数据。

### EvidencePack Coverage

扩展 `EvidencePack.coverage`，新增：

- `knowledge_count`
- `playbook_rule_count`
- `historical_case_count`
- `human_feedback_count`
- `hot_evidence_count`

这些指标只进入 `coverage` dict，不改 Pydantic schema 字段，保持兼容。

### Seed Knowledge Records

新增小型 seed 数据文件：

```text
data/knowledge_seed/premarket_rules.json
data/knowledge_seed/historical_cases.json
```

新增 loader 或测试 helper 把 seed 转成 `KnowledgeRecord`。第一阶段不要求生产环境自动加载 seed，避免隐藏副作用。脚本接入可以作为实现计划中的后续 task。

## Data Flow

盘前运行时：

1. `PremarketAgent` 采集并归一化 raw documents/events/clusters。
2. `RagIndexer` 把结构化记录写入 `KnowledgeStore`。
3. `PreMarketRAGService` 把热数据写入 Qdrant local。
4. Query planner 生成 section tasks。
5. 每个 task 先跑现有 retrievers。
6. 如果配置了 `knowledge_retriever`，按 task query、theme、symbol、trading day 搜索知识库。
7. `KnowledgeEvidenceBridge` 把知识结果转成 `RetrievalResult`。
8. 热数据和知识结果一起进入 fusion/dedup/budget/evidence pack。
9. RAG evaluation 统计证据覆盖和知识覆盖。
10. 前端继续通过现有 `/api/premarket/rag/latest` 查看 evidence pack。

## Anti-Hallucination Controls

本阶段的反幻觉策略是证据约束，不是让模型自由生成结论：

- 知识结果必须来自 `KnowledgeStore`，每条有 `record_id`。
- Evidence item 必须有 `citation_label`。
- 低可信 source 不提升为强结论。
- `human_feedback` 只作为提醒和约束，不直接覆盖报告结论。
- RAG evaluation 暴露 `knowledge_count` 和 citation coverage，方便发现“没有证据的判断”。

## Error Handling

- `knowledge_retriever` 未配置：RAG 保持现有热数据行为。
- KnowledgeStore 空：EvidencePack 仍生成，`knowledge_count = 0`。
- 某条知识记录字段缺失：bridge 跳过不可转换记录，并在 coverage 中不计数。
- SQLite 查询失败：不让盘前 agent 整体失败，记录 warning/trace 后继续使用热数据证据。
- 重复知识记录：按 `record_id` 去重。

## Testing

使用 TDD 实现：

1. `tests/knowledge/test_knowledge_record_types.py`
   - 验证新 record type 可写入、检索、按 source_rank 和 record_type 过滤。
2. `tests/premarket_rag/test_knowledge_bridge.py`
   - 验证 KnowledgeSearchResult 能转换成 RetrievalResult，并保留 citation/evidence metadata。
3. `tests/premarket_rag/test_rag_service_knowledge_integration.py`
   - 验证 RAG pack 同时包含热数据和知识证据。
   - 验证 coverage 统计 knowledge/rule/case/feedback 数量。
4. 现有回归：
   - `tests/knowledge`
   - `tests/premarket_rag`
   - `tests/premarket`
   - 全量 pytest。

## Acceptance Criteria

1. `KnowledgeRecord` 支持 `playbook_rule`、`historical_case`、`human_feedback`。
2. RAG service 可选接入 `RagRetriever`，未接入时现有行为不变。
3. EvidencePack 能包含知识库证据，并保留可追踪 citation。
4. EvidencePack coverage 能区分热数据和知识数据。
5. 盘前 agent 仍能在没有知识记录时正常运行。
6. API 和前端现有 RAG 展示不破坏。
7. 全量测试通过。
