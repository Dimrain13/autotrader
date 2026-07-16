import { MiniChartTile } from "./MiniChartTile";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "../ui/resizable";

const TIMEFRAMES = ["10Sec", "1Min", "5Min", "1Day"];

// 2x2 grid of synced-symbol chart tiles at different timeframes, inspired
// by (not copied from) multi-timeframe scanner terminals - only populates
// once a symbol is manually selected from the scanner table below. Every
// row/column boundary is user-draggable and the sizes persist across
// reloads (autoSaveId), since not everyone runs the same screen size.
export function ChartGrid({ symbol, liveTrade, levels }) {
  return (
    <ResizablePanelGroup direction="vertical" autoSaveId="dashboard-chart-grid-rows" id="chart-grid-rows-group" className="h-full" data-testid="chart-grid">
      <ResizablePanel id="chart-grid-row1" order={1} defaultSize={50} minSize={20}>
        <ResizablePanelGroup direction="horizontal" autoSaveId="dashboard-chart-grid-row1-cols" id="chart-grid-row1-cols-group">
          <ResizablePanel id="chart-grid-row1-col1" order={1} defaultSize={50} minSize={20}>
            <MiniChartTile symbol={symbol} timeframe={TIMEFRAMES[0]} liveTrade={liveTrade} levels={levels} />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel id="chart-grid-row1-col2" order={2} defaultSize={50} minSize={20}>
            <MiniChartTile symbol={symbol} timeframe={TIMEFRAMES[1]} liveTrade={liveTrade} levels={levels} />
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel id="chart-grid-row2" order={2} defaultSize={50} minSize={20}>
        <ResizablePanelGroup direction="horizontal" autoSaveId="dashboard-chart-grid-row2-cols" id="chart-grid-row2-cols-group">
          <ResizablePanel id="chart-grid-row2-col1" order={1} defaultSize={50} minSize={20}>
            <MiniChartTile symbol={symbol} timeframe={TIMEFRAMES[2]} liveTrade={liveTrade} levels={levels} />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel id="chart-grid-row2-col2" order={2} defaultSize={50} minSize={20}>
            <MiniChartTile symbol={symbol} timeframe={TIMEFRAMES[3]} liveTrade={liveTrade} levels={levels} />
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

