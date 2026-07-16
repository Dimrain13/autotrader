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
        ))}
      </div>
    </div>
  );
}
