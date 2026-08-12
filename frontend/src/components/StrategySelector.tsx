import { useEffect, useState } from 'react';
import { activateStrategy, fetchStrategies } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { StrategyInfo } from '../types/market';

export function StrategySelector() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const activeStrategyId = useAppStore((s) => s.activeStrategyId);
  const setActiveStrategyId = useAppStore((s) => s.setActiveStrategyId);

  useEffect(() => {
    fetchStrategies()
      .then((res) => setStrategies(res.strategies))
      .catch(() => {});
  }, []);

  const handleChange = async (id: string) => {
    const previous = activeStrategyId;
    setActiveStrategyId(id);
    try {
      await activateStrategy(id);
    } catch {
      setActiveStrategyId(previous);
    }
  };

  return (
    <select
      className="strategy-selector"
      value={activeStrategyId}
      onChange={(e) => handleChange(e.target.value)}
      title="אסטרטגיה פעילה"
    >
      {strategies.map((s) => (
        <option key={s.id} value={s.id}>
          {s.display_name}
        </option>
      ))}
    </select>
  );
}
