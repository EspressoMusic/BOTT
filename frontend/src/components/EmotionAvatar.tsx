import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../store/appStore';
import type { WsMessage } from '../types/market';

interface Props {
  latestMessage: WsMessage | null;
}

type Expression = 'idle' | 'happy' | 'angry';

const HAPPY_FACES = ['🤑', '😄', '🥳', '😎'];
const HAPPY_LINES = [
  'יש!! עוד עסקה שמנה בכיס!',
  'ישססס, ROI רק עולה!',
  'מי גדול? אני גדול!',
  'זהב טהור, ממש כמו השם שלי.',
  'קדימה שוק, תמשיך ככה!',
];

const ANGRY_FACES = ['😡', '🤬', '😤', '💢'];
const ANGRY_LINES = [
  'אוףףף... זה כאב.',
  'השוק ממש מרושע היום.',
  'טוב זהו, אני צריך רגע להתאושש.',
  'מי שם את הסטופ לוס שם?! אה, אני.',
  'סטופ לוס. שוב. בסדר. בסדר!!',
];

const IDLE_FACE = '🤖';

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

export function EmotionAvatar({ latestMessage }: Props) {
  const enabled = useAppStore((s) => s.emotionModeEnabled);
  const [expression, setExpression] = useState<Expression>('idle');
  const [face, setFace] = useState(IDLE_FACE);
  const [caption, setCaption] = useState<string | null>(null);
  const revertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled || !latestMessage || latestMessage.type !== 'trade_closed') return;
    const pnl = latestMessage.payload.pnl ?? 0;
    const won = pnl > 0;

    setExpression(won ? 'happy' : 'angry');
    setFace(pick(won ? HAPPY_FACES : ANGRY_FACES));
    setCaption(pick(won ? HAPPY_LINES : ANGRY_LINES));

    if (revertTimer.current) clearTimeout(revertTimer.current);
    revertTimer.current = setTimeout(() => {
      setExpression('idle');
      setFace(IDLE_FACE);
      setCaption(null);
    }, 6000);
  }, [latestMessage, enabled]);

  useEffect(() => {
    return () => {
      if (revertTimer.current) clearTimeout(revertTimer.current);
    };
  }, []);

  if (!enabled) return null;

  return (
    <div className={`emotion-avatar emotion-${expression}`}>
      <div className="emotion-face">{face}</div>
      {caption && <div className="emotion-caption">{caption}</div>}
    </div>
  );
}
