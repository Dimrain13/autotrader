import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { playTradeSound } from "../../utils/sound";

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
  let dollarAmount = getSetting("dollarAmountPerStock", 2000);
  // Margin trading, always at the max - size off buying power (includes
  // margin), never unlevered portfolio_value/equity.
  const buyingPower = account?.margin_buying_power || account?.buying_power || account?.portfolio_value;
  if (sizeMode === "percent" && buyingPower > 0) {
    // Clamp defensively (1-100%) - a stray/corrupted stored value should
    // never be able to size an order at multiples of the whole account.
    const safePct = Math.min(100, Math.max(1, getSetting("positionSizePct", 10)));
    dollarAmount = buyingPower * (safePct / 100);
  }
  const defaultQty = currentPrice > 0 ? Math.max(1, Math.floor(dollarAmount / currentPrice)) : 1;
  const buyQty = qtyOverride ?? defaultQty;

  // `sellFraction` lets a held position be closed in full (1) or trimmed by
  // half (0.5) with one click, instead of always closing the whole position.
  const placeOrder = async (side, sellFraction = 1) => {
    const heldQty = position?.qty || 0;
    const sideQty = side === "sell" ? Math.max(1, Math.min(heldQty, Math.round(heldQty * sellFraction))) : buyQty;
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
          stop_type: localStorage.getItem("stopType") || "trailing",
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
      playTradeSound();
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
        <div className="flex items-center gap-1">
          <button
            onClick={() => placeOrder("sell", 0.5)}
            disabled={placing || position.qty < 2}
            data-testid="quick-trade-sell-half-button"
            title={position.qty < 2 ? "Position too small to split" : `Sell ~half (${Math.max(1, Math.round(position.qty * 0.5))} sh)`}
            className="px-2.5 py-1 rounded-md text-xs font-bold bg-[#FF1A40]/20 text-[#FF1A40] border border-[#FF1A40]/40 hover:bg-[#FF1A40]/30 disabled:opacity-30 transition-colors"
          >
            {placing ? "..." : "SELL 1/2"}
          </button>
          <button
            onClick={() => placeOrder("sell", 1)}
            disabled={placing}
            data-testid="quick-trade-sell-all-button"
            className="px-2.5 py-1 rounded-md text-xs font-bold bg-[#FF1A40] text-white hover:bg-[#FF1A40]/90 disabled:opacity-40 transition-colors"
          >
            {placing ? "..." : `SELL ALL ${position.qty}`}
          </button>
        </div>
      )}
      {currentPrice > 0 && (
        <span className="text-[10px] text-neutral-500 font-mono" data-testid="quick-trade-est-cost">
          ~${(buyQty * currentPrice).toFixed(2)}
        </span>
      )}
    </div>
  );
}
