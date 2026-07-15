/**
 * In-memory local cache for candlestick bar data, keyed by `${symbol}_${timeframe}`.
 *
 * Lets a chart tile instantly repaint from the last-known bars when the
 * user re-selects a symbol/timeframe combo already loaded this session
 * (no blank "Loading..." flash), and gives periodic refreshes a starting
 * point so they only need to ask the backend for what's NEW since the
 * last cached bar instead of re-pulling the full historical window.
 */
const cache = new Map();

export const barsCache = {
  get: (symbol, timeframe) => cache.get(`${symbol}_${timeframe}`) || null,

  set: (symbol, timeframe, bars) => {
    cache.set(`${symbol}_${timeframe}`, { bars, updatedAt: Date.now() });
  },

  clear: (symbol, timeframe) => {
    cache.delete(`${symbol}_${timeframe}`);
  },

  /**
   * Merge freshly-fetched bars into an existing cached array, replacing any
   * overlapping timestamps (e.g. an in-progress bar) and keeping only the
   * most recent `limit` bars, sorted ascending by time.
   */
  merge: (existingBars, newBars, limit = 100) => {
    if (!newBars || newBars.length === 0) return existingBars;
    const byTimestamp = new Map();
    (existingBars || []).forEach((b) => byTimestamp.set(b.timestamp, b));
    newBars.forEach((b) => byTimestamp.set(b.timestamp, b));
    const merged = Array.from(byTimestamp.values()).sort(
      (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
    );
    return merged.slice(-limit);
  },
};
