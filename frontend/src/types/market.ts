export type Granularity = 'M1' | 'M5' | 'M15' | 'H1';

export const GRANULARITIES: Granularity[] = ['M1', 'M5', 'M15', 'H1'];

export const GRANULARITY_LABELS: Record<Granularity, string> = {
  M1: '1 דקה',
  M5: '5 דקות',
  M15: '15 דקות',
  H1: 'שעה',
};

export interface Candle {
  time: number; // unix seconds (UTC)
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface CandlesResponse {
  instrument: string;
  granularity: Granularity;
  candles: Candle[];
}

export type SignalAction = 'NONE' | 'BUY' | 'SELL' | 'CLOSE';

export interface Thought {
  id: number;
  time: number; // unix seconds — when the thought was generated
  candle_time: number; // unix seconds — the candle it was generated from
  text: string;
  signal: SignalAction;
  indicators: Record<string, number>;
  // Which way the strategy currently leans, even while `signal` is NONE. Only
  // present on live WS 'thought' messages, not on the REST backfill.
  bias?: 'BUY' | 'SELL' | null;
}

export interface ThoughtsResponse {
  thoughts: Thought[];
}

export type TradeSide = 'BUY' | 'SELL';
export type TradeStatus = 'OPEN' | 'CLOSED';
export type ExitReason = 'SL' | 'TP' | 'MANUAL' | null;

export interface Trade {
  id: number;
  instrument: string;
  side: TradeSide;
  status: TradeStatus;
  entry_price: number;
  entry_time: number; // unix seconds
  exit_price: number | null;
  exit_time: number | null; // unix seconds
  exit_reason: ExitReason;
  stop_loss: number | null;
  take_profit: number | null;
  units: number;
  pnl: number | null;
  strategy_id: string;
  signal_reason: string;
}

export interface TradesResponse {
  trades: Trade[];
}

export interface StrategyInfo {
  id: string;
  display_name: string;
  kind: 'builtin' | 'custom';
  dsl?: Record<string, unknown> | null;
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
}

export interface AppSettings {
  bot_enabled: 'true' | 'false';
  active_strategy_id: string;
  risk_units: string;
  max_concurrent_positions: string;
}

export interface JournalNote {
  id: number;
  trade_id: number | null;
  time: number;
  note_text: string;
  context: Record<string, unknown>;
  zone: ChartZone | null;
}

export interface ChartZone {
  start_time: number;
  end_time: number;
  price_low: number;
  price_high: number;
}

export interface FeedbackRuleCondition {
  left: string;
  op: '>' | '<' | '>=' | '<=' | '==' | 'crosses_above' | 'crosses_below';
  right: string | number;
}

export interface FeedbackRule {
  id: number;
  description: string;
  conditions: FeedbackRuleCondition | { all?: FeedbackRuleCondition[]; any?: FeedbackRuleCondition[] };
  action: string;
  side_filter: TradeSide | null;
  is_active: boolean;
}

export interface ChatMessage {
  id: number;
  time: number;
  role: 'user' | 'assistant';
  text: string;
  trade_id: number | null;
  zone: ChartZone | null;
}

export type PortfolioPeriod = 'all' | 'day' | 'week' | 'month';

export interface PortfolioStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl: number;
  max_drawdown: number;
  equity_curve: { time: number; equity: number }[];
}

export type WsMessage =
  | { type: 'candle_update'; payload: { granularity: Granularity; candle: Candle } }
  | { type: 'candle_closed'; payload: { granularity: Granularity; candle: Candle } }
  | { type: 'bot_status'; payload: { stream?: string; blocked_signal?: string; rule?: string } }
  | { type: 'thought'; payload: Thought }
  | { type: 'trade_opened'; payload: Trade }
  | { type: 'trade_closed'; payload: Trade }
  | { type: 'trade_modified'; payload: Trade };
