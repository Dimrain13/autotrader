import { useState, useEffect } from "react";
import { AccountStrip } from "../components/dashboard/AccountStrip";
import { ScannerTable } from "../components/dashboard/ScannerTable";
import { ReadyToTradePanel } from "../components/dashboard/ReadyToTradePanel";
import { NewsFeedPanel } from "../components/dashboard/NewsFeedPanel";
import { ChartGrid } from "../components/dashboard/ChartGrid";
import { QuickTradePanel } from "../components/dashboard/QuickTradePanel";
import { OpenPositionsPanel } from "../components/dashboard/OpenPositionsPanel";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "../components/ui/resizable";
import { useMarketDataSocket } from "../hooks/useMarketDataSocket";

const getDashboardSetting = (key, fallback) => {
  const saved = localStorage.getItem(key);
  const parsed = parseFloat(saved);
  return saved !== null && !Number.isNaN(parsed) ? parsed : fallback;
};

// One-screen manual-review trading dashboard: scanner + 5/5 alerts + a
// 4-timeframe chart grid + news, inspired by (not copying) multi-panel
// scanner terminals like StocksToTrade/Trade Ideas. Charts only populate
// once a symbol is manually selected below - no auto-focus.
export default function Dashboard({ account, positions, scanner, onOrderPlaced }) {
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const { connected: streamConnected, trades, subscribe } = useMarketDataSocket();

  const results = scanner?.results || [];

  // Keep a frozen snapshot of the selected stock's last known scanner row so
  // it never visually vanishes from the table/panel mid-review just because
  // a later scan cycle no longer matches it (price cooled off, etc). Without
  // this, the highlighted row disappears out from under the user's cursor
  // every ~60s scan tick, which reads as "my selection got cleared".
  const [pinnedRow, setPinnedRow] = useState(null);
  useEffect(() => {
    if (!selectedSymbol) { setPinnedRow(null); return; }
    const live = results.find((r) => r.symbol === selectedSymbol);
    if (live) setPinnedRow(live);
    // if not found, keep whatever pinnedRow we already have (stale snapshot)
  }, [selectedSymbol, results]);

  // Subscribe the live WS feed to every symbol currently on the scanner
  // table (not just whichever one is selected/charted) so prices/% change
  // tick in real time between the ~60s full re-scans instead of sitting
  // stale until the next scan cycle.
  useEffect(() => {
    const syms = results.map((r) => r.symbol);
    if (syms.length > 0) subscribe(syms);
  }, [results, subscribe]);

  // Overlay live WS trade prices onto each scanner row, recomputing % change
  // from the row's prev_close (same reference the backend scan itself uses)
  // so the whole table keeps moving tick-by-tick, not just the selected chart.
  const withLivePrices = (rows) =>
    rows.map((r) => {
      const tick = trades[r.symbol];
      if (!tick) return r;
      const pctChange = r.prev_close > 0 ? ((tick.price - r.prev_close) / r.prev_close) * 100 : r.pct_change;
      return { ...r, current_price: tick.price, pct_change: pctChange };
    });

  const displayResults = withLivePrices((() => {
    if (!selectedSymbol) return results;
    const stillLive = results.some((r) => r.symbol === selectedSymbol);
    if (stillLive || !pinnedRow) return results;
    return [...results, { ...pinnedRow, _stale: true }];
  })());

  const selectedPosition = selectedSymbol
    ? (positions || []).find((p) => p.symbol === selectedSymbol) || null
    : null;
  const currentPrice = selectedSymbol
    ? trades[selectedSymbol]?.price
      || displayResults.find((r) => r.symbol === selectedSymbol)?.current_price
      || selectedPosition?.current_price
      || null
    : null;

  // Stop-loss / take-profit / trailing-stop lines drawn on every chart tile
  // for the selected symbol - reuses the exact same risk settings (shared
  // localStorage keys) configured on the Trading page/QuickTradePanel, so
  // the same trade's levels look identical everywhere in the app. Once a
  // position is open, the lines anchor to the REAL fill price instead of
  // the current price so they reflect the actual trade, not a moving target.
  // Use the bot's REAL per-position levels (enriched as `bot_levels` on the
  // /positions response) when the selected symbol is an open auto-trader
  // position, so the dashboard charts draw the exact same structural stop /
  // target / psych target / live trail the bot is trading against - matching
  // the Trading page. Fall back to flat % settings only when no bot level.
  const botLevels = selectedPosition?.bot_levels || null;
  const entryPrice = botLevels?.entry_price ?? (selectedPosition?.avg_entry_price || currentPrice);
  const levels = entryPrice ? {
    entry: entryPrice,
    stopLoss: botLevels?.stop_loss
      ?? Math.round(entryPrice * (1 - getDashboardSetting("stopLossPct", 1.0) / 100) * 100) / 100,
    profitTarget: botLevels?.profit_target
      ?? Math.round(entryPrice * (1 + getDashboardSetting("takeProfitPct", 2.0) / 100) * 100) / 100,
    trailingStop: botLevels?.trailing_stop
      ?? ((localStorage.getItem("stopType") || "trailing") === "trailing" && currentPrice
        ? Math.round(currentPrice * (1 - getDashboardSetting("trailingStopPct", 1.0) / 100) * 100) / 100
        : null),
    psychTarget: botLevels?.psych_target ?? null,
    partialSold: !!botLevels?.partial_sell_done,
  } : null;

  useEffect(() => {
    if (selectedSymbol) subscribe([selectedSymbol], true);
  }, [selectedSymbol, subscribe]);

  // Open positions must always keep a live trade/quote slot too, regardless
  // of whether they're currently charted.
  useEffect(() => {
    const heldSymbols = (positions || []).map((p) => p.symbol);
    if (heldSymbols.length > 0) subscribe(heldSymbols, true);
  }, [positions, subscribe]);

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]" data-testid="dashboard-page">
      <AccountStrip account={account} positions={positions} streamConnected={streamConnected} scanner={scanner} />
      <OpenPositionsPanel positions={positions} onOrderPlaced={onOrderPlaced} onSelect={setSelectedSymbol} selectedSymbol={selectedSymbol} />

      <div className="flex-1 p-2 min-h-0">
        <ResizablePanelGroup direction="horizontal" autoSaveId="dashboard-main-columns" id="dashboard-main-columns-group">
          {/* Left sidebar: Stocks (scanner + 5/5 alerts) on top, News on
              bottom - 50/50, independently resizable via the handle between
              them. */}
          <ResizablePanel id="dashboard-panel-left" order={1} defaultSize={32} minSize={20} className="min-h-0 pr-2">
            <ResizablePanelGroup direction="vertical" autoSaveId="dashboard-left-sidebar-rows" id="dashboard-left-sidebar-rows-group">
              <ResizablePanel id="dashboard-panel-stocks" order={1} defaultSize={50} minSize={20} className="flex flex-col gap-2 min-h-0 pb-2">
                <ReadyToTradePanel results={displayResults} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
                <div className="flex-1 min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A]">
                  <ScannerTable results={displayResults} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
                </div>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel id="dashboard-panel-news" order={2} defaultSize={50} minSize={15} className="min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A] p-2 pl-3 pt-2">
                <NewsFeedPanel symbol={selectedSymbol} scannerResults={results} />
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Right side: charts snapped here, sized by the handle above -
              4-chart grid for the selected symbol takes up the rest of the
              16:9 canvas. */}
          <ResizablePanel id="dashboard-panel-charts" order={2} defaultSize={68} minSize={40} className="min-h-0 flex flex-col pl-2">
            {selectedSymbol && (
              <div className="flex items-center justify-between mb-1 px-1 shrink-0">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-bold text-neutral-200" data-testid="selected-symbol-header">
                    {selectedSymbol}
                  </div>
                  {levels?.partialSold && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#FFB800]/20 text-[#FFB800] border border-[#FFB800]/40 shrink-0" title="1st target hit — holding runner to final target">
                      RUNNER
                    </span>
                  )}
                </div>
                <QuickTradePanel
                  symbol={selectedSymbol}
                  currentPrice={currentPrice}
                  position={selectedPosition}
                  account={account}
                  onOrderPlaced={onOrderPlaced}
                />
              </div>
            )}
            <div className="flex-1 min-h-0">
              <ChartGrid symbol={selectedSymbol} liveTrade={selectedSymbol ? trades[selectedSymbol] : null} levels={levels} />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
