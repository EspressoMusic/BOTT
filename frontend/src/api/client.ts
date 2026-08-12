import type {
  AppSettings,
  CandlesResponse,
  ChatMessage,
  FeedbackRule,
  Granularity,
  JournalNote,
  PortfolioPeriod,
  PortfolioStats,
  StrategiesResponse,
  ThoughtsResponse,
  TradesResponse,
  ChartZone,
} from '../types/market';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${res.statusText} ${body}`.trim());
  }
  return res.json();
}

export function fetchCandles(granularity: Granularity, count = 300): Promise<CandlesResponse> {
  return request(`/api/candles?granularity=${granularity}&count=${count}`);
}

export function fetchThoughts(limit = 50): Promise<ThoughtsResponse> {
  return request(`/api/thoughts?limit=${limit}`);
}

export function fetchTrades(status?: 'OPEN' | 'CLOSED'): Promise<TradesResponse> {
  return request(`/api/trades${status ? `?status=${status}` : ''}`);
}

export function closePosition(tradeId: number): Promise<{ status: string }> {
  return request(`/api/positions/${tradeId}/close`, { method: 'POST' });
}

export function modifyPosition(
  tradeId: number,
  update: { stop_loss?: number; take_profit?: number }
): Promise<{ status: string }> {
  return request(`/api/positions/${tradeId}/modify`, { method: 'PATCH', body: JSON.stringify(update) });
}

export function fetchStrategies(): Promise<StrategiesResponse> {
  return request('/api/strategies');
}

export function activateStrategy(strategyId: string): Promise<{ active_strategy_id: string }> {
  return request(`/api/strategies/${strategyId}/activate`, { method: 'POST' });
}

export function createCustomStrategy(displayName: string, dsl: Record<string, unknown>) {
  return request('/api/strategies', {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName, dsl }),
  });
}

export function deleteCustomStrategy(strategyId: string) {
  return request(`/api/strategies/${strategyId}`, { method: 'DELETE' });
}

export function fetchSettings(): Promise<AppSettings> {
  return request('/api/settings');
}

export function updateSettings(update: Partial<Pick<AppSettings, 'risk_units' | 'max_concurrent_positions'>>) {
  const body: Record<string, number> = {};
  if (update.risk_units !== undefined) body.risk_units = Number(update.risk_units);
  if (update.max_concurrent_positions !== undefined) body.max_concurrent_positions = Number(update.max_concurrent_positions);
  return request<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) });
}

export function enableBot() {
  return request<{ bot_enabled: boolean }>('/api/bot/enable', { method: 'POST' });
}

export function disableBot() {
  return request<{ bot_enabled: boolean }>('/api/bot/disable', { method: 'POST' });
}

export function fetchBotStatus() {
  return request<{
    bot_enabled: boolean;
    account: { balance: number; unrealized_pnl: number; open_trade_count: number };
    open_trades: unknown[];
  }>('/api/bot/status');
}

export function fetchPortfolioStats(period: PortfolioPeriod = 'all'): Promise<PortfolioStats> {
  return request(`/api/portfolio/stats?period=${period}`);
}

export function fetchJournal(limit = 100): Promise<{ notes: JournalNote[] }> {
  return request(`/api/journal?limit=${limit}`);
}

export function createJournalNote(noteText: string, tradeId?: number, zone?: ChartZone) {
  return request<JournalNote>('/api/journal', {
    method: 'POST',
    body: JSON.stringify({ note_text: noteText, trade_id: tradeId ?? null, zone: zone ?? null }),
  });
}

export function fetchFeedbackRules(): Promise<{ rules: FeedbackRule[] }> {
  return request('/api/feedback-rules');
}

export function createFeedbackRule(
  description: string,
  conditions: Record<string, unknown>,
  sideFilter: 'BUY' | 'SELL' | null
) {
  return request<FeedbackRule>('/api/feedback-rules', {
    method: 'POST',
    body: JSON.stringify({ description, conditions, action: 'block_entry', side_filter: sideFilter }),
  });
}

export function updateFeedbackRule(ruleId: number, update: { is_active?: boolean }) {
  return request<FeedbackRule>(`/api/feedback-rules/${ruleId}`, { method: 'PUT', body: JSON.stringify(update) });
}

export function deleteFeedbackRule(ruleId: number) {
  return request(`/api/feedback-rules/${ruleId}`, { method: 'DELETE' });
}

export function fetchChatMessages(limit = 100): Promise<{ messages: ChatMessage[] }> {
  return request(`/api/chat?limit=${limit}`);
}

export function askChat(message: string, zone?: ChartZone | null, tradeId?: number | null) {
  return request<{ user: ChatMessage; assistant: ChatMessage }>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message, zone: zone ?? null, trade_id: tradeId ?? null }),
  });
}
