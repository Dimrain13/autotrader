import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import CandlestickChart from "../CandlestickChart";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// Real Alpaca data refresh cadence per timeframe - 10Sec ticks build up fast
// so it polls quickest; 1Day barely moves intraday so it polls slowest.
const REFRESH_MS = { "10Sec": 6000, "1Min": 15000, "5Min": 15000, "1Day": 45000 };
const LABELS = { "10Sec": "10 Sec", "1Min": "1 Min", "5Min": "5 Min", "1Day": "1 Day" };

export function MiniChartTile({ symbol, timeframe }) {
  const [bars, setBars] = useState([]);
  const [blockTrades, setBlockTrades] = useState([]);
  const [meta, setMeta] = useState({ source: null, warning: null });

  const fetchBars = useCallback(() => {
    if (!symbol) return;
    axios.get(`${API}/market/bars/${symbol}?timeframe=${timeframe}&limit=100`).then((res) => {
      setBars(res.data.bars || []);
      setMeta({ source: res.data.source, warning: res.data.warning });
    }).catch(() => {});
  }, [symbol, timeframe]);

  const fetchBlockTrades = useCallback(() => {
    if (!symbol) return;
    axios.get(`${API}/market/large-trades/${symbol}?limit=8`).then((res) => {
      setBlockTrades(res.data.large_trades || []);
    }).catch(() => {});
  }, [symbol]);

  useEffect(() => {
    setBars([]);
    setBlockTrades([]);
    if (!symbol) return;
    fetchBars();
    fetchBlockTrades();
    const barsInterval = setInterval(fetchBars, REFRESH_MS[timeframe] || 15000);
    const blockInterval = setInterval(fetchBlockTrades, 20000);
    return () => { clearInterval(barsInterval); clearInterval(blockInterval); };
  }, [symbol, timeframe, fetchBars, fetchBlockTrades]);

  const vwap = bars.length > 0
    ? bars.reduce((sum, b) => sum + b.close * (b.volume || 0), 0) / Math.max(1, bars.reduce((sum, b) => sum + (b.volume || 0), 0))
    : null;
  const lastPrice = bars.length > 0 ? bars[bars.length - 1].close : null;

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
          <CandlestickChart data={bars} height={220} vwap={vwap} blockTrades={blockTrades} />
        )}
      </div>
    </div>
  );
}
