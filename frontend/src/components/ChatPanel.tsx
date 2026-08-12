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

function AiChatTab() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingZone = useAppStore((s) => s.pendingZone);
  const setPendingZone = useAppStore((s) => s.setPendingZone);
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
    setSending(true);
    setError(null);
    try {
      const res = await askChat(text.trim(), pendingZone);
      setMessages((prev) => [...prev, res.user, res.assistant]);
      setText('');
      setPendingZone(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="ai-chat-tab">
      <p className="chat-hint">שאלו את הבוט על אזור שסימנתם בגרף, על עסקה, או כל שאלה על השוק.</p>
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
      <div className="ai-chat-messages" ref={listRef}>
        {messages.length === 0 && <p className="thoughts-empty">שאלו אותי משהו על הגרף או על עסקה</p>}
        {messages.map((m) => (
          <div key={m.id} className={`ai-chat-message ai-chat-${m.role}`}>
            {m.text}
          </div>
        ))}
        {sending && <div className="ai-chat-message ai-chat-assistant ai-chat-typing">חושב...</div>}
      </div>
      {error && <p className="settings-error">{error}</p>}
      <div className="journal-compose">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="למשל: מה דעתך על האזור הזה?"
          rows={2}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="button" onClick={submit} disabled={sending || !text.trim()}>
          {sending ? 'שולח...' : 'שלח'}
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
