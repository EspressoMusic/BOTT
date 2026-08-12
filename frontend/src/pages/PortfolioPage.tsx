import { useEffect, useMemo, useState } from 'react';
import { fetchPortfolioStats, fetchTrades } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { PortfolioPeriod, PortfolioStats, Trade } from '../types/market';

const PERIOD_OPTIONS: { value: PortfolioPeriod; label: string }[] = [
  { value: 'all', label: 'הכל' },
  { value: 'day', label: 'יומי' },
  { value: 'week', label: 'שבועי' },
  { value: 'month', label: 'חודשי' },
];

// Matches the backend's trailing windows (last 24h / 7d / 30d) — used to filter
// the trade-history table client-side so it stays consistent with whichever
// period the stats/equity-curve above were fetched for.
const PERIOD_MS: Record<PortfolioPeriod, number | null> = {
  all: null,
  day: 24 * 60 * 60 * 1000,
  week: 7 * 24 * 60 * 60 * 1000,
  month: 30 * 24 * 60 * 60 * 1000,
};

export function PortfolioPage() {
  const [period, setPeriod] = useState<PortfolioPeriod>('all');
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const tradeEventVersion = useAppStore((s) => s.tradeEventVersion);

  useEffect(() => {
    Promise.all([fetchPortfolioStats(period), fetchTrades()])
      .then(([s, t]) => {
        setStats(s);
        setTrades(t.trades);
      })
      .catch(() => {});
  }, [tradeEventVersion, period]);

  const visibleTrades = useMemo(() => {
    const windowMs = PERIOD_MS[period];
    if (windowMs == null) return trades;
    const cutoff = Date.now() - windowMs;
    // Closed trades: filter by when they closed. Still-open trades have no
    // exit yet, so fall back to entry time.
    return trades.filter((t) => (t.exit_time ?? t.entry_time) * 1000 >= cutoff);
  }, [trades, period]);

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
        <StatTile label="סה״כ עסקאות" value={stats?.total_trades ?? '—'} />
        <StatTile label="אחוז הצלחה" value={stats ? `${stats.win_rate_pct}%` : '—'} />
        <StatTile
          label="רווח/הפסד כולל"
          value={stats ? `${stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl}$` : '—'}
          positive={stats ? stats.total_pnl >= 0 : undefined}
        />
        <StatTile label="ירידה מקסימלית" value={stats ? `${stats.max_drawdown}$` : '—'} />
      </section>

      <section className="portfolio-equity">
        <h2>עקומת הון</h2>
        <EquityCurve points={stats?.equity_curve ?? []} />
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
              {trades
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
              {trades.length === 0 && (
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
