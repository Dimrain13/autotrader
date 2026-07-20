import { useEffect, useState } from "react";
import axios from "axios";
import { NewsFlame } from "./ScannerCells";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// Real news headlines for the currently selected symbol - Alpaca/Benzinga
// first, Google News fallback (same pipeline as the scanner's flame badges).
// Sorted by catalyst relevance (backend) - the SENTIMENT_BADGE below makes
// that ranking visible at a glance instead of just being an invisible sort.
const SENTIMENT_BADGE = {
  strong_catalyst: { label: "CATALYST", className: "text-[#FF9900] border-[#FF9900]/40 bg-[#FF9900]/10" },
  momentum: { label: "MOMENTUM", className: "text-[#2E5CFF] border-[#2E5CFF]/40 bg-[#2E5CFF]/10" },
  weak: { label: "MENTION", className: "text-neutral-400 border-neutral-600/40 bg-neutral-800/40" },
  // 'neutral' (score 0, no keyword match at all - routine/informational)
  // gets no badge at all, kept visually quiet vs the ranked tiers above.
};

// Cap how many symbols get auto-fetched at once (bounds API calls when a
// scan cycle suddenly has many 3/5+ candidates) - highest criteria/momentum
// candidates win.
const MAX_AUTO_SYMBOLS = 6;

function ArticleRow({ a, i, showSymbolTag }) {
  return (
    <a
      href={a.link}
      target="_blank"
      rel="noreferrer"
      data-testid={`news-article-${i}`}
      className="block p-2 rounded-md bg-neutral-900/60 hover:bg-neutral-800 transition-colors"
    >
      <div className="flex items-start gap-1.5">
        <NewsFlame temperature={a.temperature} hasNews={true} />
        {showSymbolTag && (
          <span className="text-[9px] font-bold text-neutral-300 bg-neutral-800 rounded px-1 py-0.5 shrink-0" data-testid={`news-symbol-tag-${a.symbol}`}>
            {a.symbol}
          </span>
        )}
        <span className="text-xs text-neutral-200 leading-snug flex-1">{a.title}</span>
        {SENTIMENT_BADGE[a.sentiment] && (
          <span
            className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 ${SENTIMENT_BADGE[a.sentiment].className}`}
            data-testid={`news-sentiment-${a.sentiment}`}
          >
            {SENTIMENT_BADGE[a.sentiment].label}
          </span>
        )}
      </div>
      <div className="text-[10px] text-neutral-600 mt-1">
        {a.source} {a.days_old !== undefined && a.days_old !== null ? `· ${a.days_old === 0 ? "today" : `${a.days_old}d ago`}` : ""}
      </div>
    </a>
  );
}

// News panel: shows the manually-selected symbol's news when one is
// clicked in the scanner/chart. When nothing is manually selected, it
// AUTO-LOADS and merges news for every scanner candidate currently hitting
// >= 3/5 criteria instead of sitting empty waiting for a click - momentum
// building on a stock is exactly when a trader wants to already see why
// (found 2026-07, user report: "news only loads when explicitly clicked;
// it should auto-load for any stock hitting 3/5 metrics").
export function NewsFeedPanel({ symbol, scannerResults }) {
  const [state, setState] = useState({ loading: false, articles: [], source: null, mode: "empty" });

  const autoSymbols = (scannerResults || [])
    .filter((r) => (r.criteria_count || 0) >= 3)
    .sort((a, b) => (b.criteria_count || 0) - (a.criteria_count || 0) || (b.pct_change || 0) - (a.pct_change || 0))
    .slice(0, MAX_AUTO_SYMBOLS)
    .map((r) => r.symbol);
  const autoSymbolsKey = autoSymbols.join(",");

  useEffect(() => {
    let cancelled = false;

    if (symbol) {
      setState((s) => ({ ...s, loading: true, mode: "manual" }));
      axios.get(`${API}/news/${symbol}?limit=8`).then((res) => {
        if (cancelled) return;
        setState({ loading: false, articles: res.data.articles || [], source: res.data.news_source, mode: "manual" });
      }).catch(() => {
        if (!cancelled) setState({ loading: false, articles: [], source: null, mode: "manual" });
      });
      return () => { cancelled = true; };
    }

    if (autoSymbols.length === 0) {
      setState({ loading: false, articles: [], source: null, mode: "empty" });
      return;
    }

    setState((s) => ({ ...s, loading: true, mode: "auto" }));
    Promise.all(
      autoSymbols.map((sym) =>
        axios.get(`${API}/news/${sym}?limit=3`)
          .then((res) => (res.data.articles || []).map((a) => ({ ...a, symbol: sym })))
          .catch(() => [])
      )
    ).then((results) => {
      if (cancelled) return;
      const merged = results.flat().sort((a, b) => (b.score || 0) - (a.score || 0));
      setState({ loading: false, articles: merged, source: null, mode: "auto" });
    });
    return () => { cancelled = true; };
  }, [symbol, autoSymbolsKey]);

  const isAuto = state.mode === "auto";

  return (
    <div className="h-full overflow-y-auto" data-testid="news-feed-panel">
      <div className="text-[10px] uppercase tracking-wider text-neutral-500 font-semibold mb-2 px-1 flex items-center justify-between">
        <span>
          News {symbol ? `- ${symbol}` : isAuto ? `- ${autoSymbols.length} stock${autoSymbols.length === 1 ? "" : "s"} @ 3/5+` : ""}
        </span>
        {state.source && <span className="text-neutral-600 font-normal">{state.source}</span>}
      </div>
      {!symbol && !state.loading && autoSymbols.length === 0 && (
        <div className="text-xs text-neutral-600 px-1" data-testid="news-feed-empty">Select a symbol, or wait for a stock to hit 3/5 criteria, to see news</div>
      )}
      {state.loading && <div className="text-xs text-neutral-600 px-1" data-testid="news-feed-loading">Loading...</div>}
      {!state.loading && (symbol || autoSymbols.length > 0) && state.articles.length === 0 && (
        <div className="text-xs text-neutral-600 px-1">No recent news found</div>
      )}
      <div className="space-y-2 px-1">
        {state.articles.map((a, i) => (
          <ArticleRow key={i} a={a} i={i} showSymbolTag={isAuto} />
        ))}
      </div>
    </div>
  );
}
