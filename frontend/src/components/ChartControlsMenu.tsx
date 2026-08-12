import { useEffect, useRef, useState } from 'react';
import { KillSwitchToggle } from './KillSwitchToggle';
import { StrategySelector } from './StrategySelector';
import { TimeframeSelector } from './TimeframeSelector';
import { useAppStore } from '../store/appStore';
import type { Granularity } from '../types/market';

interface Props {
  granularity: Granularity;
  onGranularityChange: (g: Granularity) => void;
  annotating: boolean;
  onToggleAnnotate: () => void;
  journalOpen: boolean;
  onToggleJournal: () => void;
  onOpenPortfolio: () => void;
}

export function ChartControlsMenu({
  granularity,
  onGranularityChange,
  annotating,
  onToggleAnnotate,
  journalOpen,
  onToggleJournal,
  onOpenPortfolio,
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const theme = useAppStore((s) => s.theme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    window.addEventListener('mousedown', handleClick);
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('mousedown', handleClick);
      window.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  return (
    <div className="chart-controls" ref={rootRef}>
      <button
        type="button"
        className={`header-icon-btn ${open ? 'active' : ''}`}
        onClick={() => setOpen((v) => !v)}
        title="תפריט"
        aria-label="תפריט"
      >
        📊
      </button>
      {open && (
        <div className="chart-controls-panel">
          <div className="chart-controls-row">
            <span className="chart-controls-label">בוט פעיל</span>
            <KillSwitchToggle />
          </div>
          <div className="chart-controls-row">
            <span className="chart-controls-label">טווח זמן</span>
            <TimeframeSelector value={granularity} onChange={onGranularityChange} />
          </div>
          <div className="chart-controls-row">
            <span className="chart-controls-label">אסטרטגיה</span>
            <StrategySelector />
          </div>
          <div className="chart-controls-row">
            <button
              type="button"
              className={`annotate-toggle ${annotating ? 'active' : ''}`}
              onClick={onToggleAnnotate}
              title="גרור על הגרף כדי לסמן אזור, ואז הוסיפו הערה בלשונית 'יומן וחוקים'"
            >
              {annotating ? '✏️ בטל סימון' : '🖊️ סמן אזור'}
            </button>
          </div>
          <div className="chart-controls-row">
            <button
              type="button"
              className={`chart-controls-action ${journalOpen ? 'active' : ''}`}
              onClick={onToggleJournal}
            >
              💬 יומן וחוקים
            </button>
            <button type="button" className="chart-controls-action" onClick={onOpenPortfolio}>
              📈 תיק
            </button>
          </div>
          <div className="chart-controls-row">
            <button type="button" className="chart-controls-action" onClick={toggleTheme}>
              {theme === 'warm' ? '🌙 מצב כהה' : '🟤 מצב חום'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
