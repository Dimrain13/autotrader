import { Flame, AlertTriangle } from "lucide-react";

// Flame color = catalyst STRENGTH ("temperature"), never article age.
// hot = red (real catalyst: merger/FDA/earnings), medium = orange (price
// action/momentum: surge/rally/breakout - not a fundamental catalyst),
// cold = yellow (generic weak mention). No article = no flame.
// Previously this was keyed off article AGE (breaking/warm/cold) instead,
// so a freshly-published "stock surges" headline lit up the exact same
// bright red flame as a real merger/FDA article just for being recent -
// user report: "Hot/Cold ranking flags generic price increases as Hot
// instead of reserving that for true catalysts". Age is still shown as
// plain text elsewhere (e.g. "2d ago"), just no longer drives this color.
const TEMPERATURE_STYLE = {
  hot: "text-[#FF1A40]",
  medium: "text-[#FF8A2E]",
  cold: "text-[#F5D547]",
};

export function NewsFlame({ temperature, hasNews }) {
  if (!hasNews || !TEMPERATURE_STYLE[temperature]) return null;
  return (
    <Flame
      className={`w-3.5 h-3.5 ${TEMPERATURE_STYLE[temperature]} inline-block`}
      fill="currentColor"
      data-testid={`news-flame-${temperature}`}
    />
  );
}

export function ChangeCell({ pct }) {
  const positive = pct >= 0;
  return (
    <span className={`font-mono tabular-nums ${positive ? "text-[#00E599]" : "text-[#FF1A40]"}`}>
      {positive ? "+" : ""}{pct?.toFixed(1)}%
    </span>
  );
}

export function CriteriaDots({ count }) {
  return (
    <div className="flex gap-0.5" data-testid="criteria-dots">
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i < count ? "bg-[#00E599]" : "bg-neutral-700"}`}
        />
      ))}
    </div>
  );
}

// T12 Halt Risk warning: a stock hitting every OTHER pillar (price/change/
// volume/float, all verified-real) with ZERO underlying news catalyst -
// pure retail-momentum/short-squeeze action. These setups are highly prone
// to a sudden exchange-mandated T12 (halted pending investigation) circuit
// breaker. Shown ONLY for confirmed 4/4-non-news candidates (scanner's
// `no_news_scalp_candidate`), never for stocks that simply lack news
// entirely (which is most stocks, not a warning-worthy state).
export function T12HaltBadge() {
  return (
    <span
      className="text-[8px] font-bold uppercase tracking-wider text-[#FF1A40] border border-[#FF1A40]/50 bg-[#FF1A40]/10 rounded px-1 py-0.5 inline-flex items-center gap-0.5 shrink-0"
      title="High T12 Halt Risk: No Catalyst Detected. Do not hold into a circuit-breaker pause."
      data-testid="t12-halt-badge"
    >
      <AlertTriangle className="w-2.5 h-2.5" />
      NO CATALYST
    </span>
  );
}
