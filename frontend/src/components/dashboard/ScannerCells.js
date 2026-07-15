import { Flame } from "lucide-react";

// breaking = red flame, warm = orange flame, cold = yellow flame, no article = none
const FRESHNESS_STYLE = {
  breaking: "text-[#FF1A40]",
  warm: "text-[#FF8A2E]",
  cold: "text-[#F5D547]",
};

export function NewsFlame({ freshness, hasNews }) {
  if (!hasNews || !FRESHNESS_STYLE[freshness]) return null;
  return (
    <Flame
      className={`w-3.5 h-3.5 ${FRESHNESS_STYLE[freshness]} inline-block`}
      fill="currentColor"
      data-testid={`news-flame-${freshness}`}
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
