import { useState } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { NewsFlame, ChangeCell, CriteriaDots } from "./ScannerCells";

// Column definitions: `key` is the field to sort by, `defaultDir` is which
// direction that column sorts on first click (biggest/most-extreme first
// for numeric metrics, alphabetical for the symbol column).
const COLUMNS = [
  { key: "symbol", label: "Sym", align: "left", defaultDir: "asc" },
  { key: "current_price", label: "Price", align: "right", defaultDir: "desc" },
  { key: "pct_change", label: "Chg%", align: "right", defaultDir: "desc" },
  { key: "volume_ratio", label: "RVol", align: "right", defaultDir: "desc" },
  { key: "shares_outstanding", label: "Float", align: "right", defaultDir: "asc" },
  { key: "criteria_count", label: "5/5", align: "center", defaultDir: "desc" },
];

const ALIGN_CLASS = { left: "text-left", right: "text-right", center: "text-center" };

// Dense, color-graded scanner results table for manual review - click a row
// to load it into the chart grid. Rows are tinted by % change intensity so
// the strongest movers visually pop without needing a separate "hot" column.
// Click any column header to sort by that metric (click again to flip
// direction); with no column selected, falls back to the default
// criteria-count-then-volume ranking the backend scan already provides.
export function ScannerTable({ results, selectedSymbol, onSelect }) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("desc");

  const handleHeaderClick = (col) => {
    if (sortKey === col.key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(col.key);
      setSortDir(col.defaultDir);
    }
  };

  const sorted = [...(results || [])].sort((a, b) => {
    if (!sortKey) {
      return (b.criteria_count || 0) - (a.criteria_count || 0) || b.pct_change - a.pct_change;
    }
    const dir = sortDir === "asc" ? 1 : -1;
    if (sortKey === "symbol") return a.symbol.localeCompare(b.symbol) * dir;
    return ((a[sortKey] || 0) - (b[sortKey] || 0)) * dir;
  });

  return (
    <div className="overflow-y-auto h-full" data-testid="scanner-table">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[#111111] text-neutral-500 z-10">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col)}
                data-testid={`scanner-header-${col.key}`}
                className={`px-2 py-1.5 font-normal cursor-pointer select-none hover:text-neutral-200 transition-colors ${ALIGN_CLASS[col.align]}`}
              >
                <span className={`inline-flex items-center gap-0.5 ${col.align === "right" ? "flex-row-reverse" : ""}`}>
                  {col.label}
                  {sortKey === col.key ? (
                    sortDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />
                  ) : (
                    <ChevronsUpDown size={11} className="opacity-30" />
                  )}
                </span>
              </th>
            ))}
            <th className="text-center px-2 py-1.5 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => (
            <tr
              key={s.symbol}
              onClick={() => onSelect(s.symbol)}
              data-testid={`scanner-row-${s.symbol}`}
              className={`cursor-pointer border-b border-neutral-900 hover:bg-neutral-800/60 transition-colors ${
                s._stale ? "opacity-50" : ""
              } ${
                selectedSymbol === s.symbol ? "bg-[#00E599]/10" : s.pct_change >= 20 ? "bg-[#00E599]/5" : ""
              }`}
            >
              <td className="px-2 py-1.5 font-semibold text-neutral-100 flex items-center gap-1">
                {s.symbol}
                <NewsFlame freshness={s.news_freshness} hasNews={s.has_positive_news} />
                {s._stale && (
                  <span className="text-[8px] text-neutral-500 font-normal uppercase tracking-wider" data-testid={`stale-badge-${s.symbol}`}>
                    stale
                  </span>
                )}
              </td>
              <td className="text-right px-2 py-1.5 font-mono tabular-nums text-neutral-300">${s.current_price?.toFixed(2)}</td>
              <td className="text-right px-2 py-1.5"><ChangeCell pct={s.pct_change} /></td>
              <td className="text-right px-2 py-1.5 font-mono tabular-nums text-neutral-400">{s.volume_ratio?.toFixed(1)}x</td>
              <td className="text-right px-2 py-1.5 font-mono tabular-nums text-neutral-400">
                {s.shares_outstanding ? `${(s.shares_outstanding / 1_000_000).toFixed(1)}M` : "-"}
              </td>
              <td className="px-2 py-1.5"><div className="flex justify-center"><CriteriaDots count={s.criteria_count || 0} /></div></td>
              <td className="px-2 py-1.5 text-center">
                {s.ready_to_trade && <span className="text-[9px] font-bold text-[#00E599]" data-testid={`ready-badge-${s.symbol}`}>READY</span>}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr><td colSpan={7} className="text-center text-neutral-600 py-8">No candidates yet - scanning...</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
