# 生产环境部署文档

本文档用于把 A-shares-agent 部署到生产环境，覆盖前端、后端 API、RAG 向量库、策略数据库、定时任务和上线检查。当前仓库已包含 Railway 双服务部署配置，也可以按同样结构部署到任意 Docker 平台。

## 1. 部署目标

生产环境至少拆成四类能力：

```text
用户浏览器
  -> Web Console 静态前端
  -> Backend API
  -> SQLite 策略数据库 / JSONL 审计事件 / RAG Qdrant 本地索引
  -> Daily Scheduler 定时任务
```

推荐服务拆分：

| 服务 | 作用 | 部署目录 | 运行方式 |
| --- | --- | --- | --- |
| `web` | React 控制台，展示盘前、单票策略、数据库闭环等页面 | `web/` | Caddy 静态服务 |
| `api` | FastAPI 后端，提供策略、RAG、LLM 配置、可视化数据 API | 仓库根目录 | Uvicorn |
| `scheduler` | 每日 9:15 前推荐、9:30 后结算昨日标的并学习 | 仓库根目录 | 常驻进程或平台 Cron |
| `qdrant` | RAG 向量检索存储 | 本地持久化目录或独立服务 | 本地文件模式或 Qdrant 服务 |
| `database` | 策略决策账本、价格、结果、因子权重、审计过程 | `data/daily_strategy.sqlite` | SQLite 持久化文件 |

小规模生产可以把 `api`、`scheduler`、SQLite、RAG 本地索引放在同一个后端容器加持久化卷中。后续并发变高后，再把 SQLite 迁移到 PostgreSQL，把 Qdrant 改为独立服务。

## 2. 基础环境

后端：

- Python 3.13
- `pip install -e .`
- FastAPI / Uvicorn
- 可写持久化目录：`data/`、`reports/`

前端：

- Node.js 20
- `npm ci`
- `npm run build`
- Caddy 或 Nginx 托管 `web/dist`

运行时网络：

- 后端需要访问行情/资讯数据源。
- 启用 LLM 时，后端需要访问 OpenAI-compatible API，例如 DeepSeek 或 OpenAI。
- 浏览器只访问 `web` 域名，`web` 反向代理或直连 `api` 域名。

## 3. 目录和持久化卷

生产环境必须持久化以下目录：

| 路径 | 内容 | 是否必须持久化 |
| --- | --- | --- |
| `data/daily_strategy.sqlite` | 每日策略推荐、结算、因子权重、审计日志 | 必须 |
| `data/config/llm_runtime.json` | LLM provider、base_url、api_key、模型路由 | 必须，且需要加密或平台 Secret 管理 |
| `data/qdrant/` | RAG 本地 Qdrant 向量索引 | 必须 |
| `data/events/` | 策略 pipeline 产生的 JSONL 事件 | 建议 |
| `data/premarket_learning/` | 盘前因子学习状态 | 建议，当前 SQLite 闭环也会存权重版本 |
| `reports/premarket/` | 每日盘前报告输入 | 必须 |
| `reports/daily/` | 每日复盘输出 | 建议 |
| `data/audit/`、`data/traces/`、`data/metrics/` | 审计、trace、指标 | 建议 |

容器部署时建议挂载一个统一卷到 `/app/data`，另一个卷到 `/app/reports`。

## 4. 环境变量

### API 服务

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 后端监听端口，Railway 会自动注入 |
| `CORS_ORIGINS` | `https://web.example.com` | 允许访问 API 的前端域名，多个值用逗号分隔 |
| `CORS_ORIGIN_REGEX` | `https://.*\.example\.com` | 可选，允许域名正则 |
| `RAILWAY_ENVIRONMENT` | `production` | Railway 环境标识，存在时默认兼容 `*.up.railway.app` |
| `PYTHONIOENCODING` | `utf-8` | 保证中文日志和 JSON 输出正常 |

LLM 运行配置当前不直接依赖环境变量，而是读取：

```text
data/config/llm_runtime.json
```

示例结构：

```json
{
  "providers": {
    "deepseek": {
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "<secret>",
      "default_model": "deepseek-chat"
    }
  },
  "agent_routes": {
    "premarket_agent": {
      "provider": "deepseek",
      "model": "deepseek-chat"
    }
  }
}
```

生产建议把 Secret 注入为平台环境变量，再在容器启动前生成该 JSON 文件，避免把密钥写入 Git。

### Web 服务

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `https://api.example.com` | 构建时写入前端，浏览器请求 API 的基础地址 |
| `API_PROXY_URL` | `https://api.example.com` | Caddy 反向代理 `/api/*` 到后端 |
| `PORT` | `8080` | Caddy 监听端口 |

如果 `VITE_API_BASE_URL` 为空，前端默认请求同源 `/api/...`，适合使用 Caddy 代理的部署方式。

## 5. 后端 API 部署

仓库根目录已有 `Dockerfile`，默认启动命令为：

```bash
uvicorn trading_agent_system.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

本地构建验证：

```bash
docker build -t a-shares-agent-api .
docker run --rm -p 8000:8000 \
  -e PORT=8000 \
  -e CORS_ORIGINS=http://localhost:5173 \
  -v %cd%/data:/app/data \
  -v %cd%/reports:/app/reports \
  a-shares-agent-api
```

Linux/macOS 把 `%cd%` 替换为 `$(pwd)`。

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

核心 API：

- `GET /api/health`
- `GET /api/daily-strategy/latest`
- `GET /api/daily-strategy/audit/{run_id}`
- `GET /api/one-pick/latest`
- `GET /api/llm/config`
- `POST /api/llm/config`

## 6. 前端部署

`web/Dockerfile` 使用 Node 构建，再用 Caddy 托管静态文件。

构建验证：

```bash
cd web
npm ci
npm run build
```

Docker 运行：

```bash
docker build -t a-shares-agent-web ./web
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e API_PROXY_URL=http://host.docker.internal:8000 \
  a-shares-agent-web
```

浏览器访问：

```text
http://127.0.0.1:8080
```

生产域名建议：

- 前端：`https://web.example.com`
- 后端：`https://api.example.com`

如果前端和后端分域名部署，需要在 API 服务设置：

```text
CORS_ORIGINS=https://web.example.com
```

## 7. RAG 部署

当前 RAG 配置位于：

```text
configs/rag.premarket.yaml
```

关键配置：

```yaml
rag:
  enabled: true
  vector_store:
    backend: qdrant
    mode: local
    path: data/qdrant
    collection_hot: premarket_hot
    collection_warm: premarket_warm
  embedding:
    provider: deterministic
    dimension: 384
```

当前实现使用 Qdrant 本地文件模式：

```python
QdrantClient(path="data/qdrant")
```

生产落地建议：

1. 小规模阶段：继续使用本地 Qdrant 文件模式，确保 `data/qdrant/` 挂载持久化卷。
2. 多实例阶段：迁移到独立 Qdrant 服务，避免多个 API 实例同时写本地索引。
3. 真实语义召回阶段：把 `embedding.provider` 从 deterministic 升级为真实 embedding 服务，并固定维度和模型版本。

RAG 数据进入方式：

- 盘前报告、资讯、风险事件等先标准化为 RAG 文档。
- 写入 `premarket_hot` 或 `premarket_warm` collection。
- 盘前 Agent 检索 evidence pack，再进入语义审阅、打分、推荐。

上线前检查：

```bash
pytest tests/premarket_rag -q
```

## 8. 数据库部署

当前数据库是 SQLite 文件：

```text
data/daily_strategy.sqlite
```

它不是 RAG 存储，而是结构化策略账本。主要表：

| 表 | 说明 |
| --- | --- |
| `strategy_runs` | 每次推荐/结算任务运行记录 |
| `premarket_events` | 盘前事件 |
| `semantic_reviews` | LLM 或规则语义审阅结果 |
| `factor_scores` | 因子分数、权重、贡献、风险标记 |
| `strategy_recommendations` | 每日推荐标的和交接给交易 Agent 的 payload |
| `strategy_prices` | 买入/卖出开盘价 |
| `strategy_outcomes` | 隔日结算收益和命中结果 |
| `factor_weight_versions` | 因子权重版本和学习摘要 |
| `decision_audit_logs` | 每个阶段的输入、输出、推理摘要 |

初始化方式：

```bash
python - <<'PY'
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore
store = StrategyLedgerStore("data/daily_strategy.sqlite")
store.close()
PY
```

备份策略：

- 每日收盘后备份 `data/daily_strategy.sqlite`。
- 每次发布前备份一次。
- 备份文件命名建议：`daily_strategy_YYYYMMDD_HHMMSS.sqlite`。

当前 schema 由代码中的 `CREATE TABLE IF NOT EXISTS` 自动初始化，还没有独立迁移工具。生产变更表结构前，应先：

1. 备份 SQLite。
2. 在 staging 环境运行新代码。
3. 验证 `GET /api/daily-strategy/latest` 和结算脚本。
4. 再发布生产。

## 9. 每日定时任务

目标：

- 9:15 前生成今日策略推荐。
- 9:30 后获取今日开盘价，并结算昨日推荐的隔日收益。
- 两件事可并行执行：今日推荐和昨日结算互不阻塞。

当前脚本：

```text
scripts/daily_premarket_scheduler.py
scripts/run_daily_premarket_recommendation.py
scripts/run_daily_strategy_settlement.py
```

推荐常驻进程：

```bash
python scripts/daily_premarket_scheduler.py \
  --recommendation-time 08:45 \
  --settlement-time 09:31 \
  --db-path data/daily_strategy.sqlite \
  --report-dir reports/premarket \
  --event-dir data/events \
  --learning-dir data/premarket_learning \
  --top-n 10
```

一次性执行：

```bash
python scripts/daily_premarket_scheduler.py --once
```

如果使用平台 Cron，建议拆成两个任务：

```bash
# 08:45 生成今日推荐
python scripts/run_daily_premarket_recommendation.py \
  --date 2026-06-19 \
  --db-path data/daily_strategy.sqlite \
  --use-llm

# 09:31 结算昨日策略并学习
python scripts/run_daily_strategy_settlement.py \
  --date 2026-06-19 \
  --db-path data/daily_strategy.sqlite
```

注意：

- 交易日判断由 `TradingCalendarService` 处理。
- 当前结算脚本支持从 `--price-file` 读取开盘价；生产需要接入真实行情源后，再把 9:30 开盘价写入 `strategy_prices`。
- LLM 推荐需要 `--use-llm` 和有效的 `data/config/llm_runtime.json`。

## 10. Railway 部署

仓库已有 Railway 文档：

```text
docs/railway-deployment.md
```

核心流程：

```powershell
npx --yes @railway/cli login
npx --yes @railway/cli init --name A-shares-agent
npx --yes @railway/cli add --service api
npx --yes @railway/cli add --service web
npx --yes @railway/cli domain --service api
npx --yes @railway/cli domain --service web
```

设置变量：

```powershell
npx --yes @railway/cli variable set VITE_API_BASE_URL=https://<api-service-domain> --service web
npx --yes @railway/cli variable set API_PROXY_URL=https://<api-service-domain> --service web
npx --yes @railway/cli variable set CORS_ORIGINS=https://<web-service-domain> --service api
```

部署：

```powershell
npx --yes @railway/cli up . --service api --detach
npx --yes @railway/cli up .\web --path-as-root --service web --detach
```

生产补充：

- 给 API 服务挂载持久化卷到 `/app/data` 和 `/app/reports`。
- 若 Railway 使用单独 Cron 服务，Cron 服务也需要挂载同一份 `/app/data` 和 `/app/reports`。
- 不要把 `data/config/llm_runtime.json` 里的密钥提交到仓库。

## 11. 发布检查清单

发布前：

```bash
pytest -q
cd web && npm run build
```

生产启动后：

```bash
curl https://api.example.com/api/health
curl https://api.example.com/api/daily-strategy/latest
```

页面检查：

- 控制台可打开。
- “单票策略”页面能显示今日推荐。
- 股票代码已转换为中文股票名称。
- 结算结果能显示买入价、卖出价、收益率。
- 决策审计能看到语义审阅、因子打分、推荐阶段。

数据检查：

```bash
sqlite3 data/daily_strategy.sqlite ".tables"
sqlite3 data/daily_strategy.sqlite "select run_id, trading_day, run_type, status from strategy_runs order by id desc limit 5;"
sqlite3 data/daily_strategy.sqlite "select symbol, action, confidence, signal_score from strategy_recommendations order by id desc limit 5;"
sqlite3 data/daily_strategy.sqlite "select version, is_active from factor_weight_versions order by id desc limit 5;"
```

RAG 检查：

- `data/qdrant/` 目录存在且非空。
- RAG 相关测试通过。
- 盘前报告中存在 evidence pack。

定时任务检查：

- 08:45 后出现当日 `premarket_recommend` run。
- 09:31 后出现 settlement 结果。
- `decision_audit_logs` 有对应 run_id 的过程记录。
- `factor_weight_versions` 在有有效结算样本后产生新 active 版本。

## 12. 监控和告警

最低监控项：

- API `/api/health` 可用性。
- Scheduler 最近一次成功运行时间。
- SQLite 文件大小和备份状态。
- `strategy_runs.status = failed` 的数量。
- LLM 调用失败率和超时。
- RAG 索引目录是否可写。
- 前端 5xx / API 4xx 异常。

建议告警：

- 交易日 09:10 后仍没有当日盘前报告。
- 交易日 09:15 后仍没有当日推荐。
- 交易日 09:40 后仍没有昨日结算。
- LLM 配置缺失或 provider 调用失败。
- SQLite 不可写或磁盘空间低于 20%。

## 13. 回滚方案

代码回滚：

1. 回滚到上一版镜像或上一版 Git commit。
2. 保持 `data/` 和 `reports/` 卷不变。
3. 重启 API 和 scheduler。

数据回滚：

1. 停止 API 和 scheduler。
2. 备份当前异常 SQLite。
3. 恢复上一份 `daily_strategy.sqlite`。
4. 启动 API。
5. 验证 `/api/daily-strategy/latest`。

权重回滚：

如果只是因子学习权重异常，不需要回滚整库，可以把上一版权重重新设为 active。当前仓库已有 repository 能力，后续可补一个运维脚本执行：

```python
from trading_agent_system.core.strategy_ledger import StrategyLedgerStore
store = StrategyLedgerStore("data/daily_strategy.sqlite")
store.weights.activate("<previous_weight_version>")
store.close()
```

## 14. 后续生产增强

短期：

- 把 `data/config/llm_runtime.json` 改为由环境变量生成。
- 给 scheduler 增加运行日志和失败重试。
- 接入真实 9:30 开盘价数据源。
- 增加 SQLite 自动备份脚本。

中期：

- SQLite 迁移到 PostgreSQL。
- Qdrant 改为独立服务。
- Embedding 从 deterministic 改为真实 embedding 模型。
- 增加 Alembic 或等价迁移工具。

长期：

- 将盘前 Agent 输出的 handoff payload 接给交易 Agent。
- 建立 staging 环境和生产只读可视化看板。
- 增加模型版本、prompt hash、数据快照的完整审计链路。
