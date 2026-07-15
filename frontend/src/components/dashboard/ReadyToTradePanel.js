import { NewsFlame } from "./ScannerCells";

// Dedicated always-visible alert strip for stocks that hit all 5 First
// Pullback criteria right now - the highest-priority manual-review signal.
export function ReadyToTradePanel({ results, selectedSymbol, onSelect }) {
  const ready = (results || []).filter((s) => s.ready_to_trade);

  return (
    <div className="border border-[#00E599]/30 rounded-lg bg-[#00E599]/5 p-2" data-testid="ready-to-trade-panel">
      <div className="text-[10px] uppercase tracking-wider text-[#00E599] font-semibold mb-1.5 px-1">
        5/5 Ready to Trade ({ready.length})
      </div>
      {ready.length === 0 ? (
        <div className="text-xs text-neutral-600 px-1 py-2">No 5/5 candidates right now</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {ready.map((s) => (
            <button
              key={s.symbol}
              onClick={() => onSelect(s.symbol)}
              data-testid={`ready-chip-${s.symbol}`}
              className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold border transition-colors ${
                selectedSymbol === s.symbol
                  ? "bg-[#00E599] text-black border-[#00E599]"
                  : "bg-black/40 text-[#00E599] border-[#00E599]/40 hover:bg-[#00E599]/15"
              }`}
            >
              {s.symbol}
              <NewsFlame freshness={s.news_freshness} hasNews={s.has_positive_news} />
              <span className="opacity-70 font-mono">${s.current_price?.toFixed(2)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
