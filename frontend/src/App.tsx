import { useEffect, useState } from 'react';
import { fetchSettings, fetchTrades } from './api/client';
import { ChartControlsMenu } from './components/ChartControlsMenu';
import { DraggableWindow } from './components/DraggableWindow';
import { Modal } from './components/Modal';
import { SidePanel } from './components/SidePanel';
import { useWebSocket } from './hooks/useWebSocket';
import { PortfolioPage } from './pages/PortfolioPage';
import { SettingsPage } from './pages/SettingsPage';
import { TradingPage } from './pages/TradingPage';
import { useAppStore } from './store/appStore';
import type { ChartZone, Granularity, WsMessage } from './types/market';

type ModalScreen = 'settings' | 'portfolio' | null;

function App() {
  const [latestMessage, setLatestMessage] = useState<WsMessage | null>(null);
  const [modalScreen, setModalScreen] = useState<ModalScreen>(null);
  const [granularity, setGranularity] = useState<Granularity>('M1');
  const [annotating, setAnnotating] = useState(false);
  const [journalOpen, setJournalOpen] = useState(false);
  const applyWsMessage = useAppStore((s) => s.applyWsMessage);
  const setBotEnabled = useAppStore((s) => s.setBotEnabled);
  const setActiveStrategyId = useAppStore((s) => s.setActiveStrategyId);
  const setOpenTrade = useAppStore((s) => s.setOpenTrade);
  const setPendingZone = useAppStore((s) => s.setPendingZone);

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
      })
      .catch(() => {});
    fetchTrades('OPEN')
      // Match what a live WS `trade_opened` push would show: the most
      // recently opened position, not just whichever happens to sort first.
      .then((res) => setOpenTrade(res.trades[res.trades.length - 1] ?? null))
      .catch(() => {});
  }, [setBotEnabled, setActiveStrategyId, setOpenTrade]);

  const handleZoneSelected = (zone: ChartZone) => {
    setPendingZone(zone);
    setAnnotating(false);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>זהב</h1>
        </div>
        <div className="header-right">
          <ChartControlsMenu
            granularity={granularity}
            onGranularityChange={setGranularity}
            annotating={annotating}
            onToggleAnnotate={() => setAnnotating((v) => !v)}
            journalOpen={journalOpen}
            onToggleJournal={() => setJournalOpen((v) => !v)}
            onOpenPortfolio={() => setModalScreen('portfolio')}
          />
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
