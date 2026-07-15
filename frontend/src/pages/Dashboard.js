import { useState, useEffect } from "react";
import { AccountStrip } from "../components/dashboard/AccountStrip";
import { ScannerTable } from "../components/dashboard/ScannerTable";
import { ReadyToTradePanel } from "../components/dashboard/ReadyToTradePanel";
import { NewsFeedPanel } from "../components/dashboard/NewsFeedPanel";
import { ChartGrid } from "../components/dashboard/ChartGrid";
import { QuickTradePanel } from "../components/dashboard/QuickTradePanel";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "../components/ui/resizable";
import { useMarketDataSocket } from "../hooks/useMarketDataSocket";

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

  const currentPrice = selectedSymbol
    ? trades[selectedSymbol]?.price || displayResults.find((r) => r.symbol === selectedSymbol)?.current_price || null
    : null;
  const selectedPosition = selectedSymbol
    ? (positions || []).find((p) => p.symbol === selectedSymbol) || null
    : null;

  useEffect(() => {
    if (selectedSymbol) subscribe([selectedSymbol]);
  }, [selectedSymbol, subscribe]);

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]" data-testid="dashboard-page">
      <AccountStrip account={account} positions={positions} streamConnected={streamConnected} scanner={scanner} />

      <div className="flex-1 p-2 min-h-0">
        <ResizablePanelGroup direction="horizontal" autoSaveId="dashboard-main-columns">
          {/* Left column: scanner + 5/5 alerts */}
          <ResizablePanel defaultSize={22} minSize={15} className="flex flex-col gap-2 min-h-0 pr-2">
            <ReadyToTradePanel results={displayResults} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
            <div className="flex-1 min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A]">
              <ScannerTable results={displayResults} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Center: 4-chart grid for the selected symbol */}
          <ResizablePanel defaultSize={58} minSize={30} className="min-h-0 flex flex-col px-2">
            {selectedSymbol && (
              <div className="flex items-center justify-between mb-1 px-1 shrink-0">
                <div className="text-sm font-bold text-neutral-200" data-testid="selected-symbol-header">
                  {selectedSymbol}
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
              <ChartGrid symbol={selectedSymbol} liveTrade={selectedSymbol ? trades[selectedSymbol] : null} />
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Right column: news feed for the selected symbol */}
          <ResizablePanel defaultSize={20} minSize={12} className="min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A] p-2 pl-3">
            <NewsFeedPanel symbol={selectedSymbol} />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
