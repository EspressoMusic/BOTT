import { create } from 'zustand';
import type { ChartZone, Trade, WsMessage } from '../types/market';

export type ThemeName = 'warm' | 'dark';

const THEME_STORAGE_KEY = 'bott-theme';

function readStoredTheme(): ThemeName {
  return window.localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'warm';
}

function applyThemeToDocument(theme: ThemeName) {
  document.documentElement.dataset.theme = theme;
}

interface AppState {
  botEnabled: boolean;
  activeStrategyId: string;
  openTrade: Trade | null;
  tradeEventVersion: number; // bumped on every open/close so screens know to refetch
  blockedSignalNotice: string | null;
  pendingZone: ChartZone | null; // set when the user drag-selects a zone on the chart
  theme: ThemeName;
  thoughtsVisible: boolean; // shared by the thought bubble and the chart's intent arrow
  instrument: string;
  instrumentLabel: string;
  setBotEnabled: (v: boolean) => void;
  setActiveStrategyId: (id: string) => void;
  setOpenTrade: (t: Trade | null) => void;
  setPendingZone: (z: ChartZone | null) => void;
  toggleTheme: () => void;
  toggleThoughtsVisible: () => void;
  setInstrument: (id: string, label: string) => void;
  applyWsMessage: (msg: WsMessage) => void;
}

const initialTheme = readStoredTheme();
applyThemeToDocument(initialTheme);

export const useAppStore = create<AppState>((set, get) => ({
  botEnabled: true,
  activeStrategyId: 'ma_crossover',
  openTrade: null,
  tradeEventVersion: 0,
  blockedSignalNotice: null,
  pendingZone: null,
  theme: initialTheme,
  thoughtsVisible: true,
  instrument: 'XAU_USD',
  instrumentLabel: 'זהב',
  setBotEnabled: (v) => set({ botEnabled: v }),
  setActiveStrategyId: (id) => set({ activeStrategyId: id }),
  setOpenTrade: (t) => set({ openTrade: t }),
  setPendingZone: (z) => set({ pendingZone: z }),
  toggleTheme: () => {
    const next: ThemeName = get().theme === 'warm' ? 'dark' : 'warm';
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    applyThemeToDocument(next);
    set({ theme: next });
  },
  toggleThoughtsVisible: () => set((state) => ({ thoughtsVisible: !state.thoughtsVisible })),
  setInstrument: (id, label) => set({ instrument: id, instrumentLabel: label }),
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
    } else if (msg.type === 'instrument_changed') {
      set({ instrument: msg.payload.instrument, instrumentLabel: msg.payload.label, openTrade: null });
    }
  },
}));
