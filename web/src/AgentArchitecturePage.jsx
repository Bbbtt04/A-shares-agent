import React from 'react';

const ARCHITECTURE_LAYERS = [
  {
    id: 'foundation',
    title: '基础层',
    progress: '1/3 完成',
    note: '真实工具已落地，LLM Gateway 与通用 Agent Loop 还未抽象。',
    tone: 'blue',
    modules: [
      {
        number: 1,
        title: 'LLM 基础调用',
        status: '缺口',
        subtitle: '统一 messages、tools、stop_reason、streaming 的模型访问层。',
        current: '当前项目没有统一 LLMClient，盘前/盘中/风控主要是确定性规则、Pydantic Schema 与数据管道。',
        value: '以后所有 Agent 都通过它调用模型，避免每个 Agent 自己拼 prompt、解析输出、处理失败。',
        next: '新增 LLMGateway，定义 ChatMessage、ToolCall、StopReason、StructuredOutput。',
        tags: ['LLM', 'messages', 'stop_reason'],
      },
      {
        number: 2,
        title: '最小可用 Agent',
        status: '部分',
        subtitle: 'LLM + 工具调用 + 循环 = 可泛化 Agent Runtime。',
        current: '已有 PremarketAgent、IntradayAgent、ReviewAgent 等业务 Agent，但它们是业务流程循环，不是通用 LLM tool-use loop。',
        value: '把“思考、调用工具、观察结果、继续行动、结束”做成公共运行时，后续新增 Agent 会轻很多。',
        next: '抽象 AgentLoop：max_steps、tool_result 回填、stop_reason 判断、结构化结束条件。',
        tags: ['Agent Loop', 'Tool Use', 'tool_use'],
      },
      {
        number: 3,
        title: '真实工具',
        status: '完成',
        subtitle: '文件读写、代码执行、网页抓取、行情拉取、报告生成。',
        current: '已有新闻源 provider、行情 provider、JSONL/SQLite 存储、脚本运行、FastAPI 端点与 React 控制台。',
        value: 'Agent 已经能使用真实市场数据、报告文件、事件日志和本地服务，不只是玩具 demo。',
        next: '把这些能力注册到 ToolRegistry，提供统一参数校验和权限边界。',
        tags: ['fs', 'fetch', 'market_data'],
      },
    ],
  },
  {
    id: 'collaboration',
    title: '协作层',
    progress: '0/3 完成 · 2 部分',
    note: '业务 Agent 链路已串起，通用 Orchestrator、Skill、DAG 仍待补。',
    tone: 'purple',
    modules: [
      {
        number: 4,
        title: '多 Agent 协作',
        status: '部分',
        subtitle: '盘前、盘中、风控、执行、复盘分工协作。',
        current: '当前链路是 PremarketAgent → IntradayAgent → RiskGateway → PaperBroker → ReviewAgent，通过事件和报告传递上下文。',
        value: '每个 Agent 只做自己的专业任务，风控和执行被隔离，降低误操作风险。',
        next: '增加 Orchestrator Agent，负责拆任务、路由、汇总和失败恢复。',
        tags: ['Orchestrator', 'Sub-agent', 'Multi-agent'],
      },
      {
        number: 9,
        title: 'Skill 系统',
        status: '缺口',
        subtitle: 'Tool → Skill → Agent 三层架构。',
        current: '目前能力直接写在 Agent、provider、service 里，没有独立 SkillRegistry。',
        value: 'Skill 可以把“盘前消息分析”“RAG 检索”“风控审批”等能力封装成可复用模块。',
        next: '建立 SkillRegistry，定义 skill metadata、输入输出 schema、依赖工具和安全等级。',
        tags: ['Skill', 'Registry', '三层架构'],
      },
      {
        number: 10,
        title: '工作流引擎',
        status: '部分',
        subtitle: '顺序、条件分支、并行节点、失败补偿。',
        current: '现在通过 CLI/API 串行运行多个脚本，前端支持 run-all，但没有显式 DAG 模型。',
        value: '工作流引擎可以把盘前、盘中、风控、复盘配置成可视化、可重跑、可追踪的节点图。',
        next: '新增 WorkflowEngine，支持节点状态、条件边、并行执行、重试策略。',
        tags: ['Workflow', 'DAG', '条件分支'],
      },
    ],
  },
  {
    id: 'capability',
    title: '能力层',
    progress: '1/2 完成 · 1 部分',
    note: 'RAG 已经比较完整，记忆系统还停留在事件和知识库雏形。',
    tone: 'cyan',
    modules: [
      {
        number: 5,
        title: '记忆系统',
        status: '部分',
        subtitle: '短期历史 + 长期事实 + 自动压缩。',
        current: '已有 JSONL 事件、日报、PremarketContext、SQLite KnowledgeStore，但没有统一 Memory API。',
        value: '记忆层负责沉淀用户偏好、策略经验、历史盘前结论和高价值事实。',
        next: '区分 ShortMemory、LongMemory、MemoryCompressor，并接入 AgentLoop。',
        tags: ['Memory', '短期记忆', '长期记忆'],
      },
      {
        number: 8,
        title: 'RAG 检索增强',
        status: '完成',
        subtitle: '向量化 → 混合检索 → EvidencePack → 可评估引用。',
        current: '已接入 Qdrant local、确定性 embedding、结构化/关键词/向量/风险/题材检索、RRF 融合、去重和 EvidencePack。',
        value: '盘前 Agent 能把盘后到早盘的信息做成可追溯证据包，前端能看到覆盖率、引用和来源质量。',
        next: '接入真实 embedding 模型、黄金数据集和跨窗口历史题材召回。',
        tags: ['RAG', 'Qdrant', 'EvidencePack'],
      },
    ],
  },
  {
    id: 'production',
    title: '生产层',
    progress: '1/6 完成 · 5 部分',
    note: '可观测性已成型，可靠性、HITL、事件驱动和评估还需要产品化。',
    tone: 'red',
    modules: [
      {
        number: 6,
        title: '可靠性增强',
        status: '部分',
        subtitle: '防死循环、自动重试、超时、结构化输出。',
        current: '已有 Pydantic Schema、安全默认值、风控硬拒、RAG 去重和 token budget。',
        value: '可靠性层保证 Agent 不乱跑、不无限循环、不输出无法审计的内容。',
        next: '增加 retry/backoff、timeout、dead-loop guard、输出 schema repair。',
        tags: ['Reliability', '重试', '结构化输出'],
      },
      {
        number: 7,
        title: '生产化',
        status: '部分',
        subtitle: 'Streaming、并行执行、MCP 协议、部署形态。',
        current: '已有 FastAPI、React/Vite、本地脚本、并行前端请求和 JSONL 持久化。',
        value: '生产化让系统从本地 demo 变成可持续运行、可接入外部工具的服务。',
        next: '补 WebSocket/streaming、MCP tool server、后台任务队列和部署配置。',
        tags: ['Streaming', '并行', 'MCP'],
      },
      {
        number: 11,
        title: 'Human-in-the-loop',
        status: '部分',
        subtitle: '风险等级、人工审批、修改参数、驳回。',
        current: '已有 RiskGateway、require_human_approval 默认值、approval queue API 和前端展示。',
        value: '高风险动作必须经过人工确认，系统只能建议和排队，不能越权实盘。',
        next: '前端增加批准/驳回/修改数量价格的操作流，并写入审计事件。',
        tags: ['HITL', 'Risk', '人工审批'],
      },
      {
        number: 12,
        title: '可观测性',
        status: '完成',
        subtitle: 'Trace、Span、Metrics、Event 全链路追踪。',
        current: '已有 DurableEventBus、EventEnvelope、TraceLogger、MetricsRecorder、RAG evaluation、观测 API 与 React 面板。',
        value: '可以追踪每个 Agent 做了什么、用了哪些证据、产出了哪些事件和指标。',
        next: '补 span 层级、链路火焰图、异常聚合和更细的 RAG latency 指标。',
        tags: ['Observability', 'Trace', 'Metrics'],
      },
      {
        number: 13,
        title: '评估与测试',
        status: '部分',
        subtitle: '确定性测试、黄金数据集、LLM-as-Judge。',
        current: '已有 47 个测试覆盖盘前、盘中、风控、观测、知识库和 RAG evaluator。',
        value: '评估层让策略和 Agent 改动可以量化回归，不靠肉眼看几条输出。',
        next: '建立黄金样本、盘前召回率、LLM-as-Judge 评分和每日回归报告。',
        tags: ['Evaluation', 'Testing', 'LLM-as-Judge'],
      },
      {
        number: 14,
        title: '事件驱动 Agent',
        status: '部分',
        subtitle: 'Cron 定时、文件监听、任务队列、市场事件触发。',
        current: '已有 JSONL 事件总线和 API run-all；还没有后台 scheduler、watcher 或 queue worker。',
        value: '事件驱动后，盘前定时分析、盘中行情触发、复盘定时生成都能自动化。',
        next: '增加 Cron 配置、MarketWatcher、JobQueue 和失败重放机制。',
        tags: ['Event-driven', 'Cron', 'Watcher'],
      },
    ],
  },
];

const STATUS_CLASS = {
  完成: 'done',
  部分: 'partial',
  缺口: 'missing',
};

function AgentArchitecturePage() {
  const totalModules = ARCHITECTURE_LAYERS.reduce((sum, layer) => sum + layer.modules.length, 0);
  const doneModules = ARCHITECTURE_LAYERS.flatMap((layer) => layer.modules).filter((item) => item.status === '完成').length;
  const partialModules = ARCHITECTURE_LAYERS.flatMap((layer) => layer.modules).filter((item) => item.status === '部分').length;

  return (
    <section className="architecture-page">
      <div className="architecture-hero">
        <div>
          <p className="architecture-kicker">Current Agent Architecture</p>
          <h2>当前 A 股 Agent 分层功能说明</h2>
          <p>
            这页描述的是现在代码里已经落地的架构，不是最终理想图。它把 Agent 分成基础层、协作层、
            能力层和生产层，并说明每个功能现在做到了哪里、解决什么问题、下一步补什么。
          </p>
        </div>
        <div className="architecture-score">
          <span>模块进度</span>
          <strong>{doneModules}/{totalModules}</strong>
          <small>{partialModules} 个模块已部分落地</small>
        </div>
      </div>

      <div className="architecture-summary-grid">
        {ARCHITECTURE_LAYERS.map((layer) => (
          <article className={`architecture-summary architecture-${layer.tone}`} key={layer.id}>
            <h3>{layer.title}</h3>
            <strong>{layer.progress}</strong>
            <p>{layer.note}</p>
          </article>
        ))}
      </div>

      <div className="architecture-flow">
        <span>外部数据</span>
        <span>盘前 Agent</span>
        <span>RAG 证据</span>
        <span>盘中 Agent</span>
        <span>风控 / 审批</span>
        <span>复盘 / 观测</span>
      </div>

      {ARCHITECTURE_LAYERS.map((layer) => (
        <section className="architecture-layer" key={layer.id}>
          <div className={`architecture-layer-title architecture-title-${layer.tone}`}>
            <span />
            <h3>{layer.title}</h3>
            <p>{layer.note}</p>
          </div>
          <div className="architecture-card-grid">
            {layer.modules.map((module) => (
              <article className={`architecture-card architecture-card-${layer.tone}`} key={module.number}>
                <div className="architecture-card-head">
                  <span className="architecture-number">{module.number}</span>
                  <span className={`architecture-status ${STATUS_CLASS[module.status]}`}>{module.status}</span>
                </div>
                <h4>{module.title}</h4>
                <p className="architecture-subtitle">{module.subtitle}</p>
                <dl className="architecture-details">
                  <div>
                    <dt>当前实现</dt>
                    <dd>{module.current}</dd>
                  </div>
                  <div>
                    <dt>功能价值</dt>
                    <dd>{module.value}</dd>
                  </div>
                  <div>
                    <dt>下一步</dt>
                    <dd>{module.next}</dd>
                  </div>
                </dl>
                <div className="architecture-tags">
                  {module.tags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}

export default AgentArchitecturePage;
