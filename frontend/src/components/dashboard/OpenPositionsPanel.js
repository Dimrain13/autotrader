import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { playTradeSound } from "../../utils/sound";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// Always-visible strip of every open position with an instant Sell 1/2 /
// Sell All action on each one - independent of whichever symbol happens to
// be selected/charted. Without this, a held position that scrolls off the
// scanner table (no longer matches scan criteria) becomes impossible to
// sell from the Dashboard at all, since the chart's QuickTradePanel only
// shows sell controls for the currently-selected symbol.
export function OpenPositionsPanel({ positions, onOrderPlaced }) {
  const [placingSymbol, setPlacingSymbol] = useState(null);
  const [sellingAll, setSellingAll] = useState(false);

  if (!positions || positions.length === 0) return null;

  const sellPosition = async (position, fraction = 1) => {
    const qty = Math.max(1, Math.min(position.qty, Math.round(position.qty * fraction)));
    setPlacingSymbol(position.symbol);
    try {
      const response = await axios.post(`${API}/orders`, {
        symbol: position.symbol,
        qty,
        side: "sell",
      }, { timeout: 15000 });
      const filled = response.data?.actual_price || response.data?.filled_avg_price || position.current_price;
      toast.success(`Sold ${qty} ${position.symbol} @ $${filled ? filled.toFixed(2) : "?"}`, {
        id: `positions-sell-${position.symbol}`,
      });
      playTradeSound();
      onOrderPlaced?.();
    } catch (error) {
      toast.error(`Sell ${position.symbol} failed: ${error.response?.data?.detail || error.message}`, {
        id: `positions-sell-${position.symbol}`,
      });
    } finally {
      setPlacingSymbol(null);
    }
  };

  const sellAllPositions = async () => {
    setSellingAll(true);
    let successCount = 0;
    let failCount = 0;
    for (const position of positions) {
      try {
        await axios.post(`${API}/orders`, { symbol: position.symbol, qty: position.qty, side: "sell" }, { timeout: 15000 });
        successCount += 1;
      } catch {
        failCount += 1;
      }
    }
    if (successCount > 0) {
      toast.success(`Sold ${successCount} position${successCount > 1 ? "s" : ""}`, { id: "positions-sell-all" });
      playTradeSound();
    }
    if (failCount > 0) {
      toast.error(`Failed to sell ${failCount} position${failCount > 1 ? "s" : ""}`, { id: "positions-sell-all-fail" });
    }
    onOrderPlaced?.();
    setSellingAll(false);
  };

  return (
    <div
      className="flex items-center gap-2 px-4 py-2 bg-[#111111] border-b border-neutral-800 overflow-x-auto"
      data-testid="open-positions-panel"
    >
      <span className="text-[10px] text-neutral-500 uppercase tracking-wider shrink-0">Positions</span>

      {positions.map((position) => {
        const plPositive = (position.unrealized_pl || 0) >= 0;
        const placing = placingSymbol === position.symbol;
        return (
          <div
            key={position.symbol}
            className="flex items-center gap-1.5 bg-[#0A0A0A] border border-neutral-800 rounded-md px-2 py-1 shrink-0"
            data-testid={`open-position-row-${position.symbol}`}
          >
            <div className="flex flex-col leading-tight mr-1">
              <span className="font-mono text-xs font-bold text-neutral-200">{position.symbol}</span>
              <span className={`font-mono text-[10px] ${plPositive ? "text-[#00E599]" : "text-[#FF1A40]"}`}>
                {plPositive ? "+" : ""}${(position.unrealized_pl || 0).toFixed(2)} · {position.qty} sh
              </span>
            </div>
            <button
              onClick={() => sellPosition(position, 0.5)}
              disabled={placing || sellingAll || position.qty < 2}
              data-testid={`open-position-sell-half-${position.symbol}`}
              title={position.qty < 2 ? "Position too small to split" : `Sell ~half (${Math.max(1, Math.round(position.qty * 0.5))} sh)`}
              className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#FF1A40]/20 text-[#FF1A40] border border-[#FF1A40]/40 hover:bg-[#FF1A40]/30 disabled:opacity-30 transition-colors"
            >
              {placing ? "..." : "1/2"}
            </button>
            <button
              onClick={() => sellPosition(position, 1)}
              disabled={placing || sellingAll}
              data-testid={`open-position-sell-all-${position.symbol}`}
              className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#FF1A40] text-white hover:bg-[#FF1A40]/90 disabled:opacity-40 transition-colors"
            >
              {placing ? "..." : "SELL"}
            </button>
          </div>
        );
      })}

      <div className="flex-1" />
      <button
        onClick={sellAllPositions}
        disabled={sellingAll || placingSymbol}
        data-testid="open-positions-sell-all-button"
        className="px-3 py-1 rounded-md text-xs font-bold bg-[#FF1A40] text-white hover:bg-[#FF1A40]/90 disabled:opacity-40 transition-colors shrink-0"
      >
        {sellingAll ? "SELLING..." : `SELL ALL (${positions.length})`}
      </button>
    </div>
  );
}
