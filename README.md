# A股 Agent MVP

This repository implements a safe paper-trading MVP for the pasted A-share trading-agent specification.

## 项目功能边界

项目对外展示为三条主线：

- 交易流水线：`PremarketAgent -> IntradayAgent -> RiskGateway -> PaperBroker -> ReviewAgent`。
- 盘前知识系统：信息源、事件抽取、RAG 证据、规则/历史案例、`PremarketContext`。
- 运维与审计：事件、Trace、Metrics、Approval Queue、报告预览。

真正的业务 Agent 只有 `PremarketAgent`、`IntradayAgent` 和 `ReviewAgent`。RiskGateway 是确定性风控服务，不是业务 Agent；PaperBroker 是模拟执行服务，不是业务 Agent。RAG、信息源、知识库、`PremarketContext` 是能力模块，用来支撑盘前分析和盘中约束。

The default loop is:

```text
External information / MarketBar
  -> PremarketAgent
  -> PremarketContext
  -> IntradayAgent
  -> trading.intents
  -> RiskGateway
  -> risk.decisions + orders.instructions
  -> PaperBroker
  -> orders.filled + account/position snapshots
  -> ReviewAgent daily reports
```

Safety defaults:

- Paper trading only.
- `trading_enabled: false`.
- `require_human_approval: true`.
- No real broker adapter.
- `RiskGateway` is deterministic and does not call an LLM.
- `IntradayAgent` never publishes `orders.instructions`.
- Review output is advisory and never mutates strategy config.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

python scripts/run_intraday_agent.py --config configs/app.yaml --demo
python scripts/run_risk_gateway.py --config configs/risk.paper.yaml --demo
python scripts/run_paper_broker.py --config configs/app.yaml --demo
python scripts/run_review_agent.py --date 2026-06-09 --config configs/app.yaml --demo
```

Reports are written to `reports/daily/`.

## Monorepo Packages

The repository is moving toward a monorepo layout. The first extracted capability is the premarket crawler boundary:

```text
packages/
  premarket-contracts/      # shared Pydantic contracts for crawler and host
  premarket-crawler-mcp/    # crawler registry, service, providers, and MCP tools
```

`trading_agent_system` still owns the trading agents, RAG, knowledge store, reports, risk, and audit flow. The crawler package owns source fetching and standardization, while the host consumes it through `LocalPremarketCrawlerProvider`.

The crawler MCP package exposes tool-shaped functions:

- `health`
- `list_sources`
- `fetch_source_news`
- `fetch_premarket_news`

## Web Console

Start the local API:

```bash
. .venv/bin/activate
pip install -e .
python scripts/run_api.py --port 8000
```

Start the React console in another terminal:

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.
