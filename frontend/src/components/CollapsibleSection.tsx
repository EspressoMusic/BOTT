import { useState, type ReactNode } from 'react';

interface Props {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function CollapsibleSection({ title, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="collapsible-section">
      <button type="button" className="collapsible-header" onClick={() => setOpen((v) => !v)}>
        <span>{title}</span>
        <span className={`collapsible-chevron ${open ? 'open' : ''}`}>▾</span>
      </button>
      {open && <div className="collapsible-body">{children}</div>}
    </section>
  );
}
