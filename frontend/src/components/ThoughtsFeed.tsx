import { useEffect, useState } from 'react';
import { fetchThoughts } from '../api/client';
import { AiChatTab } from './ChatPanel';
import { DraggableWindow } from './DraggableWindow';
import { useAppStore } from '../store/appStore';
import type { Thought, WsMessage } from '../types/market';

interface Props {
  latestMessage: WsMessage | null;
}

export function ThoughtsFeed({ latestMessage }: Props) {
  const [latest, setLatest] = useState<Thought | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const visible = useAppStore((s) => s.thoughtsVisible);
  const toggleVisible = useAppStore((s) => s.toggleThoughtsVisible);
  const instrument = useAppStore((s) => s.instrument);

  useEffect(() => {
    fetchThoughts(1, instrument)
      .then((res) => setLatest(res.thoughts[res.thoughts.length - 1] ?? null))
      .catch(() => {
        // backfill is best-effort; the next live thought over WS will still arrive
      });
  }, [instrument]);

  useEffect(() => {
    if (!latestMessage) return;
    if (latestMessage.type === 'thought') {
      // Ignore a stray thought from an instrument that was just switched away
      // from — the engine rebuild on switch should make this rare, but a
      // thought already in flight the instant it happens could still land.
      if (latestMessage.payload.instrument && latestMessage.payload.instrument !== instrument) return;
      setLatest(latestMessage.payload);
    } else if (latestMessage.type === 'instrument_changed') {
      // Old thoughts were about a different instrument's price action — stale
      // and misleading once the chart underneath has switched assets.
      setLatest(null);
    }
  }, [latestMessage, instrument]);

  return (
    <div className="thought-widget">
      <button
        type="button"
        className={`chart-icon-btn ${visible ? 'active' : ''}`}
        onClick={toggleVisible}
        title="מחשבות הבוט"
        aria-label="מחשבות הבוט"
      >
        🤖
      </button>
      <button
        type="button"
        className={`chart-icon-btn ${chatOpen ? 'active' : ''}`}
        onClick={() => setChatOpen((v) => !v)}
        title="שאלו את הבוט"
        aria-label="שאלו את הבוט"
      >
        💬
      </button>
      {chatOpen && (
        <DraggableWindow title="צ'אט" onClose={() => setChatOpen(false)} headerClassName="wa-header">
          <AiChatTab />
        </DraggableWindow>
      )}
      {visible && (
        <>
          <div className="thought-bubble-trail">
            <span className="thought-bubble-dot dot-1" />
            <span className="thought-bubble-dot dot-2" />
            <span className="thought-bubble-dot dot-3" />
          </div>
          <div className={`thought-bubble ${latest ? `thought-${latest.signal.toLowerCase()}` : ''}`}>
            <span className="thought-text">
              {latest ? latest.text : 'ממתין למספיק נתונים כדי להתחיל לנתח...'}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
