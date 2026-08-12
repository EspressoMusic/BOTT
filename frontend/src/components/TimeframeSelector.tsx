import { GRANULARITIES, GRANULARITY_LABELS, type Granularity } from '../types/market';

interface Props {
  value: Granularity;
  onChange: (granularity: Granularity) => void;
}

export function TimeframeSelector({ value, onChange }: Props) {
  return (
    <div className="timeframe-selector">
      {GRANULARITIES.map((g) => (
        <button
          key={g}
          className={g === value ? 'active' : ''}
          onClick={() => onChange(g)}
          type="button"
        >
          {GRANULARITY_LABELS[g]}
        </button>
      ))}
    </div>
  );
}
