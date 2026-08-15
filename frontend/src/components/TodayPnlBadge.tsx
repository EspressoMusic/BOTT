import { useEffect, useState } from 'react';
import { fetchBotStatus } from '../api/client';
import { useAppStore } from '../store/appStore';

export function TodayPnlBadge() {
  const [pnl, setPnl] = useState<number | null>(null);
  const tradeEventVersion = useAppStore((s) => s.tradeEventVersion);

  useEffect(() => {
    fetchBotStatus()
      .then((res) => setPnl(typeof res.today_pnl === 'number' ? res.today_pnl : null))
      .catch(() => {});
  }, [tradeEventVersion]);

  if (pnl === null) return null;

  const cls = pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : '';
  const sign = pnl > 0 ? '+' : '';

  return (
    <span className="today-pnl-badge">
      רווח היום: <span className={cls}>{sign}{pnl.toFixed(2)}$</span>
    </span>
  );
}
