import { useEffect, useRef, useState } from 'react';
import type { WsMessage } from '../types/market';

export type WsStatus = 'connecting' | 'open' | 'closed';

const MAX_BACKOFF_MS = 15000;

export function useWebSocket(onMessage: (msg: WsMessage) => void): WsStatus {
  const [status, setStatus] = useState<WsStatus>('connecting');
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 1000;
    let stopped = false;

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

      socket.onopen = () => {
        backoff = 1000;
        setStatus('open');
      };

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WsMessage;
          onMessageRef.current(msg);
        } catch {
          // ignore malformed messages
        }
      };

      socket.onclose = () => {
        if (stopped) return;
        setStatus('closed');
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return status;
}
