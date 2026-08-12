import { useEffect, useRef, useState } from 'react';
import { fetchInstruments, switchInstrument } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { InstrumentInfo } from '../types/market';

export function InstrumentSelector() {
  const [available, setAvailable] = useState<InstrumentInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const instrument = useAppStore((s) => s.instrument);
  const instrumentLabel = useAppStore((s) => s.instrumentLabel);
  const setInstrument = useAppStore((s) => s.setInstrument);

  useEffect(() => {
    fetchInstruments()
      .then((res) => {
        setAvailable(res.available);
        setInstrument(res.active, res.active_label);
      })
      .catch(() => {});
  }, [setInstrument]);

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

  const handlePick = async (id: string) => {
    if (id === instrument) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      const res = await switchInstrument(id);
      setInstrument(res.instrument, res.label);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="instrument-selector" ref={rootRef}>
      <button
        type="button"
        className="asset-name-btn"
        onClick={() => setOpen((v) => !v)}
        title="החלפת נכס מסחר"
        aria-label="החלפת נכס מסחר"
      >
        {instrumentLabel} ▾
      </button>
      {open && (
        <div className="instrument-picker-panel">
          {available.length <= 1 && (
            <div className="instrument-picker-note">החלפת נכס לא נתמכת עם מקור הנתונים הנוכחי</div>
          )}
          {available.map((i) => (
            <button
              key={i.id}
              type="button"
              className={`instrument-picker-option ${i.id === instrument ? 'active' : ''}`}
              disabled={switching || available.length <= 1}
              onClick={() => handlePick(i.id)}
            >
              {i.label}
            </button>
          ))}
          {error && <div className="instrument-picker-error">{error}</div>}
        </div>
      )}
    </div>
  );
}
