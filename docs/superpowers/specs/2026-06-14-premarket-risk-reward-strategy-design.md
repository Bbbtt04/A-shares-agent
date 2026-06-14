# 盘前 Agent 风险收益比推荐策略 v1 设计

## 背景

盘前 Agent 的信息获取能力已经基本成型：它可以抓取盘前新闻、公告、同花顺热点、a-stock-data 候选股、腾讯行情和题材映射。下一阶段的重点不是继续堆数据源，而是把这些信息转成可解释、可调试、可复盘、可迭代的候选交易计划。

本设计把盘前 Agent 的目标从“列出相关信息”升级为“基于风险收益比生成候选交易计划”。系统不追求单纯胜率，而是追求可控亏损下的正期望风险收益比。

## 核心原则

1. 大模型不直接推荐股票，不直接生成止损价或目标价。
2. 股票排序、入场区间、止损价、目标价由策略引擎按规则计算。
3. 大模型只负责信息归因、冲突解释、报告表达和复盘建议。
4. 每个结果必须有完整 `decision_trace`，能解释为什么入选、为什么被过滤、为什么是这个价格。
5. 策略必须版本化，所有推荐都绑定 `strategy_id` 和 `strategy_version`。
6. 前期允许用户人工纠错；后期由 Agent Loop 生成策略优化提案，但不自动偷偷上线。

## 非目标

- 不做自动下单。
- 不绕过现有风控链路。
- 不把大模型输出当成交易价格。
- 不以单日收益最大化为优化目标。
- 不在第一版引入机器学习模型训练。
- 不要求所有推荐一定触发买入，盘前计划可以只输出观察条件。

## 总体架构

```text
信息源
  -> 候选池构建 Candidate Builder
  -> 特征构建 Feature Builder
  -> 风险收益比策略 Strategy Engine
  -> 价格计划 Price Planner
  -> 模式分层 Mode Classifier
  -> 决策追踪 Decision Trace
  -> 大模型解释 Narrative Layer
  -> Web 调试 / 报告 / 反馈
```

### 1. 信息源

当前已有信息源继续复用：

- `PremarketNewsItem`: 新闻、公告、热点、a-stock-data 盘前候选。
- `AStockDataAdapter`: 腾讯行情、涨跌停、量比、估值等实时字段。
- `ThemeRegistry`: 题材到股票池映射。
- `premarket.rag_*`: 历史知识、上下文、证据包。
- 后续可扩展：龙虎榜、融资融券、资金流、解禁、大宗交易、行业板块排名。

### 2. 候选池构建

候选池只负责“哪些股票值得被评分”，不直接推荐。

候选来源：

- a-stock-data `quote_candidate`
- 同花顺热点强势股
- 个股新闻/公告中提到的股票
- 热点题材映射出的股票
- 用户自选股
- 历史关注池和前一日盘后关注池

候选池去重键：

```text
symbol + trading_day
```

候选池每个元素必须保留来源证据：

```json
{
  "symbol": "688256.SH",
  "name": "寒武纪",
  "candidate_sources": ["a-stock-data/premarket", "tonghuashun_hotspot"],
  "themes": ["算力", "AI芯片"],
  "evidence_item_ids": ["news_xxx", "news_yyy"]
}
```

### 3. 特征构建

每只候选股转成结构化特征。第一版使用可解释规则，不做黑盒模型。

```json
{
  "symbol": "688256.SH",
  "trading_day": "2026-06-14",
  "features": {
    "catalyst_strength": 0.0,
    "source_confirmation": 0.0,
    "theme_heat": 0.0,
    "market_strength": 0.0,
    "liquidity": 0.0,
    "risk_score": 0.0,
    "volatility": 0.0,
    "price_position": 0.0
  }
}
```

第一版特征范围：

| 特征 | 含义 | 第一版数据来源 |
| --- | --- | --- |
| `catalyst_strength` | 新闻、公告、热点催化强度 | `PremarketNewsItem` |
| `source_confirmation` | 多源确认程度 | source count |
| `theme_heat` | 题材热度和板块联动 | 同花顺热点、题材映射 |
| `market_strength` | 个股行情强度 | 腾讯行情：涨跌幅、量比、涨停约束 |
| `liquidity` | 流动性和可交易性 | 成交额、换手率、市值，第一版可先用行情字段 |
| `risk_score` | 风险事件和高波动惩罚 | 公告、监管、减持、解禁、ST、高位连续上涨 |
| `volatility` | 波动幅度 | 日内/历史波动，第一版可用价格区间近似 |
| `price_position` | 价格相对支撑/压力位置 | 第一版使用当前价、昨收、涨跌停约束 |

### 4. 策略评分

策略采用可配置权重，输出 `trade_score` 和 `expected_r`。

```yaml
strategy_id: premarket_rr_v1
objective: risk_reward_ratio

weights:
  catalyst_strength: 0.25
  source_confirmation: 0.15
  theme_heat: 0.20
  market_strength: 0.20
  liquidity: 0.10
  risk_score: -0.25
  volatility_penalty: -0.10

thresholds:
  conservative:
    min_trade_score: 80
    min_rr: 1.8
    min_expected_r: 0.35
    max_risk_score: 30
    max_items: 3
  opportunity:
    min_trade_score: 65
    min_rr: 2.0
    min_expected_r: 0.20
    max_risk_score: 50
    max_items: 8
  watch:
    min_trade_score: 45
    min_rr: 1.5
    max_items: 20
```

机会型允许信息确认弱一点，所以要求更高风险收益比来补偿不确定性。

### 5. 风险收益比公式

第一版核心公式：

```text
entry_mid = (entry_low + entry_high) / 2
single_trade_risk = entry_mid - stop_loss

rr_1 = (target_price_1 - entry_mid) / single_trade_risk
rr_2 = (target_price_2 - entry_mid) / single_trade_risk

expected_r = win_probability_estimate * average_target_r
             - loss_probability_estimate * 1.0
             - slippage_penalty
             - risk_penalty
```

第一版不做真实胜率模型，使用规则估计：

```text
win_probability_estimate = base_probability
  + catalyst_bonus
  + theme_bonus
  + confirmation_bonus
  + market_strength_bonus
  - risk_penalty
  - volatility_penalty
```

`win_probability_estimate` 必须限制在合理范围：

```text
min: 0.25
max: 0.72
```

这样可以防止策略过度自信。

### 6. 价格计划

止损价和目标价由 `PricePlanner` 计算，不由大模型生成。

第一版先使用腾讯行情和涨跌停约束：

```text
reference_price = 当前价，如果没有则用昨收
entry_low = reference_price * (1 - entry_buffer)
entry_high = reference_price * (1 + entry_buffer)
raw_stop = reference_price * (1 - stop_pct)
stop_loss = max(raw_stop, limit_down)

risk = entry_mid - stop_loss
target_price_1 = min(entry_mid + risk * target_r_1, limit_up)
target_price_2 = min(entry_mid + risk * target_r_2, limit_up)
```

默认参数：

```yaml
price_plan:
  entry_buffer: 0.012
  stop_pct_main_board: 0.035
  stop_pct_chinext_star: 0.045
  target_r_1: 1.8
  target_r_2: 2.6
  min_risk_pct: 0.015
  max_risk_pct: 0.06
```

后续版本加入：

- ATR 止损
- 昨日低点 / 5 日均线 / 10 日均线
- 前高压力位
- 板块指数强弱
- 分时资金流确认

### 7. 三种输出模式

三种模式来自同一套候选和评分，不做三套策略。

#### 稳健型

适合用户盘前重点盯 1-3 只。

入选条件：

- `trade_score >= 80`
- `expected_r >= 0.35`
- `rr_1 >= 1.8`
- `risk_score <= 30`
- 至少两个信息源确认，或一个高可信公告源
- 必须有明确价格计划

#### 机会型

适合用户盘前扩展观察 3-8 只。

入选条件：

- `trade_score >= 65`
- `expected_r >= 0.20`
- `rr_1 >= 2.0`
- `risk_score <= 50`
- 允许题材强但确认稍弱

#### 观察型

适合盘中继续追踪。

入选条件：

- `trade_score >= 45`
- `rr_1 >= 1.5`
- 或有强题材/强消息但风险收益比暂未达标

观察型可以没有强推荐语，只输出触发条件和放弃条件。

### 8. 决策追踪

每个候选都要生成 `decision_trace`，无论是否入选。

```json
{
  "symbol": "688256.SH",
  "strategy_id": "premarket_rr_v1",
  "strategy_version": "2026-06-14.1",
  "mode": "opportunity",
  "trade_score": 72.4,
  "expected_r": 0.28,
  "score_breakdown": {
    "catalyst_strength": 18.0,
    "source_confirmation": 8.0,
    "theme_heat": 16.0,
    "market_strength": 14.0,
    "liquidity": 7.0,
    "risk_score": -9.0
  },
  "price_plan": {
    "reference_price": 100.0,
    "entry_low": 98.8,
    "entry_high": 101.2,
    "stop_loss": 95.5,
    "target_price_1": 109.1,
    "target_price_2": 113.7,
    "rr_1": 1.8,
    "rr_2": 2.6
  },
  "evidence": [
    {
      "item_id": "news_xxx",
      "source": "a-stock-data/premarket",
      "category": "quote_candidate",
      "title": "寒武纪盘前观察候选"
    }
  ],
  "reject_reasons": [
    "未进入稳健型：信息源确认不足 2 个"
  ]
}
```

调试页必须支持：

- 查看所有候选，不只看最终入选。
- 查看每只股票的分数拆解。
- 查看价格计划公式输入和输出。
- 查看未入选原因。
- 查看同一股票在稳健型、机会型、观察型之间的差异。

### 9. 用户反馈机制

人工纠错必须结构化保存，而不是只留在聊天里。

反馈类型：

```text
good_pick        推荐合理
bad_pick         不该推荐
missed_pick      漏掉了该推荐的股票
price_too_tight  止损太近
price_too_loose  止损太远
target_too_low   目标太保守
target_too_high  目标太激进
risk_missed      漏算风险
theme_wrong      题材归因错误
```

反馈记录：

```json
{
  "trading_day": "2026-06-14",
  "symbol": "688256.SH",
  "strategy_id": "premarket_rr_v1",
  "strategy_version": "2026-06-14.1",
  "label": "price_too_tight",
  "reason": "科创板盘前波动大，4.5% 止损容易被洗掉",
  "suggested_change": {
    "stop_pct_chinext_star": 0.055
  },
  "created_by": "user"
}
```

前期流程：

```text
用户纠错 -> 保存反馈 -> Review Agent 汇总 -> 人工决定是否改策略参数
```

后期流程：

```text
用户纠错 + 实盘/回放表现 -> Optimizer Agent 生成策略变更提案 -> 回放验证 -> 人工批准
```

### 10. Agent Loop 自动优化

第一阶段只做“建议”，不做自动上线。

每日循环：

```text
盘前生成候选交易计划
-> 盘中记录是否触发入场条件
-> 收盘后记录最大浮盈、最大浮亏、是否止损、是否到目标
-> 计算每笔实际 R
-> Review Agent 做归因
-> Optimizer Agent 生成参数调整建议
-> 回放最近 N 天
-> 生成策略变更提案
-> 用户批准后生效
```

回放指标：

```text
average_r
total_r
median_r
max_drawdown_r
stop_loss_rate
target_1_hit_rate
target_2_hit_rate
untriggered_rate
false_positive_rate
missed_opportunity_count
```

策略变更提案格式：

```json
{
  "proposal_id": "proposal_xxx",
  "base_strategy_version": "2026-06-14.1",
  "candidate_strategy_version": "2026-06-21.1",
  "changes": [
    {
      "path": "weights.risk_score",
      "from": -0.25,
      "to": -0.32,
      "reason": "最近 20 个交易日高风险票平均 R 显著偏低"
    }
  ],
  "backtest_summary": {
    "days": 20,
    "average_r_before": 0.18,
    "average_r_after": 0.26,
    "max_drawdown_before": -4.2,
    "max_drawdown_after": -3.1
  },
  "recommendation": "approve_with_review"
}
```

自动优化边界：

- 不自动改风控下限。
- 不自动降低 `min_rr`。
- 不自动放宽 `max_risk_score` 超过配置上限。
- 不基于少于 20 个交易日的数据自动建议大幅调整。
- 每次变更只允许小步调整，避免过拟合。

### 11. 大模型职责

大模型可以做：

- 汇总每只候选的证据。
- 解释进入稳健型、机会型、观察型的原因。
- 解释未入选原因。
- 总结用户反馈。
- 生成策略优化提案的自然语言说明。
- 检查策略变更是否有明显逻辑矛盾。

大模型不可以做：

- 直接生成止损价。
- 直接生成目标价。
- 直接覆盖策略分数。
- 在没有回放验证时宣称新策略更好。
- 自动上线策略。

### 12. 输出形态

盘前报告建议输出：

```text
今日候选交易计划

稳健型
1. 688256.SH 寒武纪
   推荐等级：A
   入场区间：98.8 - 101.2
   止损价：95.5
   目标价：109.1 / 113.7
   风险收益比：1.8 / 2.6
   预期R：0.36
   触发条件：09:20 后竞价强于板块；开盘后不跌破竞价均价
   放弃条件：低开超过阈值；板块无联动；出现负面公告
   理由：算力题材热度 + a-stock-data 候选 + 行情强度确认

机会型
1. 300308.SZ 中际旭创
   推荐等级：B+
   入场区间：146.0 - 149.5
   止损价：140.8
   目标价：158.4 / 166.0
   风险收益比：2.0 / 3.1
   预期R：0.24
   未进稳健原因：信息源确认不足 2 个，且波动惩罚较高
   触发条件：算力板块竞价联动；个股竞价成交额放大
   放弃条件：板块龙头低于预期；开盘跌破竞价均价

观察型
1. 002371.SZ 北方华创
   推荐等级：观察
   入场区间：暂不建议直接入场
   止损价：仅在触发入场后计算
   目标价：仅在触发入场后计算
   风险收益比：当前未达稳健/机会阈值
   触发条件：半导体板块放量走强；个股突破盘前参考价
   放弃条件：板块无联动；出现负面公告；竞价承接弱
   理由：题材相关，但风险收益比或确认度暂未达标
```

Web 调试页建议新增：

- 策略总览：策略版本、模式阈值、候选数量、入选数量。
- 候选表：股票、总分、风险收益比、预期R、模式、状态。
- 单票详情：证据、特征、分数拆解、价格计划、过滤原因。
- 反馈入口：标记“错推荐”“漏推荐”“止损太近”等。
- 回放结果：按策略版本对比平均 R 和回撤。

### 13. 数据结构建议

新增或扩展结构：

```text
PremarketCandidate
PremarketFeatureSnapshot
PremarketPricePlan
PremarketDecisionTrace
PremarketRecommendation
PremarketStrategyConfig
PremarketStrategyFeedback
PremarketStrategyProposal
```

`PremarketTradePlan` 可以保留作为报告输出层，但策略内部不要只依赖它。内部应该使用更完整的 `PremarketRecommendation`，最后再映射到 `PremarketTradePlan` 或报告 JSON。

### 14. 配置文件建议

新增：

```text
configs/premarket.strategy.yaml
```

示例：

```yaml
active_strategy: premarket_rr_v1

strategies:
  premarket_rr_v1:
    objective: risk_reward_ratio
    price_plan:
      entry_buffer: 0.012
      stop_pct_main_board: 0.035
      stop_pct_chinext_star: 0.045
      target_r_1: 1.8
      target_r_2: 2.6
      min_risk_pct: 0.015
      max_risk_pct: 0.06
    weights:
      catalyst_strength: 0.25
      source_confirmation: 0.15
      theme_heat: 0.20
      market_strength: 0.20
      liquidity: 0.10
      risk_score: -0.25
      volatility_penalty: -0.10
    thresholds:
      conservative:
        min_trade_score: 80
        min_rr: 1.8
        min_expected_r: 0.35
        max_risk_score: 30
        max_items: 3
      opportunity:
        min_trade_score: 65
        min_rr: 2.0
        min_expected_r: 0.20
        max_risk_score: 50
        max_items: 8
      watch:
        min_trade_score: 45
        min_rr: 1.5
        max_items: 20
```

### 15. 测试策略

第一版测试重点：

- 候选池能从新闻、公告、a-stock-data 和题材映射生成股票。
- 特征构建能解释每个分数来源。
- 价格计划不会生成低于跌停或高于涨停的价格。
- 风险收益比计算正确。
- 三种模式阈值正确。
- 被过滤候选保留 `reject_reasons`。
- 同一输入和同一策略版本输出稳定。
- 用户反馈能被保存并关联到策略版本。
- 回放指标按 R 计算，不按绝对盈亏计算。

### 16. 实施分期

#### Phase 1: 可调试策略引擎

- 增加策略配置文件。
- 增加候选池、特征、价格计划、评分和 decision trace。
- 报告输出稳健型、机会型、观察型。
- Web 调试页能查看分数和价格拆解。

#### Phase 2: 人工反馈闭环

- Web 增加反馈入口。
- 反馈保存为结构化事件。
- Review Agent 汇总用户纠错。
- 策略参数仍由人工改。

#### Phase 3: 回放评估

- 记录是否触发入场。
- 记录收盘后 R 表现。
- 按策略版本生成回放指标。
- 支持对比两个策略版本。

#### Phase 4: Agent Optimizer

- Optimizer Agent 读取反馈和回放结果。
- 生成策略变更提案。
- 自动跑回放验证。
- 用户批准后合并参数。

## 风险和约束

- 盘前价格和竞价信息变化快，盘前计划必须带触发条件和放弃条件。
- 数据源偶发失败时，不能用缺失数据生成过度确定的推荐。
- 第一版没有真实胜率模型，`expected_r` 是启发式估计，只能作为排序依据。
- 策略优化早期样本少，必须防止过拟合。
- 输出必须始终标记为候选交易计划，不应描述为确定性收益承诺。

## 验收标准

第一版设计落地后，应满足：

- 每个推荐都有入场区间、止损价、目标价、风险收益比和预期R。
- 每个推荐都有可展开的 `decision_trace`。
- 用户能看到未入选股票的过滤原因。
- 三种模式同时输出，并且来自同一套策略。
- 策略参数能通过配置调整。
- 推荐结果能绑定策略版本，支持后续回放。
- 用户反馈能结构化保存，为 Agent Loop 优化做准备。
