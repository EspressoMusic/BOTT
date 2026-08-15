import { create } from 'zustand';
import type { ChartZone, Granularity, Trade, WsMessage } from '../types/market';

export type ThemeName = 'warm' | 'dark' | 'light';

const THEME_STORAGE_KEY = 'bott-theme';
const THEME_NAMES: ThemeName[] = ['warm', 'dark', 'light'];

function readStoredTheme(): ThemeName {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return (THEME_NAMES as string[]).includes(stored ?? '') ? (stored as ThemeName) : 'warm';
}

function applyThemeToDocument(theme: ThemeName) {
  document.documentElement.dataset.theme = theme;
}

const EMOTION_MODE_STORAGE_KEY = 'bott-emotion-mode';

function readStoredEmotionMode(): boolean {
  return window.localStorage.getItem(EMOTION_MODE_STORAGE_KEY) === 'true';
}

interface AppState {
  botEnabled: boolean;
  activeStrategyId: string;
  openTrade: Trade | null;
  tradeEventVersion: number; // bumped on every open/close so screens know to refetch
  blockedSignalNotice: string | null;
  // A rare, important auto-stop the user must actively notice and act on (the
  // bot disabling itself) — distinct from blockedSignalNotice, which fires on
  // every routine per-signal block and would drown this out if reused.
  autoStopNotice: string | null;
  directionBias: 'BUY' | 'SELL' | null; // set via chat — order_service blocks the opposite side until it clears
  annotating: boolean; // chart is in drag-to-select-a-zone mode (triggered from Settings or the chat's pencil button)
  pendingZone: ChartZone | null; // set when the user drag-selects a zone on the chart
  granularity: Granularity; // chart timeframe — was local App.tsx state, now in the store so Settings can control it too
  journalOpen: boolean; // journal/rules window, opened from Settings
  theme: ThemeName;
  emotionModeEnabled: boolean; // big reactive robot face (EmotionAvatar) on trade wins/losses — purely cosmetic, local-only
  thoughtsVisible: boolean; // shared by the thought bubble and the chart's intent arrow
  instrument: string;
  instrumentLabel: string;
  setBotEnabled: (v: boolean) => void;
  setActiveStrategyId: (id: string) => void;
  setOpenTrade: (t: Trade | null) => void;
  setDirectionBias: (v: 'BUY' | 'SELL' | null) => void;
  setAnnotating: (v: boolean) => void;
  toggleAnnotating: () => void;
  setPendingZone: (z: ChartZone | null) => void;
  setGranularity: (g: Granularity) => void;
  setJournalOpen: (v: boolean) => void;
  toggleJournalOpen: () => void;
  setTheme: (theme: ThemeName) => void;
  setEmotionModeEnabled: (v: boolean) => void;
  toggleThoughtsVisible: () => void;
  setInstrument: (id: string, label: string) => void;
  setAutoStopNotice: (v: string | null) => void;
  dismissAutoStopNotice: () => void;
  applyWsMessage: (msg: WsMessage) => void;
}

const AUTO_STOP_MESSAGES: Record<string, (payload: Record<string, unknown>) => string> = {
  daily_profit_target: (p) => `הבוט הגיע ליעד הרווח היומי (${p.pnl_pct}%) ונעצר אוטומטית עד מחר`,
  stale_history: (p) =>
    `הבוט נעצר אוטומטית: הנתונים ההיסטוריים מ-MT5 היו לא עדכניים (${p.stale_minutes ?? '?'} דקות ישנים) ` +
    'ולא ניתן היה לחשב אינדיקטורים אמינים. יש לוודא שהנתונים תקינים ולהפעיל מחדש ידנית בהגדרות.',
};

const initialTheme = readStoredTheme();
applyThemeToDocument(initialTheme);
const initialEmotionMode = readStoredEmotionMode();

export const useAppStore = create<AppState>((set) => ({
  botEnabled: true,
  activeStrategyId: 'ma_crossover',
  openTrade: null,
  tradeEventVersion: 0,
  blockedSignalNotice: null,
  autoStopNotice: null,
  directionBias: null,
  annotating: false,
  pendingZone: null,
  granularity: 'M1',
  journalOpen: false,
  theme: initialTheme,
  emotionModeEnabled: initialEmotionMode,
  thoughtsVisible: true,
  instrument: 'XAU_USD',
  instrumentLabel: 'זהב',
  setBotEnabled: (v) => set({ botEnabled: v }),
  setActiveStrategyId: (id) => set({ activeStrategyId: id }),
  setOpenTrade: (t) => set({ openTrade: t }),
  setDirectionBias: (v) => set({ directionBias: v }),
  setAnnotating: (v) => set({ annotating: v }),
  toggleAnnotating: () => set((state) => ({ annotating: !state.annotating })),
  setPendingZone: (z) => set({ pendingZone: z }),
  setGranularity: (g) => set({ granularity: g }),
  setJournalOpen: (v) => set({ journalOpen: v }),
  toggleJournalOpen: () => set((state) => ({ journalOpen: !state.journalOpen })),
  setTheme: (theme) => {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    applyThemeToDocument(theme);
    set({ theme });
  },
  setEmotionModeEnabled: (v) => {
    window.localStorage.setItem(EMOTION_MODE_STORAGE_KEY, String(v));
    set({ emotionModeEnabled: v });
  },
  toggleThoughtsVisible: () => set((state) => ({ thoughtsVisible: !state.thoughtsVisible })),
  setInstrument: (id, label) => set({ instrument: id, instrumentLabel: label }),
  setAutoStopNotice: (v) => set({ autoStopNotice: v }),
  dismissAutoStopNotice: () => set({ autoStopNotice: null }),
  applyWsMessage: (msg) => {
    if (msg.type === 'trade_opened') {
      set((state) => ({ openTrade: msg.payload, tradeEventVersion: state.tradeEventVersion + 1 }));
    } else if (msg.type === 'trade_closed') {
      set((state) => ({
        openTrade: state.openTrade?.id === msg.payload.id ? null : state.openTrade,
        tradeEventVersion: state.tradeEventVersion + 1,
      }));
    } else if (msg.type === 'trade_modified') {
      set((state) => ({
        openTrade: state.openTrade?.id === msg.payload.id ? msg.payload : state.openTrade,
      }));
    } else if (msg.type === 'bot_status' && msg.payload.blocked_signal) {
      set({ blockedSignalNotice: `${msg.payload.blocked_signal} נחסם ע"י: ${msg.payload.rule}` });
    } else if (msg.type === 'bot_status' && msg.payload.auto_stopped_reason) {
      const buildMessage = AUTO_STOP_MESSAGES[msg.payload.auto_stopped_reason];
      set({
        botEnabled: false,
        autoStopNotice: buildMessage ? buildMessage(msg.payload) : `הבוט נעצר אוטומטית (${msg.payload.auto_stopped_reason})`,
      });
    } else if (msg.type === 'bot_status' && 'direction_bias' in msg.payload) {
      set({ directionBias: msg.payload.direction_bias ?? null });
    } else if (msg.type === 'instrument_changed') {
      set({ instrument: msg.payload.instrument, instrumentLabel: msg.payload.label, openTrade: null });
    }
  },
}));
