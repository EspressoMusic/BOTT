import { useEffect, useState } from 'react';
import { fetchThoughts } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { Thought, WsMessage } from '../types/market';

interface Props {
  latestMessage: WsMessage | null;
}

export function ThoughtsFeed({ latestMessage }: Props) {
  const [latest, setLatest] = useState<Thought | null>(null);
  const visible = useAppStore((s) => s.thoughtsVisible);
  const toggleVisible = useAppStore((s) => s.toggleThoughtsVisible);

  useEffect(() => {
    fetchThoughts(1)
      .then((res) => setLatest(res.thoughts[res.thoughts.length - 1] ?? null))
      .catch(() => {
        // backfill is best-effort; the next live thought over WS will still arrive
      });
  }, []);

  useEffect(() => {
    if (!latestMessage || latestMessage.type !== 'thought') return;
    setLatest(latestMessage.payload);
  }, [latestMessage]);

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
