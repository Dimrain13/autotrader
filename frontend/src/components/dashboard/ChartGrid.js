import { MiniChartTile } from "./MiniChartTile";

const TIMEFRAMES = ["10Sec", "1Min", "5Min", "1Day"];

// 2x2 grid of synced-symbol chart tiles at different timeframes, inspired
// by (not copied from) multi-timeframe scanner terminals - only populates
// once a symbol is manually selected from the scanner table below.
export function ChartGrid({ symbol, liveTrade }) {
  return (
    <div className="grid grid-cols-2 grid-rows-2 gap-2 h-full" data-testid="chart-grid">
      {TIMEFRAMES.map((tf) => (
        <MiniChartTile key={tf} symbol={symbol} timeframe={tf} liveTrade={liveTrade} />
      ))}
    </div>
  );
}
