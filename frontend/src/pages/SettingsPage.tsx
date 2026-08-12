import { useEffect, useState } from 'react';
import { createCustomStrategy, deleteCustomStrategy, fetchSettings, fetchStrategies, updateSettings } from '../api/client';
import { CollapsibleSection } from '../components/CollapsibleSection';
import { KillSwitchToggle } from '../components/KillSwitchToggle';
import { useAppStore } from '../store/appStore';
import type { StrategyInfo } from '../types/market';

export function SettingsPage() {
  const [riskUnits, setRiskUnits] = useState('10');
  const [maxPositions, setMaxPositions] = useState('1');
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const activeStrategyId = useAppStore((s) => s.activeStrategyId);

  const load = async () => {
    const [s, strats] = await Promise.all([fetchSettings(), fetchStrategies()]);
    setRiskUnits(s.risk_units);
    setMaxPositions(s.max_concurrent_positions);
    setStrategies(strats.strategies);
  };

  useEffect(() => {
    load().catch(() => {});
  }, []);

  const saveRisk = async () => {
    setSaving(true);
    try {
      await updateSettings({ risk_units: riskUnits, max_concurrent_positions: maxPositions });
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
      <CollapsibleSection title="מתג הפעלה">
        <p className="settings-hint">כיבוי עוצר פתיחת עסקאות חדשות מיידית. פוזיציות פתוחות ממשיכות עם ה-SL/TP שלהן.</p>
        <KillSwitchToggle />
      </CollapsibleSection>

      <CollapsibleSection title="ניהול סיכון">
        <div className="settings-form-row">
          <label>גודל עסקה (יחידות)</label>
          <input type="number" value={riskUnits} onChange={(e) => setRiskUnits(e.target.value)} />
        </div>
        <div className="settings-form-row">
          <label>מספר פוזיציות פתוחות מקסימלי</label>
          <input type="number" value={maxPositions} onChange={(e) => setMaxPositions(e.target.value)} />
        </div>
        <button type="button" onClick={saveRisk} disabled={saving}>
          {saving ? 'שומר...' : 'שמור'}
        </button>
      </CollapsibleSection>

      <CollapsibleSection title="אסטרטגיות">
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
