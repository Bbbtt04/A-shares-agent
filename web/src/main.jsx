import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Clock,
  FileText,
  Gauge,
  GitBranch,
  ListFilter,
  Newspaper,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Terminal,
} from 'lucide-react';
import {
  fetchObservabilityEvents,
  fetchObservabilityMetrics,
  fetchObservabilityTraces,
  fetchDecisionTraces,
  fetchHealth,
  fetchIntradayLatest,
  fetchMarketQuotes,
  fetchPremarketContext,
  fetchPremarketDebug,
  fetchPremarketLatest,
  fetchPremarketRagLatest,
  fetchRagDebug,
  fetchReport,
  fetchReports,
  fetchRiskApprovalQueue,
  fetchStockPage,
  runAll,
  runJob,
} from './api.js';
import AgentArchitecturePage from './AgentArchitecturePage.jsx';
import {
  CONSOLE_SECTIONS,
  PIPELINE_NODES,
  buildKnowledgeCards,
  buildOpsAuditCards,
  buildPipelineNodes,
} from './consoleInformationArchitecture.js';
import './styles.css';

const JOB_LABELS = Object.fromEntries(PIPELINE_NODES.map((item) => [item.id, item.title]));
const DEBUG_STEP_LABELS = {
  source_fetch: '源站抓取状态',
  crawled_documents: '全部爬取数据',
  raw_documents: '窗口内原始文档',
};
const A_STOCK_DATA_CATEGORY_LABELS = {
  theme_hotspot: '同花顺热点',
  stock_news: '个股新闻',
  announcement: '公告',
  quote_candidate: '盘前观察候选',
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function pageEyebrow(activePage) {
  return {
    console: 'Paper Trading',
    'premarket-debug': 'Premarket Debug',
    architecture: 'Architecture Map',
  }[activePage] || 'Paper Trading';
}

function pageTitle(activePage) {
  return {
    console: 'A股 Agent 控制台',
    'premarket-debug': '盘前信息 Agent 调试',
    architecture: '当前 Agent 分层功能说明',
  }[activePage] || 'A股 Agent 控制台';
}

function formatMs(ms) {
  if (!Number.isFinite(ms)) return '0 ms';
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function App() {
  const [health, setHealth] = useState(null);
  const [activePage, setActivePage] = useState('console');
  const [date, setDate] = useState(todayIso());
  const [results, setResults] = useState({});
  const [selectedJob, setSelectedJob] = useState('intraday');
  const [running, setRunning] = useState({});
  const [timers, setTimers] = useState({});
  const [reports, setReports] = useState([]);
  const [selectedReport, setSelectedReport] = useState('');
  const [reportText, setReportText] = useState('');
  const [market, setMarket] = useState({ quotes: [], notice: '', source: '' });
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastMarketRefresh, setLastMarketRefresh] = useState(null);
  const [stockPage, setStockPage] = useState(1);
  const [stockPageSize, setStockPageSize] = useState(50);
  const [stockSort, setStockSort] = useState('changepercent');
  const [stockAsc, setStockAsc] = useState(false);
  const [stockFilter, setStockFilter] = useState('');
  const [stocks, setStocks] = useState({ quotes: [], source: '', notice: '', has_next: false });
  const [stocksLoading, setStocksLoading] = useState(false);
  const [stocksError, setStocksError] = useState('');
  const [lastStockRefresh, setLastStockRefresh] = useState(null);
  const [premarket, setPremarket] = useState(null);
  const [premarketLoading, setPremarketLoading] = useState(false);
  const [premarketError, setPremarketError] = useState('');
  const [premarketDebug, setPremarketDebug] = useState(null);
  const [premarketDebugLoading, setPremarketDebugLoading] = useState(false);
  const [premarketDebugError, setPremarketDebugError] = useState('');
  const [premarketDebugQuery, setPremarketDebugQuery] = useState('机器人');
  const [selectedDebugStep, setSelectedDebugStep] = useState('raw_documents');
  const [intraday, setIntraday] = useState({ report: null, event: null });
  const [intradayLoading, setIntradayLoading] = useState(false);
  const [intradayError, setIntradayError] = useState('');
  const [observability, setObservability] = useState({
    events: [],
    traces: [],
    metrics: [],
    knowledgeResults: [],
    premarketContext: null,
    approvalQueue: [],
    decisionTimeline: [],
    ragDebug: null,
    premarketRag: null,
  });
  const [observabilityLoading, setObservabilityLoading] = useState(false);
  const [observabilityError, setObservabilityError] = useState('');
  const [knowledgeQuery, setKnowledgeQuery] = useState('机器人');
  const [decisionQuery, setDecisionQuery] = useState('');
  const startedAtRef = useRef({});

  const refreshMarket = useCallback(async () => {
    setMarketLoading(true);
    setMarketError('');
    try {
      const data = await fetchMarketQuotes();
      setMarket(data);
      setLastMarketRefresh(new Date());
    } catch (error) {
      setMarketError(error.message);
    } finally {
      setMarketLoading(false);
    }
  }, []);

  const refreshReports = useCallback(async () => {
    const data = await fetchReports();
    setReports(data.reports);
    if (data.reports.length > 0 && !selectedReport) {
      setSelectedReport(data.reports[0].name);
    }
  }, [selectedReport]);

  const refreshStocks = useCallback(async () => {
    setStocksLoading(true);
    setStocksError('');
    try {
      const data = await fetchStockPage({
        page: stockPage,
        pageSize: stockPageSize,
        sort: stockSort,
        asc: stockAsc,
      });
      setStocks(data);
      setLastStockRefresh(new Date());
    } catch (error) {
      setStocksError(error.message);
    } finally {
      setStocksLoading(false);
    }
  }, [stockAsc, stockPage, stockPageSize, stockSort]);

  const refreshPremarket = useCallback(async () => {
    setPremarketLoading(true);
    setPremarketError('');
    try {
      const data = await fetchPremarketLatest();
      setPremarket(data.report);
    } catch (error) {
      setPremarketError(error.message);
    } finally {
      setPremarketLoading(false);
    }
  }, []);

  const refreshPremarketDebug = useCallback(async () => {
    setPremarketDebugLoading(true);
    setPremarketDebugError('');
    try {
      const data = await fetchPremarketDebug({
        tradingDay: date,
        q: premarketDebugQuery || '盘前',
        limit: 200,
      });
      setPremarketDebug(data);
      setSelectedDebugStep((current) => (
        data.steps?.some((step) => step.id === current)
          ? current
          : data.steps?.[0]?.id || 'raw_documents'
      ));
    } catch (error) {
      setPremarketDebugError(error.message);
    } finally {
      setPremarketDebugLoading(false);
    }
  }, [date, premarketDebugQuery]);

  const refreshIntraday = useCallback(async () => {
    setIntradayLoading(true);
    setIntradayError('');
    try {
      const data = await fetchIntradayLatest();
      setIntraday(data);
    } catch (error) {
      setIntradayError(error.message);
    } finally {
      setIntradayLoading(false);
    }
  }, []);

  const refreshObservability = useCallback(async () => {
    setObservabilityLoading(true);
    setObservabilityError('');
    try {
      const [
        eventsData,
        tracesData,
        metricsData,
        contextData,
        approvalData,
        decisionData,
        ragDebugData,
        premarketRagData,
      ] = await Promise.all([
        fetchObservabilityEvents(),
        fetchObservabilityTraces(),
        fetchObservabilityMetrics(),
        fetchPremarketContext(),
        fetchRiskApprovalQueue(),
        fetchDecisionTraces({ intentId: decisionQuery.trim() }),
        fetchRagDebug({ q: knowledgeQuery || '盘前', tradingDay: date }),
        fetchPremarketRagLatest(),
      ]);
      setObservability({
        events: eventsData.events || [],
        traces: tracesData.traces || [],
        metrics: metricsData.metrics || [],
        knowledgeResults: ragDebugData.results || [],
        premarketContext: contextData.context || null,
        approvalQueue: approvalData.queue || [],
        decisionTimeline: decisionData.timeline || [],
        ragDebug: ragDebugData,
        premarketRag: premarketRagData,
      });
    } catch (error) {
      setObservabilityError(error.message);
    } finally {
      setObservabilityLoading(false);
    }
  }, [date, decisionQuery, knowledgeQuery]);

  useEffect(() => {
    fetchHealth().then(setHealth).catch((error) => {
      setHealth({ status: 'failed', error: error.message });
    });
  }, []);

  useEffect(() => {
    refreshReports().catch(() => {});
  }, [refreshReports]);

  useEffect(() => {
    refreshMarket().catch(() => {});
  }, [refreshMarket]);

  useEffect(() => {
    refreshPremarket().catch(() => {});
  }, [refreshPremarket]);

  useEffect(() => {
    refreshPremarketDebug().catch(() => {});
  }, [refreshPremarketDebug]);

  useEffect(() => {
    refreshIntraday().catch(() => {});
  }, [refreshIntraday]);

  useEffect(() => {
    refreshObservability().catch(() => {});
  }, [refreshObservability]);

  useEffect(() => {
    refreshStocks().catch(() => {});
  }, [refreshStocks]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const interval = window.setInterval(() => {
      refreshMarket().catch(() => {});
      refreshStocks().catch(() => {});
    }, 10000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, refreshMarket, refreshStocks]);

  useEffect(() => {
    if (!selectedReport) return;
    fetchReport(selectedReport).then(setReportText).catch((error) => {
      setReportText(error.message);
    });
  }, [selectedReport]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const next = {};
      for (const [job, startedAt] of Object.entries(startedAtRef.current)) {
        next[job] = performance.now() - startedAt;
      }
      setTimers(next);
    }, 100);
    return () => window.clearInterval(interval);
  }, []);

  const executeJob = useCallback(async (job) => {
    setSelectedJob(job);
    setRunning((current) => ({ ...current, [job]: true }));
    startedAtRef.current[job] = performance.now();
    try {
      const result = await runJob(job, date);
      setResults((current) => ({ ...current, [job]: result }));
      if (job === 'premarket') {
        await refreshPremarket();
        await refreshObservability();
        await refreshPremarketDebug();
      }
      if (job === 'intraday') {
        await refreshIntraday();
        await refreshObservability();
      }
      if (job === 'review') {
        await refreshReports();
      }
    } catch (error) {
      setResults((current) => ({
        ...current,
        [job]: {
          job,
          label: JOB_LABELS[job] || job,
          status: 'failed',
          elapsed_ms: Math.round(performance.now() - startedAtRef.current[job]),
          stdout: '',
          stderr: error.message,
          parsed: null,
        },
      }));
    } finally {
      delete startedAtRef.current[job];
      setRunning((current) => ({ ...current, [job]: false }));
      setTimers((current) => ({ ...current, [job]: 0 }));
    }
  }, [date, refreshIntraday, refreshObservability, refreshPremarket, refreshPremarketDebug, refreshReports]);

  const executeAll = useCallback(async () => {
    const allKey = 'all';
    setSelectedJob('all');
    setRunning((current) => ({ ...current, [allKey]: true }));
    startedAtRef.current[allKey] = performance.now();
    try {
      const response = await runAll(date);
      const nextResults = {};
      for (const result of response.results) {
        nextResults[result.job] = result;
      }
      nextResults.all = {
        job: 'all',
        label: '完整链路',
        status: response.status,
        elapsed_ms: response.elapsed_ms,
        stdout: JSON.stringify(response.results.map((item) => ({
          job: item.job,
          status: item.status,
          elapsed_ms: item.elapsed_ms,
        })), null, 2),
        stderr: '',
        parsed: response,
      };
      setResults((current) => ({ ...current, ...nextResults }));
      await refreshPremarket();
      await refreshPremarketDebug();
      await refreshIntraday();
      await refreshReports();
      await refreshObservability();
    } catch (error) {
      setResults((current) => ({
        ...current,
        all: {
          job: 'all',
          label: '完整链路',
          status: 'failed',
          elapsed_ms: Math.round(performance.now() - startedAtRef.current[allKey]),
          stdout: '',
          stderr: error.message,
          parsed: null,
        },
      }));
    } finally {
      delete startedAtRef.current[allKey];
      setRunning((current) => ({ ...current, [allKey]: false }));
      setTimers((current) => ({ ...current, [allKey]: 0 }));
    }
  }, [date, refreshIntraday, refreshObservability, refreshPremarket, refreshPremarketDebug, refreshReports]);

  useEffect(() => {
    const onKeyDown = (event) => {
      const mod = event.metaKey || event.ctrlKey;
      if (!mod) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        executeAll();
        return;
      }
      const map = { 1: 'intraday', 2: 'risk', 3: 'broker', 4: 'review', 5: 'premarket' };
      if (map[event.key]) {
        event.preventDefault();
        executeJob(map[event.key]);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [executeAll, executeJob]);

  const activeResult = selectedJob === 'all' ? results.all : results[selectedJob];
  const summary = useMemo(() => buildSummary(results), [results]);
  const pipelineNodes = useMemo(() => buildPipelineNodes({
    results,
    running,
    timers,
    premarket,
    intraday,
  }), [intraday, premarket, results, running, timers]);
  const knowledgeCards = useMemo(() => buildKnowledgeCards({
    observability,
  }), [observability]);
  const opsAuditCards = useMemo(() => buildOpsAuditCards({
    observability,
    reports,
  }), [observability, reports]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">{pageEyebrow(activePage)}</p>
          <h1>{pageTitle(activePage)}</h1>
        </div>
        <div className="top-actions">
          <div className="view-switch" aria-label="页面切换">
            <button
              className={activePage === 'console' ? 'active' : ''}
              type="button"
              onClick={() => setActivePage('console')}
            >
              控制台
            </button>
            <button
              className={activePage === 'premarket-debug' ? 'active' : ''}
              type="button"
              onClick={() => setActivePage('premarket-debug')}
            >
              盘前调试
            </button>
            <button
              className={activePage === 'architecture' ? 'active' : ''}
              type="button"
              onClick={() => setActivePage('architecture')}
            >
              架构说明
            </button>
          </div>
          <label className="date-field">
            <span>交易日</span>
            <input value={date} onChange={(event) => setDate(event.target.value)} type="date" />
          </label>
          <StatusPill health={health} />
        </div>
      </header>

      {activePage === 'architecture' ? (
        <AgentArchitecturePage />
      ) : activePage === 'premarket-debug' ? (
        <PremarketDebugPage
          data={premarketDebug}
          loading={premarketDebugLoading || Boolean(running.premarket)}
          error={premarketDebugError}
          query={premarketDebugQuery}
          selectedStep={selectedDebugStep}
          onQueryChange={setPremarketDebugQuery}
          onSelectStep={setSelectedDebugStep}
          onRefresh={refreshPremarketDebug}
          onRun={() => executeJob('premarket')}
        />
      ) : (
        <>
          <section className="status-grid">
            <Metric icon={Gauge} label="模式" value="paper" tone="blue" />
            <Metric icon={ShieldCheck} label="实盘交易" value="关闭" tone="green" />
            <Metric icon={AlertTriangle} label="人工确认" value="开启" tone="orange" />
            <Metric icon={Clock} label="最近耗时" value={formatMs(activeResult?.elapsed_ms || timers[selectedJob] || 0)} tone="gray" />
          </section>

          <TradingPipelineSection
            title={CONSOLE_SECTIONS.pipeline}
            nodes={pipelineNodes}
            selectedJob={selectedJob}
            activeResult={activeResult}
            running={running}
            timers={timers}
            reports={reports}
            selectedReport={selectedReport}
            reportText={reportText}
            onSelectJob={setSelectedJob}
            onRunJob={executeJob}
            onRunAll={executeAll}
            onSelectReport={setSelectedReport}
            onRefreshReports={refreshReports}
          />

          <PremarketPanel
            report={premarket}
            loading={premarketLoading || Boolean(running.premarket)}
            error={premarketError}
            onRefresh={refreshPremarket}
            onRun={() => executeJob('premarket')}
          />

          <MarketPanel
            market={market}
            loading={marketLoading}
            error={marketError}
            autoRefresh={autoRefresh}
            lastRefresh={lastMarketRefresh}
            onRefresh={refreshMarket}
            onToggleAuto={() => setAutoRefresh((value) => !value)}
          />

          <StockTapePanel
            data={stocks}
            loading={stocksLoading}
            error={stocksError}
            page={stockPage}
            pageSize={stockPageSize}
            sort={stockSort}
            asc={stockAsc}
            filter={stockFilter}
            lastRefresh={lastStockRefresh}
            onRefresh={refreshStocks}
            onPageChange={setStockPage}
            onPageSizeChange={(value) => {
              setStockPageSize(value);
              setStockPage(1);
            }}
            onSortChange={(value) => {
              setStockSort(value);
              setStockPage(1);
            }}
            onAscChange={setStockAsc}
            onFilterChange={setStockFilter}
          />

          <IntradayAnalysisPanel
            data={intraday}
            loading={intradayLoading || Boolean(running.intraday)}
            error={intradayError}
            onRefresh={refreshIntraday}
            onRun={() => executeJob('intraday')}
          />

          <PremarketKnowledgeSection
            title={CONSOLE_SECTIONS.knowledge}
            cards={knowledgeCards}
            data={observability}
            loading={observabilityLoading}
            error={observabilityError}
            query={knowledgeQuery}
            onQueryChange={setKnowledgeQuery}
            onRefresh={refreshObservability}
          />

          <OperationsAuditSection
            title={CONSOLE_SECTIONS.ops}
            cards={opsAuditCards}
            data={observability}
            loading={observabilityLoading}
            decisionQuery={decisionQuery}
            onDecisionQueryChange={setDecisionQuery}
            onRefresh={refreshObservability}
          />

          <section className="summary-strip">
            {summary.map((item) => (
              <div className="summary-item" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

function StatusPill({ health }) {
  const ok = health?.status === 'ok';
  return (
    <div className={`status-pill ${ok ? 'ok' : 'bad'}`}>
      {ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
      <span>{ok ? 'API 在线' : 'API 未连接'}</span>
    </div>
  );
}

function Metric({ icon: Icon, label, value, tone }) {
  return (
    <div className={`metric metric-${tone}`}>
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PremarketDebugPage({
  data,
  loading,
  error,
  query,
  selectedStep,
  onQueryChange,
  onSelectStep,
  onRefresh,
  onRun,
}) {
  const steps = data?.steps || [];
  const currentStep = steps.find((step) => step.id === selectedStep) || steps[0] || null;
  const currentStepLabel = currentStep?.label || DEBUG_STEP_LABELS[currentStep?.id] || '源站抓取状态';
  const conclusion = data?.conclusion || {};
  const knowledgeResults = data?.knowledge?.query_results || [];
  const ragPacks = data?.rag?.evidence?.payload?.packs || [];
  const evaluationSummary = data?.rag?.evaluation?.payload?.summary || {};
  const aStockData = data?.a_stock_data || {};
  const [expandedSourceKeys, setExpandedSourceKeys] = useState({});
  const isSourceFetchStep = currentStep?.id === 'source_fetch';
  const crawledItemsBySource = useMemo(() => {
    const crawledStep = steps.find((step) => step.id === 'crawled_documents');
    return (crawledStep?.items || []).reduce((groups, item) => {
      const source = debugSourceKey(item);
      if (!groups[source]) groups[source] = [];
      groups[source].push(item);
      return groups;
    }, {});
  }, [steps]);

  useEffect(() => {
    setExpandedSourceKeys({});
  }, [data?.trading_day]);

  const toggleSource = useCallback((sourceKey) => {
    setExpandedSourceKeys((current) => ({
      ...current,
      [sourceKey]: !current[sourceKey],
    }));
  }, []);

  return (
    <section className="premarket-debug-page">
      <div className="premarket-debug-toolbar">
        <div className="section-title">
          <Newspaper size={18} />
          <span>盘前信息 Agent 链路</span>
        </div>
        <div className="premarket-debug-actions">
          <label className="knowledge-search debug-query">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="查询知识库 / RAG"
            />
          </label>
          <button className="toggle-button" type="button" onClick={onRun} disabled={loading}>
            {loading ? '运行中' : '运行盘前分析'}
          </button>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新盘前调试">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      <div className="premarket-debug-grid">
        <aside className="debug-chain">
          {steps.length === 0 ? (
            <div className="panel-empty">暂无链路数据</div>
          ) : steps.map((step) => (
            <button
              className={`debug-step ${currentStep?.id === step.id ? 'active' : ''}`}
              type="button"
              key={step.id}
              onClick={() => onSelectStep(step.id)}
            >
              <span>{step.label || DEBUG_STEP_LABELS[step.id] || step.id}</span>
              <strong>{step.count}</strong>
              <small>{step.status}</small>
            </button>
          ))}
        </aside>
        <div className="debug-detail">
          <div className="debug-card-head">
            <h2>{currentStepLabel}</h2>
            <span>{currentStep?.topic || '-'}</span>
          </div>
          {currentStep?.metadata?.window_start || currentStep?.metadata?.window_end ? (
            <div className="debug-step-window">
              <span>窗口</span>
              <strong>
                {formatDateTime(currentStep.metadata.window_start)} {'->'} {formatDateTime(currentStep.metadata.window_end)}
              </strong>
            </div>
          ) : null}
          <ul className="debug-record-list">
            {(currentStep?.items || []).length === 0 ? (
              <li>暂无记录</li>
            ) : isSourceFetchStep ? currentStep.items.map((item, index) => {
              const sourceKey = debugSourceKey(item) || `source-${index}`;
              const itemsForSource = crawledItemsBySource[sourceKey] || [];
              const expanded = Boolean(expandedSourceKeys[sourceKey]);
              return (
                <li className={`debug-source-record ${expanded ? 'expanded' : ''}`} key={`${currentStep.id}-${sourceKey}`}>
                  <button
                    className="debug-source-toggle"
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => toggleSource(sourceKey)}
                  >
                    <span className="debug-source-main">
                      <strong>{debugItemTitle(item)}</strong>
                      <span>{debugItemSummary(item)}</span>
                      <code>{debugItemMeta(item)}</code>
                    </span>
                    <span className="debug-source-count">{itemsForSource.length} 条明细</span>
                    <ChevronDown className="debug-source-chevron" size={16} />
                  </button>
                  {expanded ? (
                    <div className="debug-source-detail" role="region" aria-label={`${sourceKey} 爬取明细`}>
                      {itemsForSource.length === 0 ? (
                        <p className="debug-source-empty">暂无爬取明细</p>
                      ) : (
                        <ul className="debug-source-items">
                          {itemsForSource.map((crawledItem, crawledIndex) => (
                            <li className="debug-source-item" key={`${sourceKey}-${crawledItem.url || crawledItem.title || crawledIndex}`}>
                              <strong className="debug-source-item-title">{debugItemTitle(crawledItem)}</strong>
                              <span className="debug-source-item-summary">{debugItemSummary(crawledItem)}</span>
                              <code className="debug-source-item-meta">{debugItemMeta(crawledItem)}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : null}
                </li>
              );
            }) : currentStep.items.map((item, index) => (
              <li key={`${currentStep.id}-${index}`}>
                <strong>{debugItemTitle(item)}</strong>
                <span>{debugItemSummary(item)}</span>
                <code>{debugItemMeta(item)}</code>
              </li>
            ))}
          </ul>
        </div>
        <aside className="debug-side">
          <article className="debug-side-card">
            <h2>最终结论</h2>
            <div className="context-strip">
              <span>{viewLabel(conclusion.market_view)}</span>
              <span>观察 {conclusion.watchlist?.length || 0}</span>
              <span>禁入 {conclusion.avoid_list?.length || 0}</span>
            </div>
            <p>{conclusion.summary || '暂无盘前报告'}</p>
          </article>
          <article className="debug-side-card debug-a-stock-data-card">
            <h2>a-stock-data 数据包</h2>
            <div className="context-strip">
              <span>{aStockData.enabled ? '已启用' : '未启用'}</span>
              <span>{aStockData.status || '-'}</span>
              <span>{aStockData.in_window_count || 0}/{aStockData.crawled_count || 0} 入窗</span>
            </div>
            <div className="debug-a-stock-data-grid">
              {Object.entries(A_STOCK_DATA_CATEGORY_LABELS).map(([category, label]) => (
                <span key={category}>
                  <strong>{aStockData.category_counts?.[category] || 0}</strong>
                  {label}
                </span>
              ))}
            </div>
            <p>{(aStockData.symbols || []).length > 0 ? `配置标的：${aStockData.symbols.join('、')}` : '未配置盘前标的'}</p>
          </article>
          <article className="debug-side-card">
            <h2>落入知识库</h2>
            <div className="context-strip">
              <span>{data?.knowledge?.record_count || 0} 条记录</span>
              <span>{knowledgeResults.length} 条命中</span>
            </div>
            <ul className="trace-list">
              {knowledgeResults.length === 0 ? <li>暂无查询结果</li> : knowledgeResults.slice(0, 5).map((item) => (
                <li key={item.record.record_id}>
                  <strong>{item.record.title}</strong>
                  <span>{item.record.record_type} · score {formatScore(item.score)}</span>
                </li>
              ))}
            </ul>
          </article>
          <article className="debug-side-card">
            <h2>RAG 证据包</h2>
            <div className="context-strip">
              <span>{ragPacks.length} packs</span>
              <span>覆盖 {formatPercentNumber(evaluationSummary.avg_evidence_coverage_ratio)}</span>
              <span>引用 {formatPercentNumber(evaluationSummary.avg_citation_coverage_ratio)}</span>
            </div>
            <ul className="trace-list">
              {ragPacks.length === 0 ? <li>暂无 evidence pack</li> : ragPacks.slice(0, 5).map((pack) => (
                <li key={pack.pack_id || pack.section}>
                  <strong>{sectionLabel(pack.section)}</strong>
                  <span>{(pack.items || []).length} 条证据 · token {pack.token_estimate || 0}</span>
                </li>
              ))}
            </ul>
          </article>
        </aside>
      </div>
    </section>
  );
}

function TradingPipelineSection({
  title,
  nodes,
  selectedJob,
  activeResult,
  running,
  timers,
  reports,
  selectedReport,
  reportText,
  onSelectJob,
  onRunJob,
  onRunAll,
  onSelectReport,
  onRefreshReports,
}) {
  return (
    <section className="pipeline-section">
      <div className="pipeline-header">
        <div className="section-title">
          <BarChart3 size={18} />
          <span>{title}</span>
        </div>
        <button className="run-all compact-run" type="button" onClick={onRunAll} disabled={running.all}>
          {running.all ? <RefreshCw className="spin" size={18} /> : <Play size={18} />}
          <span>运行完整链路</span>
          <kbd>Ctrl Enter</kbd>
        </button>
      </div>
      <div className="pipeline-flow">
        {nodes.map((node, index) => (
          <React.Fragment key={node.id}>
            <PipelineNode
              node={node}
              selected={selectedJob === node.id}
              onSelect={() => onSelectJob(node.id)}
              onRun={() => onRunJob(node.id)}
            />
            {index < nodes.length - 1 ? <span className="pipeline-arrow">-&gt;</span> : null}
          </React.Fragment>
        ))}
      </div>
      <div className="pipeline-detail-grid">
        <div className="output-panel pipeline-output">
          <div className="section-title">
            <Terminal size={18} />
            <span>节点输出</span>
          </div>
          <OutputView result={activeResult} running={Boolean(running[selectedJob])} elapsed={timers[selectedJob]} />
        </div>
        <div className="report-panel pipeline-report">
          <div className="section-title">
            <FileText size={18} />
            <span>报告预览</span>
          </div>
          <div className="report-select-row">
            <select value={selectedReport} onChange={(event) => onSelectReport(event.target.value)}>
              <option value="">无报告</option>
              {reports.map((report) => (
                <option key={report.name} value={report.name}>{report.name}</option>
              ))}
            </select>
            <button className="icon-button" type="button" onClick={onRefreshReports} aria-label="刷新报告">
              <RefreshCw size={16} />
            </button>
          </div>
          <pre className="report-preview">{reportText || '暂无报告'}</pre>
        </div>
      </div>
    </section>
  );
}

function PipelineNode({ node, selected, onSelect, onRun }) {
  return (
    <article className={`pipeline-node ${selected ? 'selected' : ''}`}>
      <button className="pipeline-node-main" type="button" onClick={onSelect}>
        <span className={`role-badge role-${node.role.toLowerCase()}`}>{node.role}</span>
        <strong>{node.title}</strong>
        <small>{node.module}</small>
      </button>
      <p>{node.summary}</p>
      <div className="pipeline-node-meta">
        <span className={`pipeline-state state-${node.statusText}`}>{node.statusText}</span>
        <span>{node.outputLabel}: {node.outputValue}</span>
      </div>
      <button className="job-run pipeline-run" type="button" onClick={onRun} disabled={node.statusText === '运行中'}>
        <Play size={16} />
        <kbd>{node.hint}</kbd>
      </button>
    </article>
  );
}

function ModuleStatusCards({ cards }) {
  return (
    <div className="module-status-grid">
      {cards.map((card) => (
        <article className="module-status-card" key={card.id}>
          <div>
            <strong>{card.title}</strong>
            <span className={`module-status ${statusClassName(card.status)}`}>{card.status}</span>
          </div>
          <p>{card.detail}</p>
          <small>{card.metric}</small>
        </article>
      ))}
    </div>
  );
}

function PremarketPanel({ report, loading, error, onRefresh, onRun }) {
  const catalysts = report?.catalysts || [];
  const watchlist = report?.watchlist || [];
  const avoidList = report?.avoid_list || [];
  const sourceStatus = report?.source_status || [];
  const tone = report?.market_view || 'empty';
  return (
    <section className={`premarket-panel premarket-${tone}`}>
      <div className="premarket-header">
        <div className="section-title">
          <Newspaper size={18} />
          <span>盘前消息分析</span>
        </div>
        <div className="premarket-actions">
          <button className="toggle-button" type="button" onClick={onRun} disabled={loading}>
            {loading ? '分析中' : '运行盘前 Agent'}
          </button>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新盘前简报">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      {report ? (
        <>
          <div className="premarket-summary">
            <div>
              <span>盘前结论</span>
              <strong>{viewLabel(report.market_view)}</strong>
            </div>
            <div>
              <span>观察</span>
              <strong>{watchlist.length}</strong>
            </div>
            <div>
              <span>禁入</span>
              <strong>{avoidList.length}</strong>
            </div>
            <div>
              <span>消息</span>
              <strong>{report.news_items?.length || 0}</strong>
            </div>
          </div>
          <p className="premarket-lead">{report.summary}</p>
          <div className="premarket-meta">
            <span>窗口：{formatDateTime(report.window_start)} {'->'} {formatDateTime(report.window_end)}</span>
            <span>生成：{formatDateTime(report.generated_at)}</span>
          </div>
          <div className="premarket-layout">
            <div className="premarket-column">
              <h2>重点催化</h2>
              <ul className="premarket-list">
                {catalysts.length === 0 ? <li>暂无可交易级别催化</li> : catalysts.slice(0, 5).map((item) => (
                  <li key={`${item.title}-${item.importance}`}>
                    <strong>{item.importance}/{biasLabel(item.bias)}</strong>
                    <span>{item.title}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="premarket-column">
              <h2>观察清单</h2>
              <ul className="premarket-list">
                {watchlist.length === 0 ? <li>暂无</li> : watchlist.map((item) => (
                  <li key={item.symbol}>
                    <strong>{item.symbol}</strong>
                    <span>{item.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="premarket-column">
              <h2>源状态</h2>
              <ul className="premarket-list compact">
                {sourceStatus.length === 0 ? <li>尚未生成报告</li> : sourceStatus.map((item) => (
                  <li key={item.source}>
                    <strong className={`source-${item.status}`}>{item.status}</strong>
                    <span>{item.source} used {item.used_count}/{item.fetched_count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          {report.warnings?.length ? (
            <div className="premarket-warning">{report.warnings.join('；')}</div>
          ) : null}
        </>
      ) : (
        <div className="premarket-empty">还没有盘前简报，点击运行盘前 Agent 生成。</div>
      )}
    </section>
  );
}

function IntradayAnalysisPanel({ data, loading, error, onRefresh, onRun }) {
  const report = data?.report;
  const event = data?.event;
  const symbols = [...(report?.symbols || [])].sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  const themes = report?.themes || [];
  const filteredSignals = symbols.flatMap((symbol) => (
    (symbol.signals || [])
      .filter((signal) => signal.status === 'filtered')
      .map((signal) => ({ ...signal, symbol: symbol.symbol }))
  ));
  return (
    <section className="intraday-panel">
      <div className="intraday-header">
        <div className="section-title">
          <Activity size={18} />
          <span>盘中分析</span>
        </div>
        <div className="intraday-actions">
          <button className="toggle-button" type="button" onClick={onRun} disabled={loading}>
            {loading ? '扫描中' : '运行盘中 Agent'}
          </button>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新盘中分析">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      {report ? (
        <>
          <div className="intraday-summary">
            <div>
              <span>市场状态</span>
              <strong>{report.market_state?.risk_mode || '-'}</strong>
            </div>
            <div>
              <span>行情质量</span>
              <strong>{report.market_state?.data_quality || '-'}</strong>
            </div>
            <div>
              <span>交易意图</span>
              <strong>{report.trade_intent_count || 0}</strong>
            </div>
            <div>
              <span>覆盖标的</span>
              <strong>{report.symbol_count || 0}</strong>
            </div>
          </div>
          <p className="intraday-lead">{report.summary}</p>
          <div className="intraday-meta">
            <span>事件：{event?.event_id || '-'}</span>
            <span>交易日：{event?.trading_day || '-'}</span>
            <span>生成：{formatDateTime(report.generated_at || event?.created_at)}</span>
          </div>
          <div className="intraday-layout">
            <div className="intraday-card">
              <h2>市场判断</h2>
              <ul className="trace-list">
                {(report.market_state?.reasons || []).length === 0 ? (
                  <li>暂无额外市场约束</li>
                ) : report.market_state.reasons.map((reason) => (
                  <li key={reason}>
                    <strong>{report.market_state.regime || 'market'}</strong>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="intraday-card">
              <h2>重点板块</h2>
              <ul className="trace-list">
                {themes.length === 0 ? <li>暂无板块聚合</li> : themes.slice(0, 5).map((theme) => (
                  <li key={theme.theme_name}>
                    <strong>{theme.theme_name} · {formatScore(theme.avg_score)}</strong>
                    <span>{theme.symbols?.join(', ') || '-'} · 强度 {formatPercentValue(theme.avg_theme_strength)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="intraday-card">
              <h2>候选信号</h2>
              <ul className="trace-list">
                {symbols.filter((item) => item.signals?.length).length === 0 ? <li>暂无策略候选</li> : symbols
                  .filter((item) => item.signals?.length)
                  .slice(0, 5)
                  .map((item) => (
                    <li key={item.symbol}>
                      <strong>{item.symbol} · {statusLabel(item.status)}</strong>
                      <span>{item.signals[0].strategy_id} · {formatScore(item.signals[0].confidence)}</span>
                    </li>
                  ))}
              </ul>
            </div>
            <div className="intraday-card">
              <h2>过滤原因</h2>
              <ul className="trace-list">
                {filteredSignals.length === 0 ? <li>暂无被过滤信号</li> : filteredSignals.slice(0, 5).map((signal) => (
                  <li key={signal.signal_id}>
                    <strong>{signal.symbol} · {signal.filter_reason}</strong>
                    <span>{signal.reasons?.join(' / ') || '-'}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="intraday-table-wrap">
            <table className="intraday-table">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>状态</th>
                  <th className="number">评分</th>
                  <th className="number">价格</th>
                  <th className="number">5分钟</th>
                  <th className="number">量比</th>
                  <th>板块</th>
                  <th>关键原因</th>
                </tr>
              </thead>
              <tbody>
                {symbols.length === 0 ? (
                  <tr>
                    <td className="stock-empty-row" colSpan="8">{loading ? '正在扫描' : '暂无盘中分析'}</td>
                  </tr>
                ) : symbols.map((symbol) => (
                  <IntradaySymbolRow key={symbol.symbol} symbol={symbol} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="premarket-empty">还没有盘中分析，点击运行盘中 Agent 生成。</div>
      )}
    </section>
  );
}

function IntradaySymbolRow({ symbol }) {
  return (
    <tr>
      <td><strong>{symbol.symbol}</strong></td>
      <td><span className={`intraday-status status-${symbol.status}`}>{statusLabel(symbol.status)}</span></td>
      <td className="number">{formatScore(symbol.score)}</td>
      <td className="number">{formatPrice(symbol.last_price)}</td>
      <td className="number">{formatPercentValue(symbol.features?.return_5m)}</td>
      <td className="number">{formatPlain(symbol.features?.volume_ratio_5m)}</td>
      <td>{symbol.features?.primary_theme || '-'}</td>
      <td className="intraday-reason">{symbol.reasons?.[0] || '-'}</td>
    </tr>
  );
}

function PremarketKnowledgeSection({ title, cards, data, loading, error, query, onQueryChange, onRefresh }) {
  const context = data.premarketContext;
  const constraints = context?.constraints || [];
  const ragDebug = data.ragDebug;
  const knowledgeResults = data.knowledgeResults.slice(0, 6);
  const premarketRag = data.premarketRag || {};
  const evidencePayload = premarketRag.evidence?.payload || {};
  const evaluationPayload = premarketRag.evaluation?.payload || {};
  const packs = evidencePayload.packs || [];
  const evaluationSummary = evaluationPayload.summary || {};
  const citationItems = packs.flatMap((pack) => (
    (pack.items || []).map((item) => ({ ...item, section: pack.section }))
  )).slice(0, 5);
  return (
    <section className="observability-panel">
      <div className="observability-header">
        <div className="section-title">
          <GitBranch size={18} />
          <span>{title}</span>
        </div>
        <div className="observability-actions">
          <label className="knowledge-search">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="检索证据，如 机器人 / 半导体"
            />
          </label>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新观测数据">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      <ModuleStatusCards cards={cards} />
      <div className="observability-grid">
        <div className="observability-card">
          <h2>Premarket Context</h2>
          {context ? (
            <>
              <div className="context-strip">
                <span>{viewLabel(context.market_view)}</span>
                <span>确认 {context.confirmed_themes?.length || 0}</span>
                <span>失败 {context.failed_themes?.length || 0}</span>
              </div>
              <ul className="trace-list">
                {constraints.length === 0 ? <li>暂无盘前约束</li> : constraints.slice(0, 5).map((item) => (
                  <li key={`${item.instruction_type}-${item.target}-${item.reason}`}>
                    <strong>{item.instruction_type} · {item.target}</strong>
                    <span>{item.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div className="panel-empty">暂无盘前上下文</div>
          )}
        </div>
        <div className="observability-card">
          <h2>RAG Search</h2>
          <ul className="trace-list">
            {knowledgeResults.length === 0 ? <li>暂无检索结果</li> : knowledgeResults.map((item) => (
              <li key={item.record.record_id}>
                <strong>{item.record.title}</strong>
                <span>{item.record.source || item.record.source_rank} · score {Number(item.score).toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="observability-card rag-pack-card">
          <h2>Evidence Packs</h2>
          <div className="rag-pack-strip">
            <span>{evidencePayload.pack_count || packs.length || 0} packs</span>
            <span>覆盖 {formatPercentNumber(evaluationSummary.avg_evidence_coverage_ratio)}</span>
            <span>引用 {formatPercentNumber(evaluationSummary.avg_citation_coverage_ratio)}</span>
            <span>{evidencePayload.token_estimate || evaluationSummary.token_count || 0} tokens</span>
          </div>
          <ul className="trace-list">
            {packs.length === 0 ? <li>暂无 evidence pack</li> : packs.slice(0, 6).map((pack) => (
              <li key={pack.pack_id || pack.section}>
                <strong>{sectionLabel(pack.section)} · {(pack.items || []).length} 条</strong>
                <span>
                  dup {pack.dropped_duplicates || 0} · token {pack.token_estimate || 0} · hit {pack.coverage?.evidence_count || 0}/{pack.coverage?.result_count || 0}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="observability-card rag-pack-card">
          <h2>Citations</h2>
          <div className="rag-pack-strip">
            <span>来源均值 {formatScore(evaluationSummary.avg_source_rank)}</span>
            <span>重复 {formatPercentNumber(evaluationSummary.avg_duplicate_ratio)}</span>
          </div>
          <ul className="trace-list rag-citation-list">
            {citationItems.length === 0 ? <li>暂无 citation</li> : citationItems.map((item) => (
              <li key={`${item.section}-${item.evidence_id}`}>
                <strong>{item.citation_label || `[${item.evidence_id}]`} {item.title}</strong>
                <span>{sectionLabel(item.section)} · source {formatScore(item.source_rank)} · {item.source || item.source_type}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="observability-card">
          <h2>RAG Debug</h2>
          <div className="context-strip">
            <span>{ragDebug?.result_count || 0} 条</span>
            <span>{ragDebug?.query?.q || '-'}</span>
          </div>
          <ul className="trace-list">
            {(ragDebug?.results || []).length === 0 ? <li>暂无证据</li> : ragDebug.results.slice(0, 5).map((item) => (
              <li key={item.record.record_id}>
                <strong>{item.record.title}</strong>
                <span>{item.record.source_rank} · {item.record.themes?.join(', ') || '-'}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function OperationsAuditSection({ title, cards, data, loading, decisionQuery, onDecisionQueryChange, onRefresh }) {
  const metricSummary = useMemo(() => summarizeMetrics(data.metrics), [data.metrics]);
  const latestEvents = data.events.slice(0, 8);
  const latestTraces = data.traces.slice(-8).reverse();
  const approvals = data.approvalQueue || [];
  const timeline = data.decisionTimeline || [];
  return (
    <section className="decision-panel">
      <div className="decision-header">
        <div className="section-title">
          <ShieldCheck size={18} />
          <span>{title}</span>
        </div>
        <div className="decision-actions">
          <label className="decision-search">
            <Search size={16} />
            <input
              value={decisionQuery}
              onChange={(event) => onDecisionQueryChange(event.target.value)}
              placeholder="按 intent_id 过滤 timeline"
            />
          </label>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新决策数据">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      <ModuleStatusCards cards={cards} />
      <div className="decision-grid">
        <div className="decision-card">
          <h2>Event Stream</h2>
          <ul className="trace-list">
            {latestEvents.length === 0 ? <li>暂无事件</li> : latestEvents.map((event) => (
              <li key={event.event_id}>
                <strong>{event.topic}</strong>
                <span>{event.producer} · {event.run_id || '-'}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="decision-card">
          <h2>Trace Timeline</h2>
          <ul className="trace-list">
            {latestTraces.length === 0 ? <li>暂无 trace</li> : latestTraces.map((trace) => (
              <li key={trace.trace_id}>
                <strong className={`trace-${trace.status}`}>{trace.step}</strong>
                <span>{trace.agent} · {formatMs(trace.duration_ms)} · {trace.decision_summary || trace.status}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="decision-card">
          <h2>Metrics</h2>
          <div className="metric-mini-grid">
            {metricSummary.map((item) => (
              <div key={item.name}>
                <span>{item.name}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        </div>
        <div className="decision-card">
          <h2>Approval Queue</h2>
          <ul className="trace-list">
            {approvals.length === 0 ? <li>暂无人工审批项</li> : approvals.slice(0, 6).map((item) => (
              <li key={item.event_id || item.decision?.decision_id}>
                <strong>{item.intent?.symbol || '-'} · {item.decision?.decision || '-'}</strong>
                <span>{item.decision?.reason || item.premarket?.matched_instruction_types?.join(', ') || '-'}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="decision-card">
          <h2>Decision Timeline</h2>
          <ul className="trace-list">
            {timeline.length === 0 ? <li>暂无决策事件</li> : timeline.slice(0, 6).map((item) => (
              <li key={item.event_id}>
                <strong>{item.topic}</strong>
                <span>{item.intent_id || '-'} · {item.producer} · {formatDateTime(item.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function MarketPanel({ market, loading, error, autoRefresh, lastRefresh, onRefresh, onToggleAuto }) {
  const indexes = market.quotes.filter((quote) => quote.kind === 'index');
  const watchlist = market.quotes.filter((quote) => quote.kind !== 'index');
  return (
    <section className="market-panel">
      <div className="market-header">
        <div className="section-title">
          <TrendingUp size={18} />
          <span>大盘与实时价格</span>
        </div>
        <div className="market-actions">
          <span className="market-note">{market.notice || '公开行情接口仅用于监控'}</span>
          <button className={`toggle-button ${autoRefresh ? 'on' : ''}`} type="button" onClick={onToggleAuto}>
            {autoRefresh ? '自动刷新 10s' : '自动刷新关'}
          </button>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新行情">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      <div className="market-meta">
        <span>来源：{market.source || '-'}</span>
        <span>刷新：{lastRefresh ? lastRefresh.toLocaleTimeString() : '-'}</span>
      </div>
      <div className="quote-layout">
        <QuoteGroup title="大盘指数" quotes={indexes} />
        <QuoteGroup title="Watchlist" quotes={watchlist} compact />
      </div>
    </section>
  );
}

function QuoteGroup({ title, quotes, compact = false }) {
  return (
    <div className="quote-group">
      <h2>{title}</h2>
      <div className={compact ? 'quote-list compact' : 'quote-list'}>
        {quotes.length === 0 ? (
          <div className="quote-empty">暂无行情</div>
        ) : quotes.map((quote) => (
          <QuoteCard key={quote.symbol} quote={quote} />
        ))}
      </div>
    </div>
  );
}

function QuoteCard({ quote }) {
  const up = Number(quote.change_pct || 0) >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <article className="quote-card">
      <div className="quote-title">
        <div>
          <strong>{quote.name}</strong>
          <span>{quote.symbol}</span>
        </div>
        <Icon className={up ? 'quote-up' : 'quote-down'} size={18} />
      </div>
      <div className="quote-price-row">
        <span className="quote-price">{formatPrice(quote.price)}</span>
        <span className={up ? 'quote-change up' : 'quote-change down'}>
          {formatSigned(quote.change)} / {formatSigned(quote.change_pct)}%
        </span>
      </div>
      <div className="quote-subgrid">
        <span>开 {formatPrice(quote.open)}</span>
        <span>高 {formatPrice(quote.high)}</span>
        <span>低 {formatPrice(quote.low)}</span>
        <span>延迟 {formatDelay(quote.delay_seconds)}</span>
      </div>
    </article>
  );
}

function StockTapePanel({
  data,
  loading,
  error,
  page,
  pageSize,
  sort,
  asc,
  filter,
  lastRefresh,
  onRefresh,
  onPageChange,
  onPageSizeChange,
  onSortChange,
  onAscChange,
  onFilterChange,
}) {
  const normalizedFilter = filter.trim().toLowerCase();
  const visibleQuotes = useMemo(() => {
    if (!normalizedFilter) return data.quotes;
    return data.quotes.filter((quote) => (
      quote.code.toLowerCase().includes(normalizedFilter)
      || quote.symbol.toLowerCase().includes(normalizedFilter)
      || quote.name.toLowerCase().includes(normalizedFilter)
    ));
  }, [data.quotes, normalizedFilter]);

  return (
    <section className="stock-panel">
      <div className="stock-header">
        <div className="section-title">
          <ListFilter size={18} />
          <span>全 A 个股行情</span>
        </div>
        <div className="stock-actions">
          <label className="stock-search">
            <Search size={16} />
            <input
              value={filter}
              onChange={(event) => onFilterChange(event.target.value)}
              placeholder="当前页搜索代码/名称"
            />
          </label>
          <select value={sort} onChange={(event) => onSortChange(event.target.value)} aria-label="排序字段">
            <option value="changepercent">涨跌幅</option>
            <option value="trade">最新价</option>
            <option value="amount">成交额</option>
            <option value="volume">成交量</option>
            <option value="turnoverratio">换手率</option>
            <option value="symbol">代码</option>
          </select>
          <button className="toggle-button" type="button" onClick={() => onAscChange(!asc)}>
            {asc ? '升序' : '降序'}
          </button>
          <select
            value={pageSize}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            aria-label="每页数量"
          >
            <option value={20}>20/页</option>
            <option value={50}>50/页</option>
            <option value={100}>100/页</option>
          </select>
          <button className="icon-button refresh-button" type="button" onClick={onRefresh} disabled={loading} aria-label="刷新个股行情">
            <RefreshCw className={loading ? 'spin' : ''} size={16} />
          </button>
        </div>
      </div>
      {error ? <div className="market-error">{error}</div> : null}
      <div className="stock-meta">
        <span>来源：{data.source || '-'}</span>
        <span>页码：{page}</span>
        <span>刷新：{lastRefresh ? lastRefresh.toLocaleTimeString() : '-'}</span>
        <span>{data.notice || '公开行情接口仅用于监控'}</span>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>市场</th>
              <th className="number">最新</th>
              <th className="number">涨跌幅</th>
              <th className="number">涨跌额</th>
              <th className="number">成交额</th>
              <th className="number">换手</th>
              <th className="number">PE</th>
              <th className="number">PB</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {visibleQuotes.length === 0 ? (
              <tr>
                <td className="stock-empty-row" colSpan="11">{loading ? '正在拉取行情' : '暂无个股行情'}</td>
              </tr>
            ) : visibleQuotes.map((quote) => (
              <StockRow key={quote.symbol} quote={quote} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="stock-pager">
        <button className="pager-button" type="button" onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page <= 1 || loading}>
          <ChevronLeft size={16} />
          <span>上一页</span>
        </button>
        <span>{visibleQuotes.length} / {data.quotes.length} 条</span>
        <button className="pager-button" type="button" onClick={() => onPageChange(page + 1)} disabled={!data.has_next || loading}>
          <span>下一页</span>
          <ChevronRight size={16} />
        </button>
      </div>
    </section>
  );
}

function StockRow({ quote }) {
  const up = Number(quote.change_pct || 0) >= 0;
  return (
    <tr>
      <td><strong>{quote.code}</strong></td>
      <td>{quote.name}</td>
      <td>{quote.market}</td>
      <td className="number">{formatPrice(quote.price)}</td>
      <td className={`number ${up ? 'quote-up' : 'quote-down'}`}>{formatSigned(quote.change_pct)}%</td>
      <td className={`number ${up ? 'quote-up' : 'quote-down'}`}>{formatSigned(quote.change)}</td>
      <td className="number">{formatAmount(quote.amount)}</td>
      <td className="number">{formatRatio(quote.turnover_ratio)}</td>
      <td className="number">{formatPlain(quote.pe)}</td>
      <td className="number">{formatPlain(quote.pb)}</td>
      <td>{quote.tick_time || '-'}</td>
    </tr>
  );
}

function formatPrice(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toFixed(Number(value) > 100 ? 2 : 3);
}

function formatSigned(value) {
  if (value === null || value === undefined) return '-';
  const number = Number(value);
  return `${number >= 0 ? '+' : ''}${number.toFixed(2)}`;
}

function formatDelay(value) {
  if (value === null || value === undefined) return '-';
  if (value < 60) return `${value}s`;
  return `${Math.round(value / 60)}m`;
}

function viewLabel(value) {
  return { positive: '偏积极', neutral: '中性', cautious: '谨慎' }[value] || '-';
}

function biasLabel(value) {
  return { bullish: '利好', bearish: '利空', neutral: '中性', unclear: '不明' }[value] || value;
}

function formatDateTime(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function formatRatio(value) {
  if (value === null || value === undefined) return '-';
  return `${Number(value).toFixed(2)}%`;
}

function formatPercentValue(value) {
  if (value === null || value === undefined || value === '') return '-';
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatPercentNumber(value) {
  if (value === null || value === undefined || value === '') return '-';
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function formatPlain(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toFixed(2);
}

function formatScore(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toFixed(2);
}

function debugItemTitle(item) {
  if (!item || typeof item !== 'object') return '-';
  if (item.source && ('fetched_count' in item || 'used_count' in item)) return item.source;
  if (item.title) return item.title;
  if (item.summary) return item.summary;
  if (item.section) return sectionLabel(item.section);
  if (item.record?.title) return item.record.title;
  if (item.event_id) return item.event_id;
  if (item.source_id) return item.source_id;
  if (item.cluster_id) return item.cluster_id;
  return JSON.stringify(item).slice(0, 80);
}

function debugSourceKey(item) {
  if (!item || typeof item !== 'object') return '未知来源';
  return item.provider_name || item.source || item.source_name || item.record?.source || '未知来源';
}

function debugItemSummary(item) {
  if (!item || typeof item !== 'object') return '';
  if ('fetched_count' in item || 'used_count' in item) {
    const fetched = item.fetched_count ?? 0;
    const used = item.used_count ?? 0;
    const error = item.error ? ` · ${item.error}` : '';
    return `抓取 ${fetched} 条，入窗 ${used} 条${error}`;
  }
  if (item.summary) return item.summary;
  if (item.raw_text) return String(item.raw_text).slice(0, 140);
  if (item.reason) return item.reason;
  if (item.items) return `${item.items.length} 条证据`;
  if (item.record?.summary) return item.record.summary;
  return '';
}

function debugItemMeta(item) {
  if (!item || typeof item !== 'object') return '-';
  if ('in_premarket_window' in item) {
    const values = [
      item.provider_name && item.provider_name !== item.source ? item.provider_name : null,
      item.source,
      item.category,
      item.in_premarket_window ? '入窗' : '未入窗',
      item.published_at,
    ].filter(Boolean);
    return values.join(' · ') || '-';
  }
  const values = [
    item.status,
    item.source_name || item.record_type || item.record?.record_type,
    item.event_type,
    item.importance,
    item.source_rank || item.record?.source_rank,
  ].filter(Boolean);
  return values.join(' · ') || '-';
}

function formatAmount(value) {
  if (value === null || value === undefined) return '-';
  const number = Number(value);
  if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(2)}万`;
  return number.toFixed(0);
}

function OutputView({ result, running, elapsed }) {
  if (running) {
    return (
      <div className="empty-state">
        <RefreshCw className="spin" size={24} />
        <span>{formatMs(elapsed || 0)}</span>
      </div>
    );
  }
  if (!result) {
    return <div className="empty-state">选择一个 Agent 运行</div>;
  }
  const text = result.parsed
    ? JSON.stringify(result.parsed, null, 2)
    : `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
  return (
    <>
      <div className="result-header">
        <span className={`result-badge ${result.status}`}>{result.status}</span>
        <span>{result.label}</span>
        <span>{formatMs(result.elapsed_ms)}</span>
      </div>
      <pre className="json-output">{text}</pre>
    </>
  );
}

function buildSummary(results) {
  const intradayParsed = results.intraday?.parsed;
  const intent = Array.isArray(intradayParsed)
    ? intradayParsed[0]
    : intradayParsed?.intents?.[0] || intradayParsed?.analysis?.generated_intents?.[0] || null;
  const risk = results.risk?.parsed;
  const brokerFill = Array.isArray(results.broker?.parsed) ? results.broker.parsed[0] : null;
  const review = results.review?.parsed;
  return [
    { label: '最新意图', value: intent ? `${intent.symbol} ${intent.side}` : '-' },
    { label: '风控结论', value: risk?.decision || '-' },
    { label: '模拟成交', value: brokerFill ? `${brokerFill.quantity}@${Number(brokerFill.price).toFixed(3)}` : '-' },
    { label: '复盘净收益', value: review?.pnl ? Number(review.pnl.net_pnl).toFixed(2) : '-' },
  ];
}

function statusLabel(value) {
  return {
    tradable: '可交易',
    watch: '观察',
    blocked: '受限',
    no_signal: '无信号',
  }[value] || value || '-';
}

function statusClassName(value) {
  return {
    已接入: 'ready',
    部分接入: 'partial',
    待接入: 'pending',
    失败: 'failed',
  }[value] || 'pending';
}

function sectionLabel(value) {
  return {
    core_conclusion: '核心结论',
    post_close_events: '盘后事件',
    announcement_events: '公告',
    portfolio_risks: '持仓风险',
    theme_candidates: '题材候选',
    macro_calendar: '宏观日历',
    overseas_mapping: '海外映射',
    avoid_list: '回避清单',
    opening_radar: '竞价雷达',
    premarket_instructions: '盘前指令',
  }[value] || value || '-';
}

function summarizeMetrics(metrics) {
  const totals = new Map();
  for (const metric of metrics) {
    const current = totals.get(metric.name) || 0;
    totals.set(metric.name, current + Number(metric.value || 0));
  }
  const preferred = ['agent_run_total', 'data_source_fetch_total', 'rag_qdrant_index_records_total', 'rag_evidence_coverage_ratio'];
  const rows = preferred
    .filter((name) => totals.has(name))
    .map((name) => ({
      name,
      value: name.endsWith('_ms')
        ? formatMs(totals.get(name))
        : name.endsWith('_ratio')
          ? formatPercentNumber(totals.get(name))
          : totals.get(name).toFixed(0),
    }));
  if (rows.length > 0) return rows;
  return [{ name: 'metrics', value: String(metrics.length) }];
}

createRoot(document.getElementById('root')).render(<App />);
