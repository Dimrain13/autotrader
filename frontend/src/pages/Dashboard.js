import { useState } from "react";
import { AccountStrip } from "../components/dashboard/AccountStrip";
import { ScannerTable } from "../components/dashboard/ScannerTable";
import { ReadyToTradePanel } from "../components/dashboard/ReadyToTradePanel";
import { NewsFeedPanel } from "../components/dashboard/NewsFeedPanel";
import { ChartGrid } from "../components/dashboard/ChartGrid";
import { useMarketDataSocket } from "../hooks/useMarketDataSocket";

// One-screen manual-review trading dashboard: scanner + 5/5 alerts + a
// 4-timeframe chart grid + news, inspired by (not copying) multi-panel
// scanner terminals like StocksToTrade/Trade Ideas. Charts only populate
// once a symbol is manually selected below - no auto-focus.
export default function Dashboard({ account, positions, scanner }) {
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const { connected: streamConnected } = useMarketDataSocket();

  const results = scanner?.results || [];

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]" data-testid="dashboard-page">
      <AccountStrip account={account} positions={positions} streamConnected={streamConnected} scanner={scanner} />

      <div className="flex-1 grid grid-cols-12 gap-2 p-2 min-h-0">
        {/* Left column: scanner + 5/5 alerts */}
        <div className="col-span-3 flex flex-col gap-2 min-h-0">
          <ReadyToTradePanel results={results} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
          <div className="flex-1 min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A]">
            <ScannerTable results={results} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
          </div>
        </div>

        {/* Center: 4-chart grid for the selected symbol */}
        <div className="col-span-7 min-h-0">
          {selectedSymbol && (
            <div className="text-sm font-bold text-neutral-200 mb-1 px-1" data-testid="selected-symbol-header">
              {selectedSymbol}
            </div>
          )}
          <div className={selectedSymbol ? "h-[calc(100%-24px)]" : "h-full"}>
            <ChartGrid symbol={selectedSymbol} />
          </div>
        </div>

        {/* Right column: news feed for the selected symbol */}
        <div className="col-span-2 min-h-0 border border-neutral-800 rounded-lg bg-[#0A0A0A] p-2">
          <NewsFeedPanel symbol={selectedSymbol} />
        </div>
      </div>
    </div>
  );
}
