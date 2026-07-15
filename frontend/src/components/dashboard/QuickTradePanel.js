import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

const getSetting = (key, fallback) => {
  const saved = localStorage.getItem(key);
  const parsed = parseFloat(saved);
  return saved !== null && !Number.isNaN(parsed) ? parsed : fallback;
};

// Fast one-click buy/sell for whatever symbol is currently loaded in the
// chart grid, right on the manual-review dashboard - no need to jump to the
// Trading page for a quick entry/exit. Reuses the exact same risk settings
// (stop loss / take profit / trailing stop / partial sell / position sizing
// mode) configured on the Trading page (shared localStorage keys), so
// orders behave identically no matter which screen they're placed from.
export function QuickTradePanel({ symbol, currentPrice, position, account, onOrderPlaced }) {
  const [qtyOverride, setQtyOverride] = useState(null);
  const [placing, setPlacing] = useState(false);

  useEffect(() => {
    setQtyOverride(null);
  }, [symbol]);

  if (!symbol) return null;

  const sizeMode = localStorage.getItem("positionSizeMode") === "percent" ? "percent" : "dollar";
  let dollarAmount = getSetting("dollarAmountPerStock", 100);
  if (sizeMode === "percent" && account?.portfolio_value > 0) {
    dollarAmount = account.portfolio_value * (getSetting("positionSizePct", 10) / 100);
  }
  const defaultQty = currentPrice > 0 ? Math.max(1, Math.floor(dollarAmount / currentPrice)) : 1;
  const buyQty = qtyOverride ?? defaultQty;

  const placeOrder = async (side) => {
    const sideQty = side === "sell" ? position?.qty || buyQty : buyQty;
    if (!sideQty || sideQty <= 0) return;
    setPlacing(true);
    try {
      const response = await axios.post(
        `${API}/orders`,
        {
          symbol,
          qty: sideQty,
          side,
          stop_loss_pct: getSetting("stopLossPct", 1),
          take_profit_pct: getSetting("takeProfitPct", 2),
          entry_price: currentPrice || undefined,
          stop_type: localStorage.getItem("stopType") || "fixed",
          trailing_stop_pct: getSetting("trailingStopPct", 1),
          partial_sell_pct: getSetting("partialSellPct", 50),
          partial_sell_trigger_pct: getSetting("partialSellTrigger", 2),
          move_to_breakeven: localStorage.getItem("moveToBreakeven") !== "false",
        },
        { timeout: 15000 }
      );
      const filled = response.data?.actual_price || response.data?.filled_avg_price || currentPrice;
      toast.success(
        `${side === "buy" ? "Bought" : "Sold"} ${sideQty} ${symbol} @ $${filled ? filled.toFixed(2) : "?"}`,
        { id: `quick-${side}-${symbol}` }
      );
      onOrderPlaced?.();
    } catch (error) {
      toast.error(`${side === "buy" ? "Buy" : "Sell"} ${symbol} failed: ${error.response?.data?.detail || error.message}`, {
        id: `quick-${side}-${symbol}`,
      });
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="flex items-center gap-2" data-testid="quick-trade-panel">
      <input
        type="number"
        min={1}
        value={buyQty}
        onChange={(e) => setQtyOverride(Math.max(1, parseInt(e.target.value, 10) || 1))}
        data-testid="quick-trade-qty-input"
        className="w-16 bg-[#111111] border border-neutral-700 rounded-md px-2 py-1 text-xs font-mono text-neutral-200 focus:outline-none focus:border-[#2E5CFF]"
      />
      <button
        onClick={() => placeOrder("buy")}
        disabled={placing || !currentPrice}
        data-testid="quick-trade-buy-button"
        className="px-3 py-1 rounded-md text-xs font-bold bg-[#00E599] text-black hover:bg-[#00E599]/90 disabled:opacity-40 transition-colors"
      >
        {placing ? "..." : "BUY"}
      </button>
      {position && (
        <button
          onClick={() => placeOrder("sell")}
          disabled={placing}
          data-testid="quick-trade-sell-button"
          className="px-3 py-1 rounded-md text-xs font-bold bg-[#FF1A40] text-white hover:bg-[#FF1A40]/90 disabled:opacity-40 transition-colors"
        >
          {placing ? "..." : `SELL ${position.qty}`}
        </button>
      )}
      {currentPrice > 0 && (
        <span className="text-[10px] text-neutral-500 font-mono" data-testid="quick-trade-est-cost">
          ~${(buyQty * currentPrice).toFixed(2)}
        </span>
      )}
    </div>
  );
}
