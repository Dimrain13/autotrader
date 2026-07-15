import { useEffect, useState } from "react";
import axios from "axios";
import { NewsFlame } from "./ScannerCells";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

// Real news headlines for the currently selected symbol - Alpaca/Benzinga
// first, Google News fallback (same pipeline as the scanner's flame badges).
export function NewsFeedPanel({ symbol }) {
  const [state, setState] = useState({ loading: false, articles: [], source: null });

  useEffect(() => {
    if (!symbol) {
      setState({ loading: false, articles: [], source: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    axios.get(`${API}/news/${symbol}?limit=8`).then((res) => {
      if (cancelled) return;
      setState({ loading: false, articles: res.data.articles || [], source: res.data.news_source });
    }).catch(() => {
      if (!cancelled) setState({ loading: false, articles: [], source: null });
    });
    return () => { cancelled = true; };
  }, [symbol]);

  return (
    <div className="h-full overflow-y-auto" data-testid="news-feed-panel">
      <div className="text-[10px] uppercase tracking-wider text-neutral-500 font-semibold mb-2 px-1 flex items-center justify-between">
        <span>News {symbol ? `- ${symbol}` : ""}</span>
        {state.source && <span className="text-neutral-600 font-normal">{state.source}</span>}
      </div>
      {!symbol && <div className="text-xs text-neutral-600 px-1">Select a symbol to see news</div>}
      {symbol && state.loading && <div className="text-xs text-neutral-600 px-1">Loading...</div>}
      {symbol && !state.loading && state.articles.length === 0 && (
        <div className="text-xs text-neutral-600 px-1">No recent news found</div>
      )}
      <div className="space-y-2 px-1">
        {state.articles.map((a, i) => (
          <a
            key={i}
            href={a.link}
            target="_blank"
            rel="noreferrer"
            data-testid={`news-article-${i}`}
            className="block p-2 rounded-md bg-neutral-900/60 hover:bg-neutral-800 transition-colors"
          >
            <div className="flex items-start gap-1.5">
              <NewsFlame freshness={a.freshness} hasNews={true} />
              <span className="text-xs text-neutral-200 leading-snug">{a.title}</span>
            </div>
            <div className="text-[10px] text-neutral-600 mt-1">
              {a.source} {a.days_old !== undefined && a.days_old !== null ? `· ${a.days_old === 0 ? "today" : `${a.days_old}d ago`}` : ""}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
