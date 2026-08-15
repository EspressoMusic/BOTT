import { clearDirectionBias } from '../api/client';
import { useAppStore } from '../store/appStore';

export function DirectionBiasBadge() {
  const directionBias = useAppStore((s) => s.directionBias);
  const setDirectionBias = useAppStore((s) => s.setDirectionBias);

  if (!directionBias) return null;

  const label = directionBias === 'BUY' ? 'קנייה' : 'מכירה';

  const cancel = async () => {
    setDirectionBias(null);
    try {
      await clearDirectionBias();
    } catch {
      // best-effort — a live bot_status broadcast or the next chat reply will resync it
    }
  };

  return (
    <span className="direction-bias-badge" title={`נקבע דרך הצ'אט — חוסם איתותים שאינם ${label}`}>
      ⏳ ממתין ל{label}
      <button type="button" onClick={cancel} aria-label="בטל חסימת כיוון">
        ✕
      </button>
    </span>
  );
}
