const jsonHeaders = {
  'Content-Type': 'application/json',
};

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function fetchHealth() {
  return request('/api/health');
}

export function runJob(job, date) {
  return request(`/api/run/${job}`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ date }),
  });
}

export function runAll(date) {
  return request('/api/run-all', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ date }),
  });
}

export function fetchReports() {
  return request('/api/reports');
}

export function fetchPremarketLatest() {
  return request('/api/premarket/latest');
}

export function fetchPremarketContext() {
  return request('/api/premarket/context');
}

export async function fetchReport(name) {
  const response = await fetch(`/api/reports/${encodeURIComponent(name)}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.text();
}

export function fetchMarketQuotes(symbols) {
  if (symbols && symbols.length > 0) {
    return request('/api/market/quotes', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ symbols }),
    });
  }
  return request('/api/market/quotes');
}

export function fetchStockPage({ page, pageSize, sort, asc }) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort,
    asc: String(asc),
  });
  return request(`/api/market/stocks?${params.toString()}`);
}

export function fetchObservabilityEvents(topic = '') {
  const params = new URLSearchParams({ limit: '80' });
  if (topic) params.set('topic', topic);
  return request(`/api/observability/events?${params.toString()}`);
}

export function fetchObservabilityTraces() {
  return request('/api/observability/traces?limit=80');
}

export function fetchObservabilityMetrics() {
  return request('/api/observability/metrics?limit=80');
}

export function fetchRiskApprovalQueue() {
  return request('/api/risk/approval-queue?limit=50');
}

export function fetchDecisionTraces({ intentId = '', runId = '' } = {}) {
  const params = new URLSearchParams({ limit: '80' });
  if (intentId) params.set('intent_id', intentId);
  if (runId) params.set('run_id', runId);
  return request(`/api/decisions/traces?${params.toString()}`);
}

export function searchKnowledge({ q, tradingDay, themes = [] }) {
  const params = new URLSearchParams({
    q,
    top_k: '8',
  });
  if (tradingDay) params.set('trading_day', tradingDay);
  for (const theme of themes) {
    if (theme) params.append('theme', theme);
  }
  return request(`/api/observability/knowledge/search?${params.toString()}`);
}

export function fetchRagDebug({ q, tradingDay, themes = [], symbols = [], sourceRankMin = '' }) {
  const params = new URLSearchParams({
    q,
    top_k: '8',
  });
  if (tradingDay) params.set('trading_day', tradingDay);
  if (sourceRankMin) params.set('source_rank_min', sourceRankMin);
  for (const theme of themes) {
    if (theme) params.append('theme', theme);
  }
  for (const symbol of symbols) {
    if (symbol) params.append('symbol', symbol);
  }
  return request(`/api/rag/debug?${params.toString()}`);
}
