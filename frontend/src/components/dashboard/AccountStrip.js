// Compact top strip - key account vitals at a glance, doesn't dominate the
// one-screen manual-review layout below it.
export function AccountStrip({ account, positions, streamConnected, scanner }) {
  const totalUnrealizedPl = (positions || []).reduce((sum, p) => sum + (p.unrealized_pl || 0), 0);
  const plPositive = totalUnrealizedPl >= 0;

  const stat = (label, value, valueClass = "text-neutral-100", testId) => (
    <div className="flex flex-col" data-testid={testId}>
      <span className="text-[10px] text-neutral-500 uppercase tracking-wider">{label}</span>
      <span className={`font-mono text-sm font-semibold ${valueClass}`}>{value}</span>
    </div>
  );

  return (
    <div className="flex items-center gap-6 px-4 py-2 bg-[#111111] border-b border-neutral-800" data-testid="account-strip">
      {stat("Portfolio", `$${account?.portfolio_value?.toFixed(2) || "0.00"}`, "text-neutral-100", "strip-portfolio-value")}
      {stat("Buying Power", `$${account?.max_buying_power?.toFixed(2) || "0.00"}`, "text-neutral-100", "strip-buying-power")}
      {stat(
        "Open P&L",
        `${plPositive ? "+" : ""}$${totalUnrealizedPl.toFixed(2)}`,
        plPositive ? "text-[#00E599]" : "text-[#FF1A40]",
        "strip-open-pl"
      )}
      {stat("Positions", positions?.length || 0, "text-neutral-100", "strip-positions-count")}
      <div className="flex-1" />
      <button
        onClick={() => scanner.setAutoScan(!scanner.autoScan)}
        data-testid="dashboard-scan-toggle"
        className={`px-3 py-1 rounded-md text-xs font-semibold border transition-colors ${
          scanner.autoScan
            ? "bg-[#00E599]/15 text-[#00E599] border-[#00E599]/40"
            : "bg-neutral-800 text-neutral-400 border-neutral-700 hover:border-neutral-500"
        }`}
      >
        {scanner.scanning ? "Scanning..." : scanner.autoScan ? `Scanning (next in ${scanner.nextScanCountdown}s)` : "Start Scanning"}
      </button>
      <div className="flex items-center gap-1.5 text-[10px] text-neutral-500" data-testid="dashboard-stream-indicator">
        <span className={`w-1.5 h-1.5 rounded-full ${streamConnected ? "bg-[#00E599] animate-pulse" : "bg-neutral-600"}`} />
        {streamConnected ? "Live stream connected" : "Reconnecting..."}
      </div>
    </div>
  );
}
