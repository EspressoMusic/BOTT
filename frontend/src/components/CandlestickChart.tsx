import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import { fetchCandles, fetchThoughts, fetchTrades } from '../api/client';
import { useAppStore } from '../store/appStore';
import type { Candle, ChartZone, Granularity, Trade, WsMessage } from '../types/market';

interface Props {
  granularity: Granularity;
  latestMessage: WsMessage | null;
  openTrade: Trade | null;
  annotating: boolean;
  onZoneSelected: (zone: ChartZone) => void;
  onModifyTrade: (tradeId: number, update: { stop_loss?: number; take_profit?: number }) => void;
  onCloseTrade: (tradeId: number) => void;
}

// A mousedown within this many pixels of the SL/TP line's y-coordinate grabs
// that line for dragging, instead of panning the chart.
const LINE_GRAB_TOLERANCE_PX = 6;

// Fewer visible bars = more pixels per candle = tighter, gap-free-looking spacing.
const RECENT_BARS_VISIBLE = 70;

// Chart colors mirror the CSS theme variables — lightweight-charts renders to
// its own canvas, so it can't read CSS custom properties directly.
const CHART_THEME_COLORS = {
  warm: { bg: '#18130f', text: '#d9cab3', up: '#8fac6f', down: '#c96f4f', ema: '#4dabf7' },
  dark: { bg: '#0b0d12', text: '#d1d5db', up: '#26a69a', down: '#ef5350', ema: '#4dabf7' },
  light: { bg: '#f7f5f1', text: '#3a3630', up: '#2e7d4f', down: '#c1392b', ema: '#1c7ed6' },
} as const;

interface DragState {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

// Trade markers/SL-TP lines only make sense on the timeframe the strategy
// actually operates on — an M1-timed entry marker plotted on an H1 chart
// wouldn't line up with any real bar.
const TRADE_MARKER_GRANULARITY: Granularity = 'M1';

function toBar(c: Candle) {
  return { time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close };
}

// lightweight-charts formats its axis/crosshair labels using the timestamp's
// UTC fields by default, ignoring the viewer's actual timezone. All candle
// times are UTC-seconds anyway, so we render them explicitly in Israel time
// instead of relying on that default (or the browser's local timezone).
const CHART_TIMEZONE = 'Asia/Jerusalem';
const tickTimeFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: CHART_TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const tickDayFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: CHART_TIMEZONE,
  day: 'numeric',
  month: 'short',
});
const tickMonthFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: CHART_TIMEZONE,
  month: 'short',
  year: 'numeric',
});
const tickYearFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: CHART_TIMEZONE,
  year: 'numeric',
});
const crosshairTimeFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: CHART_TIMEZONE,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

function formatTickMark(time: Time, tickMarkType: TickMarkType): string {
  const date = new Date((time as UTCTimestamp) * 1000);
  switch (tickMarkType) {
    case TickMarkType.Year:
      return tickYearFormatter.format(date);
    case TickMarkType.Month:
      return tickMonthFormatter.format(date);
    case TickMarkType.DayOfMonth:
      return tickDayFormatter.format(date);
    default:
      return tickTimeFormatter.format(date);
  }
}

function formatCrosshairTime(time: Time): string {
  return crosshairTimeFormatter.format(new Date((time as UTCTimestamp) * 1000));
}

export function CandlestickChart({
  granularity,
  latestMessage,
  openTrade,
  annotating,
  onZoneSelected,
  onModifyTrade,
  onCloseTrade,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);
  const tpLineRef = useRef<IPriceLine | null>(null);
  const entryLineRef = useRef<IPriceLine | null>(null);
  const lastBarTimeRef = useRef<number>(0);
  const [error, setError] = useState<string | null>(null);
  // Drag state lives in a ref (always synchronously current) so rapid native
  // mousemove events can't race a stale React-state closure; `drag` (state)
  // exists purely to trigger a re-render for drawing the selection box.
  const dragRef = useRef<DragState | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const theme = useAppStore((s) => s.theme);
  const thoughtsVisible = useAppStore((s) => s.thoughtsVisible);
  const instrument = useAppStore((s) => s.instrument);
  // The strategy's current directional lean while flat (no open trade) — shown
  // as an intent arrow on the chart, tied to the same visibility toggle as the
  // thought bubble.
  const [bias, setBias] = useState<{ direction: 'BUY' | 'SELL'; candleTime: number } | null>(null);

  useEffect(() => {
    if (!latestMessage || latestMessage.type !== 'thought') return;
    const { bias: nextBias, candle_time } = latestMessage.payload;
    setBias(nextBias ? { direction: nextBias, candleTime: candle_time } : null);
  }, [latestMessage]);

  // Closed-trade history, so past entries/exits stay visible on the chart
  // (not just the currently open position) — sourced from the real trade
  // records in the DB, never invented client-side.
  const [closedTrades, setClosedTrades] = useState<Trade[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchTrades('CLOSED', instrument)
      .then((res) => {
        if (!cancelled) setClosedTrades(res.trades);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [instrument]);

  useEffect(() => {
    if (!latestMessage || latestMessage.type !== 'trade_closed') return;
    const closed = latestMessage.payload;
    if (closed.instrument !== instrument) return;
    setClosedTrades((prev) => (prev.some((t) => t.id === closed.id) ? prev : [...prev, closed]));
  }, [latestMessage, instrument]);

  // EMA50 line, backfilled from the real thought log (same ema50 the bot's
  // own EMA50 entry filter checked against) — only meaningful on the M1 chart,
  // since that's the only granularity the strategy engine actually computes it
  // on (see TRADE_MARKER_GRANULARITY above for the same reasoning).
  useEffect(() => {
    // Cleared eagerly (not just once the fetch below resolves) so a switch
    // never leaves the previous instrument's EMA50 line on screen — mismatched
    // scale from whatever asset was active before (e.g. gold's ~4400 range
    // still drawn under BTC's ~60000 candles) is exactly the kind of "does the
    // bot even know what it's looking at" confusion this line exists to avoid.
    ema50SeriesRef.current?.setData([]);
    if (granularity !== TRADE_MARKER_GRANULARITY) return;
    let cancelled = false;
    fetchThoughts(500, instrument)
      .then((res) => {
        if (cancelled) return;
        const byTime = new Map<number, number>();
        for (const t of res.thoughts) {
          const value = t.indicators?.ema50;
          if (typeof value === 'number') byTime.set(t.candle_time, value);
        }
        const points = [...byTime.entries()]
          .sort(([a], [b]) => a - b)
          .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
        ema50SeriesRef.current?.setData(points);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [granularity, instrument]);

  // Live EMA50 updates as each new M1 thought comes in over the WS.
  useEffect(() => {
    if (granularity !== TRADE_MARKER_GRANULARITY) return;
    if (!latestMessage || latestMessage.type !== 'thought') return;
    if (latestMessage.payload.instrument && latestMessage.payload.instrument !== instrument) return;
    const { candle_time, indicators } = latestMessage.payload;
    const value = indicators?.ema50;
    if (typeof value !== 'number') return;
    ema50SeriesRef.current?.update({ time: candle_time as UTCTimestamp, value });
  }, [latestMessage, granularity, instrument]);

  // Live price + PnL badge that rides the current-price line on the right
  // edge — replaces the chart's own last-value label while a trade is open,
  // and reveals a close (✕) button on hover.
  const [priceBadge, setPriceBadge] = useState<{ y: number; price: number; pnl: number } | null>(null);

  useEffect(() => {
    if (!openTrade) {
      setPriceBadge(null);
      return;
    }
    if (!latestMessage) return;
    if (latestMessage.type !== 'candle_update' && latestMessage.type !== 'candle_closed') return;
    if (latestMessage.payload.granularity !== granularity) return;
    const lastPrice = latestMessage.payload.candle.close;
    const y = seriesRef.current?.priceToCoordinate(lastPrice);
    if (y == null) return;
    const direction = openTrade.side === 'BUY' ? 1 : -1;
    const pnl = (lastPrice - openTrade.entry_price) * direction * openTrade.units;
    setPriceBadge({ y, price: lastPrice, pnl });
  }, [latestMessage, openTrade, granularity]);

  // Hide the chart's own current-price line/label while the custom PnL badge
  // above is showing in its place.
  useEffect(() => {
    seriesRef.current?.applyOptions({ lastValueVisible: !openTrade, priceLineVisible: !openTrade });
  }, [openTrade]);

  // Create the chart once.
  useEffect(() => {
    if (!containerRef.current) return;

    const colors = CHART_THEME_COLORS[theme];
    const chart = createChart(containerRef.current, {
      layout: { background: { color: colors.bg }, textColor: colors.text },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: formatTickMark },
      localization: { timeFormatter: formatCrosshairTime },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderVisible: false,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });

    // The exact EMA50 the bot itself computes (from strategy_engine, always on
    // M1 — see the ema50SeriesRef effects below) — real values pulled from the
    // same /api/thoughts history the bot's own decisions are logged with,
    // never recomputed client-side, so this line can never silently drift
    // from what actually gated a trade.
    const ema50Series = chart.addSeries(LineSeries, {
      color: colors.ema,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: 'EMA50',
    });

    chartRef.current = chart;
    seriesRef.current = series;
    ema50SeriesRef.current = ema50Series;
    markersRef.current = createSeriesMarkers(series, []);

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      chart.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      ema50SeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Backfill historical candles whenever the selected timeframe or the active
  // trading instrument changes (switching asset resets the chart entirely).
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setBias(null);
    // Block live updates until the new backfill lands — our live in-memory
    // aggregator and the REST backfill's historical bars aren't bucketed by
    // exactly the same clock, so a stray update for the new granularity could
    // otherwise race ahead of setData() and target the wrong data.
    lastBarTimeRef.current = Number.POSITIVE_INFINITY;
    fetchCandles(granularity)
      .then((res) => {
        if (cancelled || !seriesRef.current) return;
        seriesRef.current.setData(res.candles.map(toBar));
        // Show only the most recent bars (not the full backfill) so the
        // current price is immediately visible and zoomed in on load,
        // instead of a zoomed-out view where it can be hard to spot.
        const total = res.candles.length;
        const from = Math.max(0, total - RECENT_BARS_VISIBLE);
        chartRef.current?.timeScale().setVisibleLogicalRange({ from, to: total - 1 + 3 });
        const last = res.candles[res.candles.length - 1];
        lastBarTimeRef.current = last ? last.time : 0;
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [granularity, instrument]);

  // Apply live tick/candle updates without resetting zoom/scroll (series.update
  // patches the last bar in place or appends a new one, unlike setData). Guarded
  // against out-of-order/stale candles, which lightweight-charts otherwise throws on.
  useEffect(() => {
    if (!latestMessage) return;
    if (latestMessage.type !== 'candle_update' && latestMessage.type !== 'candle_closed') return;
    const { granularity: msgGranularity, candle } = latestMessage.payload;
    if (msgGranularity !== granularity) return;
    if (candle.time < lastBarTimeRef.current) return;
    try {
      seriesRef.current?.update(toBar(candle));
      lastBarTimeRef.current = candle.time;
    } catch (err) {
      console.warn('Skipped out-of-order candle update', err);
    }
  }, [latestMessage, granularity]);

  // Entry marker + SL/TP lines for the currently open position (if any).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const colors = CHART_THEME_COLORS[theme];

    if (slLineRef.current) {
      series.removePriceLine(slLineRef.current);
      slLineRef.current = null;
    }
    if (tpLineRef.current) {
      series.removePriceLine(tpLineRef.current);
      tpLineRef.current = null;
    }
    if (entryLineRef.current) {
      series.removePriceLine(entryLineRef.current);
      entryLineRef.current = null;
    }

    const markers: SeriesMarker<Time>[] = [];

    // Past trades — real entry/exit fills pulled from the trade history (DB),
    // not derived from the currently displayed candles, so they stay correct
    // even after scrolling/reloading the chart.
    if (granularity === TRADE_MARKER_GRANULARITY) {
      for (const t of closedTrades) {
        markers.push({
          time: t.entry_time as UTCTimestamp,
          position: t.side === 'BUY' ? 'belowBar' : 'aboveBar',
          color: t.side === 'BUY' ? colors.up : colors.down,
          shape: t.side === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: t.side === 'BUY' ? 'כניסה' : 'כניסה',
        });
        if (t.exit_time != null) {
          const won = (t.pnl ?? 0) > 0;
          markers.push({
            time: t.exit_time as UTCTimestamp,
            position: 'inBar',
            color: won ? colors.up : colors.down,
            shape: 'circle',
            text: `${t.exit_reason ?? 'יציאה'} ${won ? '+' : ''}${(t.pnl ?? 0).toFixed(1)}$`,
          });
        }
      }
    }

    if (!openTrade) {
      // Flat — show the strategy's current lean as an intent arrow instead,
      // tied to the same visibility toggle as the thought bubble.
      if (bias && thoughtsVisible && granularity === TRADE_MARKER_GRANULARITY) {
        markers.push({
          time: bias.candleTime as UTCTimestamp,
          position: bias.direction === 'BUY' ? 'belowBar' : 'aboveBar',
          color: bias.direction === 'BUY' ? colors.up : colors.down,
          shape: bias.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: bias.direction === 'BUY' ? 'לקנייה' : 'למכירה',
        });
      }
      markers.sort((a, b) => (a.time as number) - (b.time as number));
      markersRef.current?.setMarkers(markers);
      return;
    }
    if (granularity !== TRADE_MARKER_GRANULARITY) {
      markers.sort((a, b) => (a.time as number) - (b.time as number));
      markersRef.current?.setMarkers(markers);
      return;
    }

    markers.push({
      time: openTrade.entry_time as UTCTimestamp,
      position: openTrade.side === 'BUY' ? 'belowBar' : 'aboveBar',
      color: openTrade.side === 'BUY' ? colors.up : colors.down,
      shape: openTrade.side === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: openTrade.side === 'BUY' ? 'כניסה — קנייה' : 'כניסה — מכירה',
    });
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current?.setMarkers(markers);

    entryLineRef.current = series.createPriceLine({
      price: openTrade.entry_price,
      color: colors.text,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      // No axis label here — the current-price badge (chart-price-badge,
      // price + live PnL) sits in that same right-edge spot and, whenever
      // price is trading near entry (a trade hovering around breakeven,
      // which happens constantly), the two would overlap and the badge —
      // the one with the actually useful info — ends up half-hidden behind
      // "כניסה". The dotted line itself still marks the entry on the chart.
      axisLabelVisible: false,
      title: 'כניסה',
    });

    if (openTrade.stop_loss != null) {
      slLineRef.current = series.createPriceLine({
        price: openTrade.stop_loss,
        color: colors.down,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL',
      });
    }
    if (openTrade.take_profit != null) {
      tpLineRef.current = series.createPriceLine({
        price: openTrade.take_profit,
        color: colors.up,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'TP',
      });
    }
  }, [openTrade, granularity, theme, bias, thoughtsVisible, closedTrades]);

  // Re-paint the chart's own canvas colors when the theme is toggled — the
  // creation effect above only sets them once, at mount.
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    const colors = CHART_THEME_COLORS[theme];
    chart.applyOptions({ layout: { background: { color: colors.bg }, textColor: colors.text } });
    series.applyOptions({
      upColor: colors.up,
      downColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });
    ema50SeriesRef.current?.applyOptions({ color: colors.ema });
  }, [theme]);

  // Drag the SL/TP lines directly on the chart to move an open trade's stop
  // or target (e.g. dragging SL up to entry for a break-even stop). Disabled
  // while annotating a zone, which owns mouse events via its own overlay.
  const draggingLineRef = useRef<'sl' | 'tp' | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const chart = chartRef.current;
    if (!container || !chart || annotating) return;
    if (!openTrade || granularity !== TRADE_MARKER_GRANULARITY) return;
    const trade = openTrade;

    function priceLineAt(y: number): 'sl' | 'tp' | null {
      const series = seriesRef.current;
      if (!series) return null;
      if (slLineRef.current && trade.stop_loss != null) {
        const slY = series.priceToCoordinate(trade.stop_loss);
        if (slY != null && Math.abs(slY - y) <= LINE_GRAB_TOLERANCE_PX) return 'sl';
      }
      if (tpLineRef.current && trade.take_profit != null) {
        const tpY = series.priceToCoordinate(trade.take_profit);
        if (tpY != null && Math.abs(tpY - y) <= LINE_GRAB_TOLERANCE_PX) return 'tp';
      }
      return null;
    }

    function handleMouseDown(e: MouseEvent) {
      const rect = container!.getBoundingClientRect();
      const hit = priceLineAt(e.clientY - rect.top);
      if (!hit) return;
      draggingLineRef.current = hit;
      chart!.applyOptions({ handleScroll: false, handleScale: false });
      container!.style.cursor = 'ns-resize';
    }

    function handleMouseMove(e: MouseEvent) {
      const rect = container!.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const dragging = draggingLineRef.current;
      if (!dragging) {
        container!.style.cursor = priceLineAt(y) ? 'ns-resize' : '';
        return;
      }
      const price = seriesRef.current?.coordinateToPrice(y);
      if (price == null) return;
      const line = dragging === 'sl' ? slLineRef.current : tpLineRef.current;
      line?.applyOptions({ price });
    }

    function handleMouseUp() {
      const dragging = draggingLineRef.current;
      draggingLineRef.current = null;
      chart!.applyOptions({ handleScroll: true, handleScale: true });
      container!.style.cursor = '';
      if (!dragging) return;
      const line = dragging === 'sl' ? slLineRef.current : tpLineRef.current;
      const price = line?.options().price;
      if (price == null) return;
      onModifyTrade(trade.id, dragging === 'sl' ? { stop_loss: price } : { take_profit: price });
    }

    container.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      container.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      draggingLineRef.current = null;
      container.style.cursor = '';
    };
  }, [openTrade, annotating, granularity, onModifyTrade]);

  // The overlay (z-index above the chart's own canvases) already intercepts all
  // pointer events while marking a zone, so the chart underneath never sees
  // them — no need to separately disable its pan/zoom handlers.
  useEffect(() => {
    if (!annotating) {
      dragRef.current = null;
      setDrag(null);
    }
  }, [annotating]);

  function handleMouseDown(e: ReactMouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const next = { startX: x, startY: y, curX: x, curY: y };
    dragRef.current = next;
    setDrag(next);
  }

  function handleMouseMove(e: ReactMouseEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const next = { ...dragRef.current, curX: e.clientX - rect.left, curY: e.clientY - rect.top };
    dragRef.current = next;
    setDrag(next);
  }

  function tryComputeZone(startX: number, startY: number, curX: number, curY: number): ChartZone | null {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return null;
    const startTime = chart.timeScale().coordinateToTime(Math.min(startX, curX));
    const endTime = chart.timeScale().coordinateToTime(Math.max(startX, curX));
    // Pixel Y grows downward, price grows upward — the smaller Y is the higher price.
    const priceHigh = series.coordinateToPrice(Math.min(startY, curY));
    const priceLow = series.coordinateToPrice(Math.max(startY, curY));
    if (startTime == null || endTime == null || priceHigh == null || priceLow == null) return null;
    return { start_time: Number(startTime), end_time: Number(endTime), price_low: priceLow, price_high: priceHigh };
  }

  function handleMouseUp() {
    const activeDrag = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!activeDrag) return;
    const { startX, startY, curX, curY } = activeDrag;
    if (Math.abs(curX - startX) < 5 || Math.abs(curY - startY) < 5) return; // too small to be intentional

    const zone = tryComputeZone(startX, startY, curX, curY);
    if (zone) {
      onZoneSelected(zone);
      return;
    }
    // lightweight-charts' coordinate<->price/time conversion can transiently
    // return null (e.g. right after a fresh chart mount, or when mouseup lands
    // before the library's own layout pass has run) — back off and retry a
    // few times before giving up.
    const delays = [0, 50, 150, 300];
    let attempt = 0;
    const retry = () => {
      const result = tryComputeZone(startX, startY, curX, curY);
      if (result) {
        onZoneSelected(result);
        return;
      }
      attempt += 1;
      if (attempt < delays.length) {
        setTimeout(retry, delays[attempt]);
      }
    };
    setTimeout(retry, delays[0]);
  }

  const selectionStyle = drag
    ? {
        left: Math.min(drag.startX, drag.curX),
        top: Math.min(drag.startY, drag.curY),
        width: Math.abs(drag.curX - drag.startX),
        height: Math.abs(drag.curY - drag.startY),
      }
    : null;

  return (
    <div className="chart-wrapper">
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      {annotating && (
        <div
          className="chart-annotate-overlay"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            dragRef.current = null;
            setDrag(null);
          }}
        >
          {selectionStyle && <div className="chart-selection-box" style={selectionStyle} />}
        </div>
      )}
      {error && <div className="chart-error">שגיאה בטעינת נתונים: {error}</div>}
      {priceBadge && openTrade && (
        <div
          className={`chart-price-badge ${priceBadge.pnl >= 0 ? 'pnl-up' : 'pnl-down'}`}
          style={{ top: priceBadge.y }}
          onClick={() => onCloseTrade(openTrade.id)}
          title="לחצו לסגירת העסקה"
        >
          <span className="chart-price-badge-price">{priceBadge.price.toFixed(2)}</span>
          <span className="chart-price-badge-amount">
            {priceBadge.pnl >= 0 ? '+' : ''}
            {priceBadge.pnl.toFixed(2)}$
          </span>
          <span className="chart-price-badge-close">✕</span>
        </div>
      )}
    </div>
  );
}
