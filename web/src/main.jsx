import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Clock,
  Database,
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
  Wallet,
} from 'lucide-react';
import {
  fetchObservabilityEvents,
  fetchObservabilityMetrics,
  fetchObservabilityTraces,
  fetchDecisionTraces,
  fetchHealth,
  fetchMarketQuotes,
  fetchPremarketContext,
  fetchPremarketLatest,
  fetchRagDebug,
  fetchReport,
  fetchReports,
  fetchRiskApprovalQueue,
  fetchStockPage,
  runAll,
  runJob,
} from './api.js';
import './styles.css';

const JOBS = [
  { id: 'premarket', label: '盘前 Agent', hint: 'Ctrl+5', icon: Newspaper },
  { id: 'intraday', label: '盘中 Agent', hint: 'Ctrl+1', icon: Activity },
  { id: 'risk', label: '风控网关', hint: 'Ctrl+2', icon: ShieldCheck },
  { id: 'broker', label: 'Paper Broker', hint: 'Ctrl+3', icon: Wallet },
  { id: 'review', label: '复盘 Agent', hint: 'Ctrl+4', icon: FileText },
];

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function formatMs(ms) {
  if (!Number.isFinite(ms)) return '0 ms';
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function App() {
  const [health, setHealth] = useState(null);
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
  const [observability, setObservability] = useState({
    events: [],
    traces: [],
    metrics: [],
    knowledgeResults: [],
    premarketContext: null,
    approvalQueue: [],
    decisionTimeline: [],
    ragDebug: null,
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
      ] = await Promise.all([
        fetchObservabilityEvents(),
        fetchObservabilityTraces(),
        fetchObservabilityMetrics(),
        fetchPremarketContext(),
        fetchRiskApprovalQueue(),
        fetchDecisionTraces({ intentId: decisionQuery.trim() }),
        fetchRagDebug({ q: knowledgeQuery || '盘前', tradingDay: date }),
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
      }
      if (job === 'review') {
        await refreshReports();
      }
    } catch (error) {
      setResults((current) => ({
        ...current,
        [job]: {
          job,
          label: JOBS.find((item) => item.id === job)?.label || job,
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
  }, [date, refreshObservability, refreshPremarket, refreshReports]);

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
  }, [date, refreshObservability, refreshPremarket, refreshReports]);

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

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Paper Trading</p>
          <h1>A股 Agent 控制台</h1>
        </div>
        <div className="top-actions">
          <label className="date-field">
            <span>交易日</span>
            <input value={date} onChange={(event) => setDate(event.target.value)} type="date" />
          </label>
          <StatusPill health={health} />
        </div>
      </header>

      <section className="status-grid">
        <Metric icon={Gauge} label="模式" value="paper" tone="blue" />
        <Metric icon={ShieldCheck} label="实盘交易" value="关闭" tone="green" />
        <Metric icon={AlertTriangle} label="人工确认" value="开启" tone="orange" />
        <Metric icon={Clock} label="最近耗时" value={formatMs(activeResult?.elapsed_ms || timers[selectedJob] || 0)} tone="gray" />
      </section>

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

      <ObservabilityPanel
        data={observability}
        loading={observabilityLoading}
        error={observabilityError}
        query={knowledgeQuery}
        onQueryChange={setKnowledgeQuery}
        onRefresh={refreshObservability}
      />

      <DecisionOpsPanel
        data={observability}
        loading={observabilityLoading}
        decisionQuery={decisionQuery}
        onDecisionQueryChange={setDecisionQuery}
        onRefresh={refreshObservability}
      />

      <section className="workspace">
        <div className="control-panel">
          <div className="section-title">
            <BarChart3 size={18} />
            <span>运行</span>
          </div>
          <button className="run-all" type="button" onClick={executeAll} disabled={running.all}>
            {running.all ? <RefreshCw className="spin" size={18} /> : <Play size={18} />}
            <span>运行完整链路</span>
            <kbd>Ctrl Enter</kbd>
          </button>
          <div className="job-list">
            {JOBS.map((job) => (
              <JobButton
                key={job.id}
                job={job}
                selected={selectedJob === job.id}
                running={Boolean(running[job.id])}
                elapsed={running[job.id] ? timers[job.id] : results[job.id]?.elapsed_ms}
                status={results[job.id]?.status}
                onSelect={() => setSelectedJob(job.id)}
                onRun={() => executeJob(job.id)}
              />
            ))}
          </div>
        </div>

        <div className="output-panel">
          <div className="section-title">
            <Terminal size={18} />
            <span>输出</span>
          </div>
          <OutputView result={activeResult} running={Boolean(running[selectedJob])} elapsed={timers[selectedJob]} />
        </div>

        <div className="report-panel">
          <div className="section-title">
            <FileText size={18} />
            <span>日报</span>
          </div>
          <div className="report-select-row">
            <select value={selectedReport} onChange={(event) => setSelectedReport(event.target.value)}>
              <option value="">无报告</option>
              {reports.map((report) => (
                <option key={report.name} value={report.name}>{report.name}</option>
              ))}
            </select>
            <button className="icon-button" type="button" onClick={refreshReports} aria-label="刷新报告">
              <RefreshCw size={16} />
            </button>
          </div>
          <pre className="report-preview">{reportText || '暂无报告'}</pre>
        </div>
      </section>

      <section className="summary-strip">
        {summary.map((item) => (
          <div className="summary-item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </section>
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

function JobButton({ job, selected, running, elapsed, status, onSelect, onRun }) {
  const Icon = job.icon;
  return (
    <div className={`job-row ${selected ? 'selected' : ''}`}>
      <button className="job-select" type="button" onClick={onSelect}>
        <Icon size={18} />
        <span>{job.label}</span>
      </button>
      <span className={`job-status ${status || 'idle'}`}>{running ? formatMs(elapsed || 0) : status || '待命'}</span>
      <button className="job-run" type="button" onClick={onRun} disabled={running}>
        {running ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}
        <kbd>{job.hint}</kbd>
      </button>
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
                {watchlist.length === 0 ? <li>暂无</li> : watchlist.slice(0, 5).map((item) => (
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

function ObservabilityPanel({ data, loading, error, query, onQueryChange, onRefresh }) {
  const metricSummary = useMemo(() => summarizeMetrics(data.metrics), [data.metrics]);
  const latestEvents = data.events.slice(0, 8);
  const latestTraces = data.traces.slice(-8).reverse();
  const knowledgeResults = data.knowledgeResults.slice(0, 6);
  return (
    <section className="observability-panel">
      <div className="observability-header">
        <div className="section-title">
          <GitBranch size={18} />
          <span>可观测性与 RAG</span>
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
      <div className="observability-grid">
        <div className="observability-card">
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
        <div className="observability-card">
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
        <div className="observability-card">
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
        <div className="observability-card">
          <h2>RAG Evidence</h2>
          <ul className="trace-list">
            {knowledgeResults.length === 0 ? <li>暂无检索结果</li> : knowledgeResults.map((item) => (
              <li key={item.record.record_id}>
                <strong>{item.record.title}</strong>
                <span>{item.record.source || item.record.source_rank} · score {Number(item.score).toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function DecisionOpsPanel({ data, loading, decisionQuery, onDecisionQueryChange, onRefresh }) {
  const context = data.premarketContext;
  const constraints = context?.constraints || [];
  const approvals = data.approvalQueue || [];
  const timeline = data.decisionTimeline || [];
  const ragDebug = data.ragDebug;
  return (
    <section className="decision-panel">
      <div className="decision-header">
        <div className="section-title">
          <ShieldCheck size={18} />
          <span>决策与约束</span>
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
      <div className="decision-grid">
        <div className="decision-card">
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
        <div className="decision-card">
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

function formatPlain(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toFixed(2);
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
  const intent = Array.isArray(results.intraday?.parsed) ? results.intraday.parsed[0] : null;
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

function summarizeMetrics(metrics) {
  const totals = new Map();
  for (const metric of metrics) {
    const current = totals.get(metric.name) || 0;
    totals.set(metric.name, current + Number(metric.value || 0));
  }
  const preferred = ['agent_run_total', 'data_source_fetch_total', 'rag_index_records_total', 'agent_run_duration_ms'];
  const rows = preferred
    .filter((name) => totals.has(name))
    .map((name) => ({ name, value: name.endsWith('_ms') ? formatMs(totals.get(name)) : totals.get(name).toFixed(0) }));
  if (rows.length > 0) return rows;
  return [{ name: 'metrics', value: String(metrics.length) }];
}

createRoot(document.getElementById('root')).render(<App />);
