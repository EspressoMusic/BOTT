import { useEffect, useMemo, useState } from 'react';
import { fetchTrades } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { PortfolioPeriod, Trade } from '../types/market';

const PERIOD_OPTIONS: { value: PortfolioPeriod; label: string }[] = [
  { value: 'all', label: 'הכל' },
  { value: 'day', label: 'יומי' },
  { value: 'week', label: 'שבועי' },
  { value: 'month', label: 'חודשי' },
];

// Calendar boundaries in the browser's local timezone — "today" means since
// local midnight, not "last 24 hours", so the tab actually narrows down once
// there's more than a day of history.
function periodStartMs(period: PortfolioPeriod, now: Date): number | null {
  if (period === 'all') return null;
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (period === 'week') start.setDate(start.getDate() - start.getDay());
  if (period === 'month') start.setDate(1);
  return start.getTime();
}

export function PortfolioPage() {
  const [period, setPeriod] = useState<PortfolioPeriod>('all');
  const [trades, setTrades] = useState<Trade[]>([]);
  const tradeEventVersion = useAppStore((s) => s.tradeEventVersion);

  useEffect(() => {
    fetchTrades()
      .then((t) => setTrades(t.trades))
      .catch(() => {});
  }, [tradeEventVersion]);

  const visibleTrades = useMemo(() => {
    const cutoff = periodStartMs(period, new Date());
    if (cutoff == null) return trades;
    // Closed trades: filter by when they closed. Still-open trades have no
    // exit yet, so fall back to entry time.
    return trades.filter((t) => (t.exit_time ?? t.entry_time) * 1000 >= cutoff);
  }, [trades, period]);

  const stats = useMemo(() => {
    const closed = visibleTrades
      .filter((t): t is Trade & { exit_time: number } => t.status === 'CLOSED' && t.exit_time != null)
      .slice()
      .sort((a, b) => a.exit_time - b.exit_time);
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0);
    const totalPnl = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const winRate = closed.length ? (wins.length / closed.length) * 100 : 0;

    let cumulative = 0;
    let peak = 0;
    let maxDrawdown = 0;
    const equityCurve = closed.map((t) => {
      cumulative += t.pnl ?? 0;
      peak = Math.max(peak, cumulative);
      maxDrawdown = Math.max(maxDrawdown, peak - cumulative);
      return { time: t.exit_time, equity: Math.round(cumulative * 100) / 100 };
    });

    return {
      total_trades: closed.length,
      win_rate_pct: Math.round(winRate * 10) / 10,
      total_pnl: Math.round(totalPnl * 100) / 100,
      max_drawdown: Math.round(maxDrawdown * 100) / 100,
      equity_curve: equityCurve,
    };
  }, [visibleTrades]);

  return (
    <div className="portfolio-page">
      <div className="portfolio-period-tabs">
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`portfolio-period-tab ${period === opt.value ? 'active' : ''}`}
            onClick={() => setPeriod(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <section className="portfolio-stats">
        <StatTile label="סה״כ עסקאות" value={stats.total_trades} />
        <StatTile label="אחוז הצלחה" value={`${stats.win_rate_pct}%`} />
        <StatTile
          label="רווח/הפסד כולל"
          value={`${stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl}$`}
          positive={stats.total_pnl >= 0}
        />
        <StatTile label="ירידה מקסימלית" value={`${stats.max_drawdown}$`} />
      </section>

      <section className="portfolio-equity">
        <h2>עקומת הון</h2>
        <EquityCurve points={stats.equity_curve} />
      </section>

      <section className="portfolio-history">
        <h2>היסטוריית עסקאות</h2>
        <div className="table-scroll">
          <table className="trades-table">
            <thead>
              <tr>
                <th>זמן כניסה</th>
                <th>צד</th>
                <th>כניסה</th>
                <th>יציאה</th>
                <th>סיבה</th>
                <th>רווח/הפסד</th>
                <th>אסטרטגיה</th>
              </tr>
            </thead>
            <tbody>
              {visibleTrades
                .slice()
                .reverse()
                .map((t) => (
                  <tr key={t.id}>
                    <td>{new Date(t.entry_time * 1000).toLocaleString('he-IL')}</td>
                    <td>{t.side === 'BUY' ? 'קנייה' : 'מכירה'}</td>
                    <td>{t.entry_price.toFixed(2)}</td>
                    <td>{t.exit_price != null ? t.exit_price.toFixed(2) : '—'}</td>
                    <td>{t.exit_reason ?? (t.status === 'OPEN' ? 'פתוחה' : '—')}</td>
                    <td className={t.pnl != null ? (t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : ''}>
                      {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}$` : '—'}
                    </td>
                    <td>{t.strategy_id}</td>
                  </tr>
                ))}
              {visibleTrades.length === 0 && (
                <tr>
                  <td colSpan={7} className="thoughts-empty">
                    אין עסקאות עדיין
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function StatTile({ label, value, positive }: { label: string; value: string | number; positive?: boolean }) {
  const cls = positive === undefined ? '' : positive ? 'positive' : 'negative';
  return (
    <div className={`stat-tile ${cls}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

function EquityCurve({ points }: { points: { time: number; equity: number }[] }) {
  if (points.length < 2) {
    return <p className="thoughts-empty">אין מספיק נתונים עדיין</p>;
  }

  const width = 600;
  const height = 120;
  const pad = 10;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const stepX = (width - pad * 2) / (points.length - 1);

  const path = points
    .map((p, i) => {
      const x = pad + i * stepX;
      const y = height - pad - ((p.equity - min) / range) * (height - pad * 2);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const zeroY = height - pad - ((0 - min) / range) * (height - pad * 2);
  const lastPositive = values[values.length - 1] >= 0;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="equity-svg" preserveAspectRatio="none">
      <line x1={0} y1={zeroY} x2={width} y2={zeroY} stroke="#2a2f3d" strokeDasharray="4 4" />
      <path d={path} fill="none" stroke={lastPositive ? '#26a69a' : '#ef5350'} strokeWidth={2} />
    </svg>
  );
}
