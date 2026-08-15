import { closePosition, modifyPosition } from '../api/client';
import { CandlestickChart } from '../components/CandlestickChart';
import { EmotionAvatar } from '../components/EmotionAvatar';
import { ThoughtsFeed } from '../components/ThoughtsFeed';
import { useAppStore } from '../store/appStore';
import type { ChartZone, Granularity, WsMessage } from '../types/market';

interface Props {
  latestMessage: WsMessage | null;
  granularity: Granularity;
  annotating: boolean;
  onZoneSelected: (zone: ChartZone) => void;
}

export function TradingPage({ latestMessage, granularity, annotating, onZoneSelected }: Props) {
  const openTrade = useAppStore((s) => s.openTrade);

  const handleModifyTrade = (tradeId: number, update: { stop_loss?: number; take_profit?: number }) => {
    modifyPosition(tradeId, update).catch(() => {
      // best-effort; the trade_modified WS event (or next poll) will reconcile state
    });
  };

  const handleCloseTrade = (tradeId: number) => {
    closePosition(tradeId).catch(() => {
      // best-effort; the trade_closed WS event (or next poll) will reconcile state
    });
  };

  return (
    <main className="main-layout">
      <div className="chart-area">
        <CandlestickChart
          granularity={granularity}
          latestMessage={latestMessage}
          openTrade={openTrade}
          annotating={annotating}
          onZoneSelected={onZoneSelected}
          onModifyTrade={handleModifyTrade}
          onCloseTrade={handleCloseTrade}
        />
        <div className="chart-icon-row">
          <ThoughtsFeed latestMessage={latestMessage} />
        </div>
        <EmotionAvatar latestMessage={latestMessage} />
      </div>
    </main>
  );
}
