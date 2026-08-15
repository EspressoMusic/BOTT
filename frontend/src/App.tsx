import { useEffect, useState } from 'react';
import { fetchSettings, fetchTrades } from './api/client';
import { DirectionBiasBadge } from './components/DirectionBiasBadge';
import { DraggableWindow } from './components/DraggableWindow';
import { InstrumentSelector } from './components/InstrumentSelector';
import { Modal } from './components/Modal';
import { SidePanel } from './components/SidePanel';
import { TodayPnlBadge } from './components/TodayPnlBadge';
import { useWebSocket } from './hooks/useWebSocket';
import { PortfolioPage } from './pages/PortfolioPage';
import { SettingsPage } from './pages/SettingsPage';
import { TradingPage } from './pages/TradingPage';
import { useAppStore } from './store/appStore';
import type { ChartZone, WsMessage } from './types/market';

type ModalScreen = 'settings' | 'portfolio' | null;

function App() {
  const [latestMessage, setLatestMessage] = useState<WsMessage | null>(null);
  const [modalScreen, setModalScreen] = useState<ModalScreen>(null);
  const applyWsMessage = useAppStore((s) => s.applyWsMessage);
  const setBotEnabled = useAppStore((s) => s.setBotEnabled);
  const setActiveStrategyId = useAppStore((s) => s.setActiveStrategyId);
  const setOpenTrade = useAppStore((s) => s.setOpenTrade);
  const setDirectionBias = useAppStore((s) => s.setDirectionBias);
  const annotating = useAppStore((s) => s.annotating);
  const setAnnotating = useAppStore((s) => s.setAnnotating);
  const setPendingZone = useAppStore((s) => s.setPendingZone);
  const granularity = useAppStore((s) => s.granularity);
  const journalOpen = useAppStore((s) => s.journalOpen);
  const setJournalOpen = useAppStore((s) => s.setJournalOpen);
  const autoStopNotice = useAppStore((s) => s.autoStopNotice);
  const setAutoStopNotice = useAppStore((s) => s.setAutoStopNotice);
  const dismissAutoStopNotice = useAppStore((s) => s.dismissAutoStopNotice);

  useWebSocket((msg) => {
    setLatestMessage(msg);
    applyWsMessage(msg);
  });

  // Seed state that only WS push events would otherwise update, so a page
  // refresh doesn't lose "bot is off" / "which strategy" / "position is open".
  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setBotEnabled(s.bot_enabled === 'true');
        setActiveStrategyId(s.active_strategy_id);
        setDirectionBias(s.chat_direction_bias || null);
        // Persisted (not just pushed live over the WS) precisely so a page
        // opened/reloaded after the bot already auto-stopped itself still
        // explains why — a WS broadcast alone only reaches clients that were
        // already connected at the exact moment it fired.
        if (s.bot_enabled === 'false' && s.auto_stop_message) setAutoStopNotice(s.auto_stop_message);
      })
      .catch(() => {});
    fetchTrades('OPEN')
      // Match what a live WS `trade_opened` push would show: the most
      // recently opened position, not just whichever happens to sort first.
      .then((res) => setOpenTrade(res.trades[res.trades.length - 1] ?? null))
      .catch(() => {});
  }, [setBotEnabled, setActiveStrategyId, setOpenTrade, setDirectionBias, setAutoStopNotice]);

  // The timeframe/strategy/mark-zone/journal controls all now live in the
  // Settings modal, which sits on top of the chart — starting to mark a zone
  // needs the chart visible and interactive underneath, so close whichever
  // modal is open the moment annotate mode turns on.
  useEffect(() => {
    if (annotating) setModalScreen(null);
  }, [annotating]);

  const handleZoneSelected = (zone: ChartZone) => {
    setPendingZone(zone);
    setAnnotating(false);
  };

  return (
    <div className="app">
      {autoStopNotice && (
        <div className="auto-stop-banner" role="alert">
          <span>⚠️ {autoStopNotice}</span>
          <button type="button" onClick={dismissAutoStopNotice} aria-label="סגור">
            ✕
          </button>
        </div>
      )}
      <header className="app-header">
        <div className="header-left">
          <InstrumentSelector />
          <TodayPnlBadge />
          <DirectionBiasBadge />
        </div>
        <div className="header-right">
          <button
            type="button"
            className="header-icon-btn"
            title="מצב התיק"
            aria-label="מצב התיק"
            onClick={() => setModalScreen('portfolio')}
          >
            💼
          </button>
          <button
            type="button"
            className="header-icon-btn"
            title="הגדרות"
            aria-label="הגדרות"
            onClick={() => setModalScreen('settings')}
          >
            ⚙️
          </button>
        </div>
      </header>
      <TradingPage
        latestMessage={latestMessage}
        granularity={granularity}
        annotating={annotating}
        onZoneSelected={handleZoneSelected}
      />
      {journalOpen && (
        <DraggableWindow title="יומן וחוקים" onClose={() => setJournalOpen(false)}>
          <SidePanel />
        </DraggableWindow>
      )}
      {modalScreen === 'settings' && (
        <Modal title="הגדרות" onClose={() => setModalScreen(null)}>
          <SettingsPage />
        </Modal>
      )}
      {modalScreen === 'portfolio' && (
        <Modal title="תיק" onClose={() => setModalScreen(null)}>
          <PortfolioPage />
        </Modal>
      )}
    </div>
  );
}

export default App;
