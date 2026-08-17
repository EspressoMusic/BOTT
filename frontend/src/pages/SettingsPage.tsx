import { useEffect, useState } from 'react';
import { createCustomStrategy, deleteCustomStrategy, fetchSettings, fetchStrategies, updateSettings } from '../api/client';
import { CollapsibleSection } from '../components/CollapsibleSection';
import { KillSwitchToggle } from '../components/KillSwitchToggle';
import { StrategySelector } from '../components/StrategySelector';
import { TimeframeSelector } from '../components/TimeframeSelector';
import { useAppStore } from '../store/appStore';
import type { StrategyInfo } from '../types/market';

export function SettingsPage() {
  const [riskUnits, setRiskUnits] = useState('10');
  const [riskDollars, setRiskDollars] = useState('0');
  const [riskPct, setRiskPct] = useState('0');
  const [maxPositions, setMaxPositions] = useState('1');
  const [dailyProfitTargetPct, setDailyProfitTargetPct] = useState('0');
  const [dailyStopDate, setDailyStopDate] = useState('');
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const activeStrategyId = useAppStore((s) => s.activeStrategyId);
  const granularity = useAppStore((s) => s.granularity);
  const setGranularity = useAppStore((s) => s.setGranularity);
  const setAnnotating = useAppStore((s) => s.setAnnotating);
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const setJournalOpen = useAppStore((s) => s.setJournalOpen);
  const emotionModeEnabled = useAppStore((s) => s.emotionModeEnabled);
  const setEmotionModeEnabled = useAppStore((s) => s.setEmotionModeEnabled);

  const load = async () => {
    const [s, strats] = await Promise.all([fetchSettings(), fetchStrategies()]);
    setRiskUnits(s.risk_units);
    setRiskDollars(s.risk_dollars);
    setRiskPct(s.risk_pct);
    setMaxPositions(s.max_concurrent_positions);
    setDailyProfitTargetPct(s.daily_profit_target_pct);
    setDailyStopDate(s.daily_stop_date);
    setStrategies(strats.strategies);
  };

  useEffect(() => {
    load().catch(() => {});
  }, []);

  const saveRisk = async () => {
    setSaving(true);
    try {
      await updateSettings({
        risk_units: riskUnits,
        risk_dollars: riskDollars,
        risk_pct: riskPct,
        max_concurrent_positions: maxPositions,
        daily_profit_target_pct: dailyProfitTargetPct,
      });
    } finally {
      setSaving(false);
    }
  };

  const removeCustom = async (id: string) => {
    await deleteCustomStrategy(id).catch(() => {});
    await load();
  };

  return (
    <div className="settings-page">
      <CollapsibleSection title="בקרות" defaultOpen>
        <p className="settings-hint">כיבוי עוצר פתיחת עסקאות חדשות מיידית. פוזיציות פתוחות ממשיכות עם ה-SL/TP שלהן.</p>
        <KillSwitchToggle />
        <div className="settings-form-row">
          <label>טווח זמן בגרף</label>
          <TimeframeSelector value={granularity} onChange={setGranularity} />
        </div>
        <div className="settings-form-row">
          <label>סימון אזור בגרף</label>
          <button type="button" className="annotate-toggle" onClick={() => setAnnotating(true)}>
            🖊️ סמן אזור
          </button>
        </div>
        <div className="settings-form-row">
          <label>הערות אישיות וחוקי פידבק</label>
          <button type="button" onClick={() => setJournalOpen(true)}>
            💬 יומן וחוקים
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="ניהול סיכון">
        <div className="settings-form-row">
          <label>סיכון קבוע לעסקה ($, 0 = כבוי — עדיפות ראשונה)</label>
          <input type="number" step="1" min="0" value={riskDollars} onChange={(e) => setRiskDollars(e.target.value)} />
        </div>
        <p className="settings-hint">
          כשמופעל, גודל כל עסקה מחושב אוטומטית כך שאם הסטופ-לוס ייפגע, ההפסד יהיה בדיוק הסכום הזה בדולרים — בלי קשר
          למרחק הסטופ או ליתרה. גובר על הסיכון באחוזים למטה.
        </p>
        <div className="settings-form-row">
          <label>סיכון לעסקה (% מהיתרה, 0 = כבוי — בשימוש רק כשהסיכון הקבוע בדולרים כבוי)</label>
          <input type="number" step="0.01" min="0" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} />
        </div>
        <div className="settings-form-row">
          <label>גודל עסקה קבוע (יחידות מהנכס הבסיסי — בשימוש רק כששני הסיכונים למעלה כבויים)</label>
          <input type="number" step="any" min="0" value={riskUnits} onChange={(e) => setRiskUnits(e.target.value)} />
        </div>
        <div className="settings-form-row">
          <label>מספר פוזיציות פתוחות מקסימלי</label>
          <input type="number" value={maxPositions} onChange={(e) => setMaxPositions(e.target.value)} />
        </div>
        <div className="settings-form-row">
          <label>עצירה אוטומטית ביעד רווח יומי (% מהתיק, 0 = כבוי)</label>
          <input
            type="number"
            step="0.1"
            min="0"
            value={dailyProfitTargetPct}
            onChange={(e) => setDailyProfitTargetPct(e.target.value)}
          />
        </div>
        <p className="settings-hint">
          כשמופעל, ברגע שהרווח הממומש היום מגיע לאחוז הזה מהיתרה שאיתה התחיל היום המסחרי — הבוט כובה אוטומטית (מתג
          ההפעלה) עד פתיחת סשן לונדון הבא (08:00 UTC), ואז חוזר לפעול לבד.
        </p>
        {dailyStopDate && <p className="settings-hint">הבוט נעצר אוטומטית עקב יעד הרווח ביום {dailyStopDate}.</p>}
        <button type="button" onClick={saveRisk} disabled={saving}>
          {saving ? 'שומר...' : 'שמור'}
        </button>
      </CollapsibleSection>

      <CollapsibleSection title="אסטרטגיות">
        <div className="settings-form-row">
          <label>אסטרטגיה פעילה</label>
          <StrategySelector />
        </div>
        <table className="settings-table">
          <tbody>
            {strategies.map((s) => (
              <tr key={s.id} className={s.id === activeStrategyId ? 'active-row' : ''}>
                <td>{s.display_name}</td>
                <td>{s.kind === 'builtin' ? 'מובנית' : 'מותאמת אישית'}</td>
                <td>{s.id === activeStrategyId ? '✓ פעילה' : ''}</td>
                <td>
                  {s.kind === 'custom' && (
                    <button type="button" onClick={() => removeCustom(s.id)}>
                      מחק
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <CustomStrategyBuilder onCreated={load} />
      </CollapsibleSection>

      <CollapsibleSection title="עיצוב">
        <div className="theme-picker">
          <button type="button" className={theme === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')}>
            🌙 כהה
          </button>
          <button type="button" className={theme === 'light' ? 'active' : ''} onClick={() => setTheme('light')}>
            ☀️ בהיר
          </button>
          <button type="button" className={theme === 'warm' ? 'active' : ''} onClick={() => setTheme('warm')}>
            🟤 חום עדין
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="מצב מצחיק 🤪">
        <p className="settings-hint">
          פרצוף גדול של הבוט שמגיב לתוצאות שלו בזמן אמת — שמח כשעסקה מרוויחה, מתעצבן כשעסקה מפסידה. תכונה קוסמטית
          בלבד, לא משפיעה על המסחר.
        </p>
        <div className="settings-form-row">
          <label>הפעל מצב מצחיק</label>
          <button
            type="button"
            className={`bot-switch ${emotionModeEnabled ? 'on' : 'off'}`}
            onClick={() => setEmotionModeEnabled(!emotionModeEnabled)}
            role="switch"
            aria-checked={emotionModeEnabled}
          >
            <span className="bot-switch-knob" />
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="חיבור לברוקר">
        <p className="settings-hint">
          המצב הנוכחי: מסחר מדומה (paper trading) פנימי — ללא חיבור לברוקר חיצוני, בלי הרשמה. חיבור ל-OANDA (לביצוע
          עסקאות דמו אמיתיות מול חשבון אמיתי) יתווסף כאן כשיהיו פרטי חשבון.
        </p>
      </CollapsibleSection>
    </div>
  );
}

function CustomStrategyBuilder({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('');
  const [indicatorType, setIndicatorType] = useState<'EMA' | 'SMA'>('EMA');
  const [fastPeriod, setFastPeriod] = useState(9);
  const [slowPeriod, setSlowPeriod] = useState(21);
  const [stopDistance, setStopDistance] = useState(15);
  const [targetDistance, setTargetDistance] = useState(30);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    const dsl = {
      indicators: [
        { name: 'fast', type: indicatorType, period: fastPeriod },
        { name: 'slow', type: indicatorType, period: slowPeriod },
      ],
      entry_long: { left: 'fast', op: 'crosses_above', right: 'slow' },
      entry_short: { left: 'fast', op: 'crosses_below', right: 'slow' },
      stop_loss: { type: 'distance', value: stopDistance },
      take_profit: { type: 'distance', value: targetDistance },
    };
    try {
      await createCustomStrategy(name.trim(), dsl);
      setName('');
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="custom-strategy-builder">
      <h3>אסטרטגיה חדשה — חציית אינדיקטורים</h3>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="שם האסטרטגיה" />
      <div className="builder-row">
        <label>סוג אינדיקטור</label>
        <select value={indicatorType} onChange={(e) => setIndicatorType(e.target.value as 'EMA' | 'SMA')}>
          <option value="EMA">EMA</option>
          <option value="SMA">SMA</option>
        </select>
      </div>
      <div className="builder-row">
        <label>תקופה מהירה</label>
        <input type="number" value={fastPeriod} onChange={(e) => setFastPeriod(Number(e.target.value))} />
        <label>תקופה איטית</label>
        <input type="number" value={slowPeriod} onChange={(e) => setSlowPeriod(Number(e.target.value))} />
      </div>
      <div className="builder-row">
        <label>מרחק סטופ לוס ($)</label>
        <input type="number" value={stopDistance} onChange={(e) => setStopDistance(Number(e.target.value))} />
        <label>מרחק טייק פרופיט ($)</label>
        <input type="number" value={targetDistance} onChange={(e) => setTargetDistance(Number(e.target.value))} />
      </div>
      {error && <p className="settings-error">{error}</p>}
      <button type="button" onClick={submit} disabled={saving || !name.trim()}>
        {saving ? 'שומר...' : 'צור אסטרטגיה'}
      </button>
    </div>
  );
}
