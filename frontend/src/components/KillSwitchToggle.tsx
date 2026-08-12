import { disableBot, enableBot } from '../api/client';
import { useAppStore } from '../store/appStore';

export function KillSwitchToggle() {
  const botEnabled = useAppStore((s) => s.botEnabled);
  const setBotEnabled = useAppStore((s) => s.setBotEnabled);

  const toggle = async () => {
    const next = !botEnabled;
    setBotEnabled(next);
    try {
      if (next) await enableBot();
      else await disableBot();
    } catch {
      setBotEnabled(!next); // revert on failure — the server is the source of truth
    }
  };

  return (
    <button
      type="button"
      className={`bot-switch ${botEnabled ? 'on' : 'off'}`}
      onClick={toggle}
      role="switch"
      aria-checked={botEnabled}
      title={botEnabled ? 'הבוט פועל — לחצו לכיבוי' : 'הבוט כבוי — לחצו להפעלה'}
    >
      <span className="bot-switch-knob" />
    </button>
  );
}
