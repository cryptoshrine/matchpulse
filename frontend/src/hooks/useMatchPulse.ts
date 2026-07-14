/** Public WebSocket hook for MatchPulse state and notification updates. */

import { useEffect, useRef, useState } from 'react';
import type { LiveMatchState, LiveNotification } from '@/types/api';

interface UseMatchPulseParams {
  matchId: number | null;
  onNotification: (notification: LiveNotification) => void;
  onStateSnapshot: (state: LiveMatchState | null, momentumDelta: number) => void;
  enabled?: boolean;
}

interface UseMatchPulseReturn {
  connected: boolean;
}

interface MatchPulseMessage {
  type: 'live_update' | 'state_snapshot' | 'heartbeat';
  live_notification?: LiveNotification;
  state?: LiveMatchState | null;
  momentum_delta?: number;
}

const VISIBILITY_CLOSE_DELAY_MS = 60_000;
const RECONNECT_DELAY_MS = 3_000;

export function useMatchPulse({
  matchId,
  onNotification,
  onStateSnapshot,
  enabled = true,
}: UseMatchPulseParams): UseMatchPulseReturn {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);
  const visibilityCloseTimeoutRef = useRef<number | null>(null);
  const closedByVisibilityRef = useRef(false);

  const onNotificationRef = useRef(onNotification);
  onNotificationRef.current = onNotification;
  const onStateSnapshotRef = useRef(onStateSnapshot);
  onStateSnapshotRef.current = onStateSnapshot;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const matchIdRef = useRef(matchId);
  matchIdRef.current = matchId;

  useEffect(() => {
    if (matchId === null || !enabled) {
      setConnected(false);
      return;
    }

    let disposed = false;
    const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8123';
    const wsUrl = apiUrl.replace(/^http/, 'ws');
    const endpoint = `${wsUrl}/api/matchpulse/ws/${matchId}`;

    const clearPing = () => {
      if (pingIntervalRef.current !== null) {
        window.clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    };

    const connect = () => {
      if (disposed || !enabledRef.current || matchIdRef.current === null) return;

      const ws = new WebSocket(endpoint);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        setConnected(true);
        closedByVisibilityRef.current = false;
        clearPing();
        pingIntervalRef.current = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30_000);
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const message = JSON.parse(event.data) as MatchPulseMessage;
          if (message.type === 'live_update' && message.live_notification) {
            onNotificationRef.current(message.live_notification);
          } else if (message.type === 'state_snapshot') {
            onStateSnapshotRef.current(message.state ?? null, message.momentum_delta ?? 0);
          }
        } catch (error) {
          console.error('[useMatchPulse] Failed to parse message:', error);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        clearPing();
        if (disposed || closedByVisibilityRef.current) return;
        if (enabledRef.current && matchIdRef.current !== null) {
          reconnectTimeoutRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = (error) => {
        console.error('[useMatchPulse] WebSocket error:', error);
      };
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        if (
          visibilityCloseTimeoutRef.current === null &&
          wsRef.current?.readyState === WebSocket.OPEN
        ) {
          visibilityCloseTimeoutRef.current = window.setTimeout(() => {
            visibilityCloseTimeoutRef.current = null;
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              closedByVisibilityRef.current = true;
              wsRef.current.close();
              wsRef.current = null;
            }
          }, VISIBILITY_CLOSE_DELAY_MS);
        }
      } else {
        if (visibilityCloseTimeoutRef.current !== null) {
          window.clearTimeout(visibilityCloseTimeoutRef.current);
          visibilityCloseTimeoutRef.current = null;
        }
        if (closedByVisibilityRef.current && enabledRef.current && matchIdRef.current !== null) {
          closedByVisibilityRef.current = false;
          connect();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    connect();

    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (visibilityCloseTimeoutRef.current !== null) {
        window.clearTimeout(visibilityCloseTimeoutRef.current);
        visibilityCloseTimeoutRef.current = null;
      }
      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      clearPing();
      if (wsRef.current !== null) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [matchId, enabled]);

  return { connected };
}
