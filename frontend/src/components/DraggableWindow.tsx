import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  headerClassName?: string;
}

const DEFAULT_WIDTH = 380;
const DEFAULT_HEIGHT = 480;
// Matches the `@media (max-width: 700px)` breakpoint in index.css, where
// .drag-window switches to calc(100vw - 24px) / calc(100vh - 24px) — below
// this width the window is effectively full-screen, not DEFAULT_WIDTH x
// DEFAULT_HEIGHT, so centering math based on the desktop size would place it
// off-screen (its real height is far taller than what the math assumed).
const MOBILE_BREAKPOINT = 700;

export function DraggableWindow({ title, onClose, children, headerClassName }: Props) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  // Center the window over the chart the first time it opens (full-screen
  // with a small margin on mobile, where the CSS breakpoint takes over).
  useEffect(() => {
    if (window.innerWidth <= MOBILE_BREAKPOINT) {
      setPos({ x: 12, y: 12 });
      return;
    }
    const width = Math.min(DEFAULT_WIDTH, window.innerWidth - 24);
    const height = Math.min(DEFAULT_HEIGHT, window.innerHeight - 24);
    setPos({ x: (window.innerWidth - width) / 2, y: (window.innerHeight - height) / 2 });
  }, []);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  function handleDragMove(e: MouseEvent) {
    const drag = dragRef.current;
    if (!drag) return;
    const width = windowRef.current?.offsetWidth ?? DEFAULT_WIDTH;
    const height = windowRef.current?.offsetHeight ?? DEFAULT_HEIGHT;
    const nextX = drag.originX + (e.clientX - drag.startX);
    const nextY = drag.originY + (e.clientY - drag.startY);
    setPos({
      x: Math.min(Math.max(0, nextX), window.innerWidth - width),
      y: Math.min(Math.max(0, nextY), window.innerHeight - height),
    });
  }

  function handleDragEnd() {
    dragRef.current = null;
    window.removeEventListener('mousemove', handleDragMove);
    window.removeEventListener('mouseup', handleDragEnd);
  }

  function handleDragStart(e: ReactMouseEvent) {
    if (!pos) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, originX: pos.x, originY: pos.y };
    window.addEventListener('mousemove', handleDragMove);
    window.addEventListener('mouseup', handleDragEnd);
  }

  if (!pos) return null;

  return (
    <div ref={windowRef} className="drag-window" style={{ left: pos.x, top: pos.y }}>
      <div className={`drag-window-header ${headerClassName ?? ''}`} onMouseDown={handleDragStart}>
        <h2>{title}</h2>
        <button type="button" className="modal-close" onClick={onClose} aria-label="סגור">
          ✕
        </button>
      </div>
      <div className="drag-window-body">{children}</div>
    </div>
  );
}
