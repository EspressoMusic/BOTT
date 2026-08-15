import { useEffect, useRef, useState } from 'react';
import {
  askChat,
  createFeedbackRule,
  createJournalNote,
  deleteFeedbackRule,
  fetchChatMessages,
  fetchFeedbackRules,
  fetchJournal,
  updateFeedbackRule,
} from '../api/client';
import { useAppStore } from '../store/appStore';
import type { ChatMessage, FeedbackRule, JournalNote } from '../types/market';

const INDICATOR_OPTIONS = [
  'price',
  'rsi',
  'ema_fast',
  'ema_slow',
  'macd',
  'macd_signal',
  'macd_hist',
  'bb_upper',
  'bb_mid',
  'bb_lower',
  'sma_trend',
  'atr',
];

const OPERATOR_OPTIONS: { value: string; label: string }[] = [
  { value: '>', label: 'גדול מ' },
  { value: '<', label: 'קטן מ' },
  { value: '>=', label: 'גדול/שווה ל' },
  { value: '<=', label: 'קטן/שווה ל' },
];

export function ChatPanel() {
  const [subTab, setSubTab] = useState<'ai' | 'journal' | 'rules'>('ai');

  return (
    <div className="chat-panel">
      <div className="chat-subtabs">
        <button type="button" className={subTab === 'ai' ? 'active' : ''} onClick={() => setSubTab('ai')}>
          שאל את הבוט
        </button>
        <button type="button" className={subTab === 'journal' ? 'active' : ''} onClick={() => setSubTab('journal')}>
          הערות
        </button>
        <button type="button" className={subTab === 'rules' ? 'active' : ''} onClick={() => setSubTab('rules')}>
          חוקים
        </button>
      </div>
      {subTab === 'ai' ? <AiChatTab /> : subTab === 'journal' ? <JournalTab /> : <RulesTab />}
    </div>
  );
}

export function AiChatTab() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingZone = useAppStore((s) => s.pendingZone);
  const setPendingZone = useAppStore((s) => s.setPendingZone);
  const annotating = useAppStore((s) => s.annotating);
  const setAnnotating = useAppStore((s) => s.setAnnotating);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchChatMessages(100)
      .then((res) => setMessages(res.messages))
      .catch(() => {
        // backfill is best-effort
      });
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight });
  }, [messages, sending]);

  const submit = async () => {
    if (!text.trim() || sending) return;
    const messageText = text.trim();
    const zone = pendingZone;
    // Negative id keeps this bubble's key unique from any real DB id, so it
    // never collides while it's swapped out for the server's copy below.
    const optimisticId = -Date.now();
    const optimisticMsg: ChatMessage = {
      id: optimisticId,
      time: Math.floor(Date.now() / 1000),
      role: 'user',
      text: messageText,
      trade_id: null,
      zone: zone ?? null,
    };
    // Show the user's own message immediately instead of waiting for the
    // round trip — the "typing" indicator (driven by `sending`) covers the
    // wait for the bot's reply.
    setMessages((prev) => [...prev, optimisticMsg]);
    setText('');
    setPendingZone(null);
    setSending(true);
    setError(null);
    try {
      const res = await askChat(messageText, zone);
      setMessages((prev) => [...prev.filter((m) => m.id !== optimisticId), res.user, res.assistant]);
    } catch (err) {
      // The backend only persists the message once the model call succeeds,
      // so a failure here means it was never actually sent — drop the
      // optimistic bubble and hand the text back instead of losing it.
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
      setText(messageText);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="ai-chat-tab wa-chat">
      <div className="wa-messages" ref={listRef}>
        {messages.map((m) => (
          <div key={m.id} className={`wa-row ${m.role === 'user' ? 'wa-row-out' : 'wa-row-in'}`}>
            <div className={`wa-bubble ${m.role === 'user' ? 'wa-bubble-out' : 'wa-bubble-in'}`}>
              <span className="wa-bubble-text">{m.text}</span>
              <span className="wa-bubble-time">
                {new Date(m.time * 1000).toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          </div>
        ))}
        {sending && (
          <div className="wa-row wa-row-in">
            <div className="wa-bubble wa-bubble-in wa-typing">
              <span className="wa-typing-dot" />
              <span className="wa-typing-dot" />
              <span className="wa-typing-dot" />
            </div>
          </div>
        )}
      </div>
      {error && <p className="settings-error">{error}</p>}
      {pendingZone && (
        <div className="wa-reply-preview">
          <span>
            אזור מסומן: {new Date(pendingZone.start_time * 1000).toLocaleTimeString('he-IL')} –{' '}
            {new Date(pendingZone.end_time * 1000).toLocaleTimeString('he-IL')}, מחיר{' '}
            {pendingZone.price_low.toFixed(2)}–{pendingZone.price_high.toFixed(2)}
          </span>
          <button type="button" onClick={() => setPendingZone(null)} aria-label="בטל">
            ✕
          </button>
        </div>
      )}
      <div className="wa-input-row">
        <button
          type="button"
          className={`wa-annotate-btn ${annotating ? 'active' : ''}`}
          onClick={() => setAnnotating(true)}
          title="סמנו אזור בגרף כדי שהבוט יתייחס אליו"
          aria-label="סמן אזור בגרף"
        >
          ✏️
        </button>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="הקלידו הודעה"
          rows={1}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="button" className="wa-send-btn" onClick={submit} disabled={sending || !text.trim()} aria-label="שלח">
          ➤
        </button>
      </div>
    </div>
  );
}

function JournalTab() {
  const [notes, setNotes] = useState<JournalNote[]>([]);
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const pendingZone = useAppStore((s) => s.pendingZone);
  const setPendingZone = useAppStore((s) => s.setPendingZone);

  const load = () =>
    fetchJournal(100)
      .then((res) => setNotes(res.notes))
      .catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    if (!text.trim()) return;
    setLoading(true);
    try {
      await createJournalNote(text.trim(), undefined, pendingZone ?? undefined);
      setText('');
      setPendingZone(null);
      await load();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="journal-tab">
      <p className="chat-hint">הערות אישיות לתיעוד בלבד — לא משפיעות על הבוט. לחוקים שכן משפיעים, עברו ל"חוקים".</p>
      {pendingZone && (
        <div className="pending-zone-banner">
          <span>
            אזור מסומן: {new Date(pendingZone.start_time * 1000).toLocaleTimeString('he-IL')} –{' '}
            {new Date(pendingZone.end_time * 1000).toLocaleTimeString('he-IL')}, מחיר{' '}
            {pendingZone.price_low.toFixed(2)}–{pendingZone.price_high.toFixed(2)}
          </span>
          <button type="button" onClick={() => setPendingZone(null)}>
            בטל
          </button>
        </div>
      )}
      <div className="journal-list">
        {notes.length === 0 && <p className="thoughts-empty">אין הערות עדיין</p>}
        {notes
          .slice()
          .reverse()
          .map((n) => (
            <div key={n.id} className="journal-note">
              <span className="journal-note-time">{new Date(n.time * 1000).toLocaleString('he-IL')}</span>
              {n.zone && <span className="journal-note-zone">📍 אזור מסומן</span>}
              <span>{n.note_text}</span>
            </div>
          ))}
      </div>
      <div className="journal-compose">
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="כתוב הערה..." rows={2} />
        <button type="button" onClick={submit} disabled={loading || !text.trim()}>
          שלח
        </button>
      </div>
    </div>
  );
}

function RulesTab() {
  const [rules, setRules] = useState<FeedbackRule[]>([]);
  const [description, setDescription] = useState('');
  const [indicator, setIndicator] = useState(INDICATOR_OPTIONS[1]);
  const [operator, setOperator] = useState('>');
  const [value, setValue] = useState('70');
  const [side, setSide] = useState<'BUY' | 'SELL' | ''>('BUY');
  const [saving, setSaving] = useState(false);

  const load = () =>
    fetchFeedbackRules()
      .then((res) => setRules(res.rules))
      .catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    if (!description.trim()) return;
    setSaving(true);
    try {
      await createFeedbackRule(description.trim(), { left: indicator, op: operator, right: Number(value) }, side || null);
      setDescription('');
      await load();
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (rule: FeedbackRule) => {
    await updateFeedbackRule(rule.id, { is_active: !rule.is_active });
    await load();
  };

  const remove = async (rule: FeedbackRule) => {
    await deleteFeedbackRule(rule.id);
    await load();
  };

  return (
    <div className="rules-tab">
      <p className="chat-hint">
        חוקים אלו חוסמים כניסה לעסקה בפועל — למשל "אל תקנה כש-RSI מעל 80". שימו לב: כל אסטרטגיה מדווחת אינדיקטורים
        שונים, חוק שמתייחס לאינדיקטור שלא קיים באסטרטגיה הפעילה פשוט לא יופעל.
      </p>
      <div className="rules-list">
        {rules.length === 0 && <p className="thoughts-empty">אין חוקים עדיין</p>}
        {rules.map((r) => (
          <div key={r.id} className={`rule-row ${r.is_active ? '' : 'rule-inactive'}`}>
            <div className="rule-desc">{r.description}</div>
            <div className="rule-actions">
              <button type="button" onClick={() => toggle(r)}>
                {r.is_active ? 'השבת' : 'הפעל'}
              </button>
              <button type="button" onClick={() => remove(r)}>
                מחק
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="rule-builder">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="תיאור החוק (למשל: אל תקנה ב-RSI גבוה)"
        />
        <div className="rule-builder-row">
          <span>חסום</span>
          <select value={side} onChange={(e) => setSide(e.target.value as 'BUY' | 'SELL' | '')}>
            <option value="BUY">קנייה</option>
            <option value="SELL">מכירה</option>
            <option value="">קנייה ומכירה</option>
          </select>
          <span>כאשר</span>
          <select value={indicator} onChange={(e) => setIndicator(e.target.value)}>
            {INDICATOR_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          <select value={operator} onChange={(e) => setOperator(e.target.value)}>
            {OPERATOR_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <input type="number" value={value} onChange={(e) => setValue(e.target.value)} style={{ width: 70 }} />
        </div>
        <button type="button" onClick={submit} disabled={saving || !description.trim()}>
          הוסף חוק
        </button>
      </div>
    </div>
  );
}
