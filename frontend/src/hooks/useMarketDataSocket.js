import { useEffect, useRef, useState, useCallback } from "react";
import { getToken } from "../lib/axiosConfig";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

function toWsUrl(httpUrl) {
  return httpUrl.replace(/^https/, "wss").replace(/^http/, "ws") + "/api/ws/market-data";
}

/**
 * Real-time Alpaca market data over a persistent WebSocket connection to the
 * backend (/api/ws/market-data), replacing REST polling for price ticks and
 * minute bars. Auto-reconnects with a fixed backoff and re-sends all
 * previously subscribed symbols on every reconnect.
 *
 * Returns:
 *   quotes: { [symbol]: { bid_price, ask_price, bid_size, ask_size, timestamp } }
 *   trades: { [symbol]: { price, size, timestamp } }
 *   bars:   { [symbol]: { timestamp, open, high, low, close, volume } } - latest completed 1-min bar
 *   connected: boolean
 *   subscribe(symbols: string[]): add symbols to the live stream
 */
export function useMarketDataSocket() {
  const [quotes, setQuotes] = useState({});
  const [trades, setTrades] = useState({});
  const [bars, setBars] = useState({});
  const [connected, setConnected] = useState(false);

  const wsRef = useRef(null);
  const subscribedRef = useRef(new Set());
  const reconnectTimerRef = useRef(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    const token = getToken();
    if (!token || !BACKEND_URL) return;

    const ws = new WebSocket(`${toWsUrl(BACKEND_URL)}?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      if (subscribedRef.current.size > 0) {
        ws.send(JSON.stringify({ action: "subscribe", symbols: Array.from(subscribedRef.current) }));
      }
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      const symbol = msg.S;
      if (!symbol) return;

      if (msg.T === "q") {
        setQuotes((prev) => ({
          ...prev,
          [symbol]: { bid_price: msg.bp, ask_price: msg.ap, bid_size: msg.bs, ask_size: msg.as, timestamp: msg.t },
        }));
      } else if (msg.T === "t") {
        setTrades((prev) => ({ ...prev, [symbol]: { price: msg.p, size: msg.s, timestamp: msg.t } }));
      } else if (msg.T === "b") {
        setBars((prev) => ({
          ...prev,
          [symbol]: { timestamp: msg.t, open: msg.o, high: msg.h, low: msg.l, close: msg.c, volume: msg.v },
        }));
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (mountedRef.current) {
        reconnectTimerRef.current = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  const subscribe = useCallback((symbols) => {
    const clean = (symbols || []).filter(Boolean).map((s) => s.toUpperCase());
    const newOnes = clean.filter((s) => !subscribedRef.current.has(s));
    clean.forEach((s) => subscribedRef.current.add(s));
    if (newOnes.length > 0 && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", symbols: newOnes }));
    }
  }, []);

  return { quotes, trades, bars, connected, subscribe };
}
