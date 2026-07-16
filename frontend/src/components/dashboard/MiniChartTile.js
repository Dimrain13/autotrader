import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import CandlestickChart from "../CandlestickChart";
import { barsCache } from "../../utils/barsCache";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// All 4 tiles refresh on the same 30s cadence (per user preference) - real
// Alpaca data either way, just less redraw churn than a faster interval.
const REFRESH_MS = 30000;
const LABELS = { "10Sec": "10 Sec", "1Min": "1 Min", "5Min": "5 Min", "1Day": "1 Day" };

// Bar counts sized to cover a FULL trading day (the app's own extended
// hours window is 4:00 AM - 8:00 PM ET, 16 hours) instead of an arbitrary
// fixed count that only fills a few minutes/hours on faster timeframes.
// 10Sec is naturally capped by how many raw trade ticks are still buffered
// server-side (no historical seconds-level data exists on Alpaca at all -
// it's built live from ticks) - requesting more than that simply returns
// whatever's actually available. 1Day is a multi-day lookback, not "a day".
const FULL_DAY_BAR_LIMIT = { "10Sec": 600, "1Min": 960, "5Min": 200, "1Day": 100 };

export function MiniChartTile({ symbol, timeframe, liveTrade, levels }) {
  const [bars, setBars] = useState([]);
  const [blockTrades, setBlockTrades] = useState([]);
  const [meta, setMeta] = useState({ source: null, warning: null });
  const barsRef = useRef([]);

  const fetchBars = useCallback((isIncremental = false) => {
    if (!symbol) return;
    const limit = FULL_DAY_BAR_LIMIT[timeframe] || 100;
    const params = { timeframe, limit };
    // Incremental refresh: we already have bars cached locally, so only ask
    // the backend for what's newer than the last one instead of re-pulling
    // the whole day's history every 30s - much lighter and faster.
    if (isIncremental && barsRef.current.length > 0) {
      params.since = barsRef.current[barsRef.current.length - 1].timestamp;
    }
    axios.get(`${API}/market/bars/${symbol}`, { params }).then((res) => {
      const fetched = res.data.bars || [];
      const merged = params.since ? barsCache.merge(barsRef.current, fetched, limit) : fetched;
      barsRef.current = merged;
      setBars(merged);
      setMeta({ source: res.data.source, warning: res.data.warning });
      if (merged.length > 0) barsCache.set(symbol, timeframe, merged);
    }).catch(() => {});
  }, [symbol, timeframe]);

  const fetchBlockTrades = useCallback(() => {
    if (!symbol) return;
    axios.get(`${API}/market/large-trades/${symbol}?limit=8`).then((res) => {
      setBlockTrades(res.data.large_trades || []);
    }).catch(() => {});
  }, [symbol]);

  useEffect(() => {
    if (!symbol) {
      barsRef.current = [];
      setBars([]);
      setBlockTrades([]);
      return;
    }

    // Paint instantly from the local cache (if this symbol/timeframe was
    // already loaded this session) while a fresh fetch runs in the
    // background, instead of flashing a blank "Loading real data..." state
    // every time the user re-selects a symbol they already viewed.
    const cached = barsCache.get(symbol, timeframe);
    barsRef.current = cached ? cached.bars : [];
    setBars(barsRef.current);
    setBlockTrades([]);

    fetchBars(!!cached);
    fetchBlockTrades();
    const barsInterval = setInterval(() => fetchBars(true), REFRESH_MS);
    const blockInterval = setInterval(fetchBlockTrades, REFRESH_MS);
    return () => { clearInterval(barsInterval); clearInterval(blockInterval); };
  }, [symbol, timeframe, fetchBars, fetchBlockTrades]);

  const vwap = bars.length > 0
    ? bars.reduce((sum, b) => sum + b.close * (b.volume || 0), 0) / Math.max(1, bars.reduce((sum, b) => sum + (b.volume || 0), 0))
    : null;
  const lastPrice = liveTrade?.price ?? (bars.length > 0 ? bars[bars.length - 1].close : null);

  return (
    <div className="flex flex-col h-full border border-neutral-800 rounded-lg overflow-hidden bg-[#0A0A0A]" data-testid={`chart-tile-${timeframe}`}>
      <div className="flex items-center justify-between px-2 py-1 bg-[#111111] border-b border-neutral-800 text-[10px]">
        <span className="font-semibold text-neutral-400 uppercase tracking-wider">{LABELS[timeframe]}</span>
        {lastPrice && <span className="font-mono text-neutral-300">${lastPrice.toFixed(2)}</span>}
      </div>
      <div className="flex-1 min-h-0">
        {!symbol ? (
          <div className="h-full flex items-center justify-center text-xs text-neutral-600">No symbol selected</div>
        ) : bars.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-neutral-600 text-center px-2">
            {meta.warning || "Loading real data..."}
          </div>
        ) : (
          <CandlestickChart data={bars} height={220} vwap={vwap} blockTrades={blockTrades} livePrice={liveTrade} levels={levels} />
        )}
      </div>
    </div>
  );
}
