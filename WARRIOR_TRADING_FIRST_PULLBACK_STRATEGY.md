# The "First Pullback" Strategy — Ross Cameron / Warrior Trading

This document is the authoritative, implementation-accurate breakdown of
the momentum entry pattern this bot actually trades: **buying the first
pullback after a high-volume, news-driven surge.** It is derived directly
from Ross Cameron's own teaching (see the full lesson transcript at the
bottom of this file) and maps every rule to the exact code that enforces
it in `/app/backend/services/auto_trader_service.py`.

> Trading is risky. Ross Cameron's own results are not typical. This bot
> only ever trades a **paper account** unless `ALPACA_PAPER=false` is
> explicitly set. Always test extensively in simulation before risking
> real capital.

---

## 1. The Core Idea

> "I let the stock squeeze up as much as it wants to. If it goes up 100%
> without me, it doesn't matter. But once it gives me that first pullback
> and it proves it can hold, that's when I pull the trigger." — Ross Cameron

Chasing a stock mid-surge is a lottery ticket — you don't know if you're
buying the very top. Instead, wait for the stock to **prove itself**: let
it pull back, see if it holds, and only buy the moment the trend
resumes (a new high breaking the pullback's high).

![The First Pullback Pattern](https://static.prod-images.emergentagent.com/jobs/7da4d582-bcba-40ea-92a1-b6fd98458b9e/images/382ef1fb225e06457e3920cdb8c559aaf9c37466b733db54991383e69cf8b6b3.png)

*The initial surge is driven by a real news catalyst + abnormal volume
(this bot's 5-pillar scanner already screens for this before any of the
logic below ever runs — see `scanner_service.py`). The pullback is 1-3 RED
candles of profit-taking. Entry fires the instant a candle breaks back
above the high of the candle right before it.*

---

## 2. Setup Identification (Scanner Phase — already implemented)

Before this pattern is even checked, a stock must already meet **all 5**
of Ross Cameron's stock-selection pillars (`scanner_service.py`):

| Pillar | Rule |
|---|---|
| Price | $2 – $20 per share |
| Float | Under 20 million shares (real SEC EDGAR data, never randomized) |
| Relative Volume | Abnormally high vs. the stock's own average |
| % Change | Meaningful gainer on the day |
| News Catalyst | Real, fresh news (Alpaca/Benzinga news API, Google News fallback) |

Only stocks hitting **5/5** are ever passed into the entry logic below.

---

## 3. The Pullback & The 50% Rule

> "What I look at is that it should be holding at least 50% of the
> initial move. ... If we drop down further than that, that's displayed
> weakness — that's not a setup I would trade."

The pullback (1-3 red candles) must hold **at least 50%** of the initial
surge. If price retraces past the surge's midpoint, the setup shows too
much weakness and is discarded entirely — no entry, no exception.

![The 50% Rule](https://static.prod-images.emergentagent.com/jobs/7da4d582-bcba-40ea-92a1-b6fd98458b9e/images/b4017e89ed0aacec41ade64413e5596cdde60b43028ce7a4332d94639c6e191b.png)

**Code**: `AutoTraderService.check_first_pullback()`
```python
surge_size = surge_peak - surge_start_low
retracement_pct = (surge_peak - pullback_low) / surge_size * 100
if retracement_pct > self.pullback_retracement_max_pct * 100:  # default 50%
    # setup discarded - "too weak"
```

---

## 4. Entry Trigger & Structural Stop-Loss

> "My entry is the first candle to make a new high after at least one red
> candle... My max loss is always the low of the pullback."

- **Entry**: the first candle whose high breaks above the high of the
  immediately preceding red pullback candle.
- **Stop-loss**: NOT an arbitrary percentage — it is the **actual low of
  the pullback candles**. This is a structural stop, exactly as Ross
  Cameron places it.
- **Safety cap**: if that structural stop turns out to be more than
  `max_stop_distance_pct` (default 3%) away from entry, the trade is
  skipped entirely — the setup is too volatile/low-conviction to size
  properly.

![Entry and Stop Loss](https://static.prod-images.emergentagent.com/jobs/7da4d582-bcba-40ea-92a1-b6fd98458b9e/images/37c3e598121e4b93ce0e95a149c4d76ee57777be0972c054a33842a84c504e9a.png)

**Code**: `check_first_pullback()` returns `stop_loss_price` = the real
pullback low; `check_entry_signals()` rejects the trade if
`risk_per_share / entry_price > max_stop_distance_pct`.

---

## 5. MACD Confirmation

> "I check the MACD, and the MACD has gone negative... does this stock
> work on this pullback as an entry? The answer is no. The MACD needs to
> be positive."

MACD(12, 26, 9) must be **bullish** (MACD line above the signal line)
at the moment of entry — checked as ongoing trend state by default, not
as a same-candle crossover event (see the 2026-02 correction note below).

![MACD Crossover](https://static.prod-images.emergentagent.com/jobs/7da4d582-bcba-40ea-92a1-b6fd98458b9e/images/98777956bc704703147f2d32328e452286a7fa1b5a8cc93cccbdd486be5fab91.png)

**Code**: `calculate_macd()` + `require_macd_crossover` gate in
`check_entry_signals()`. Also checked in this bot (extra confirmation
beyond Ross Cameron's base rules): SMA20/50 bullish state + green
volume bars after a red bar.

> **2026-02 correction**: `require_macd_crossover`/`require_sma_crossover`
> previously defaulted to `True`, requiring MACD to cross its signal line
> AND SMA20 to cross SMA50 on the EXACT SAME 5-min candle as the pullback
> breakout. Backtested against 10 real trading days of TSLA/NVDA/AMD
> 5-min bars: this produced **zero** valid entry signals for any of the
> three stocks — three independent low-probability events essentially
> never coincide on one candle. Both now default to `False` (state-based:
> MACD above signal, SMA20 above SMA50 — trend context, as Ross Cameron
> actually uses them) which produced 6-13 real signals per stock over the
> same 10-day window. Still toggleable to strict crossover-only via
> Settings/Trading page.

---

## 6. Risk Management: The 2:1 Ratio

> "I focus on using a 2:1 profit-to-loss ratio... If I trade with a 2:1
> profit-loss ratio, how often do I have to be right in order to break
> even? I only need to be right 33% of the time."

The profit target is now computed as a **true** 2:1 off the real
structural risk (not a flat %):

```
risk_per_share = entry_price - stop_loss_price   # real distance to the pullback low
target_price   = entry_price + (2 * risk_per_share)
```

At the target: sell 50% of the position and move the stop to break-even
on the rest (locks in a guaranteed win while letting a runner continue).

---

## 7. "Breakout or Bailout" — The Time-Stop

> "If the move doesn't resolve instantly in my favor, I just get out. I
> don't even wait for it to come all the way back down to my max loss. ...
> True momentum resolves instantly."

If, `breakout_bailout_seconds` (default **90s**) after entry, the
position is still **not in profit** (price ≤ entry), the bot exits
immediately at market — rather than waiting for the full structural stop
to be hit. This is Ross Cameron's discipline of cutting a "dud" breakout
fast instead of hoping.

**Code**: `monitor_exits()` — `bailout_triggered` check, evaluated on
every 60-second auto-trader loop tick.

---

## 8. Full Decision Tree (as implemented)

```
Scanner: 5/5 pillars met?
  └─ NO  → skip
  └─ YES → check_first_pullback(bars)
             ├─ 1-3 red candles found after the surge? NO → skip
             ├─ Breakout bar breaks the prior red candle's high? NO → skip
             ├─ 50% Rule: pullback holds ≥ 50% of the surge? NO → skip ("too weak")
             └─ YES → stop_loss = pullback low
                       risk = entry - stop_loss
                       risk_pct = risk / entry
                       ├─ risk_pct > max_stop_distance_pct (3%)? YES → skip ("too risky")
                       └─ NO → target = entry + 2×risk
                                ├─ MACD bullish (above signal)? NO → skip
                                ├─ SMA20/50 bullish (20 above 50)? NO → skip
                                ├─ Volume confirmation (green after red)? NO → skip
                                └─ ALL YES → BUY

Position management (every 60s):
  ├─ price ≤ stop_loss (structural/trailing)? → EXIT (cut loss fast)
  ├─ not profitable AND time_since_entry ≥ 90s? → EXIT ("Breakout or Bailout")
  ├─ price ≥ target (2:1)? → SELL 50%, move stop to break-even
  └─ 3:30 PM ET? → EXIT everything (end of window)
```

---

## 9. Configuration Reference

Located in `/app/backend/services/auto_trader_service.py`
(adjustable via `POST /api/auto-trader/settings`):

| Parameter | Default | Meaning |
|---|---|---|
| `pullback_min_candles` / `pullback_max_candles` | 1 / 3 | Valid red-candle pullback range |
| `pullback_lookback_bars` | 10 | Bars scanned for the pattern |
| `pullback_retracement_max_pct` | 50% | The 50% Rule ceiling |
| `max_stop_distance_pct` | 3% | Safety cap — skip if structural stop is farther than this |
| `breakout_bailout_seconds` | 90s | Time-stop if trade never turns profitable |
| `require_macd_crossover` | False (2026-02) | If True, requires an exact MACD/signal crossover on the same candle as the breakout (near-impossible in practice, see §5) instead of state-based bullish |
| `require_sma_crossover` | False (2026-02) | If True, requires an exact SMA20/SMA50 crossover on the same candle as the breakout, instead of state-based (SMA20 > SMA50) |
| `position_size_pct` | 10% | Capital per trade (max 5 concurrent = 50% exposure) |
| `daily_max_loss_pct` | 1% | Hard kill switch — blocks all new BUYs for the day |
| `max_consecutive_losses` | 3 | "Three strikes" — done for the day |
| Trading window | 7:00 AM – 3:30 PM ET | Entries + management; all positions closed at 3:30 PM |

---

## 10. Disclaimer

Day trading is high-risk. Ross Cameron's own results are explicitly not
typical, and neither are anyone else's. This breakdown and its
implementation are for educational and algorithmic-analysis purposes.
This bot is currently configured for **PAPER trading only**. Always
validate extensively in simulation, understand every rule above, and
only ever risk capital you can afford to lose before ever flipping
`ALPACA_PAPER=false`.

---

## Appendix: Full Source Lesson (Ross Cameron, Warrior Trading)

<details>
<summary>Click to expand the full class transcript this strategy is based on</summary>

Ross Cameron: Welcome to today's class. In this session, I'm going to teach you my number one favorite candlestick chart pattern. This is the setup that I use whenever I'm doing a Small Account Challenge.

The reason is, when I'm trading on a small account, I've got zero margin for error. I cannot afford to make mistakes. And so naturally, I want to focus on trading the setup that I've got the highest degree of conviction in — the setup that will give me the highest level of accuracy. It's not about hitting big winners; it's about being consistent.

I approach trading with the same mentality as if this is my livelihood. This is for income. I need to make this money to pay my bills this week. I can't afford to take a gamble on this month's rent or this month's mortgage payment. I need consistency, even if it is a little boring.

So the setup that I'm going to share with you, for me, has been incredibly consistent. And it doesn't matter if you're trading it on Forex, Futures, Cryptocurrency, or you're trading it on stocks like I do. There's a psychology behind why this pattern works that is universal.

So while my confidence has given me the ability to trade these with larger and larger share sizes, you could be trading this with a $200 account or a $2,000 account just the same because the pattern is universal.

Okay, so let's talk about this setup. This is my bread and butter. What I'm looking at is a stock that has started to move up very quickly, but there's something special: the stock is moving up because it has a catalyst. It has breaking news. And that's what's bringing in all the volume.

So as it's squeezing up faster and faster and faster, I have to make a decision. Do I jump in somewhere in the middle of this move right here? Well, see now, that's a little bit like buying a lottery ticket. So I wouldn't be managing my risk well if I took that trade.

I need to wait for a pullback. So I let the stock squeeze up as much as it wants to. If it goes up 100% without me, it doesn't matter. But once it gives me that first pullback and it proves it can hold, that's when I pull the trigger.

Emotion — our gut intuition — tells us to do the exact opposite in the market than what will produce profit. As an example, imagine getting your thumb caught on a fishhook. Your instinct is to pull it out. But when you pull it, the barb just goes deeper. In fact, doing the opposite is how you release it. It's not intuitive. Being a successful trader requires non-intuitive decisions.

So this is the first pullback right there, and this is an animation of what it looks like. So initially, the stock has breaking news. Boom, we've got a breaking news catalyst and it starts squeezing up. So the stock starts squeezing up and it moves higher and higher. Now, I'm not buying right here or right here because I don't know — these could be the very top before it rolls over.

I let it form that first red candle. I let it pull back a little bit more. And then once it's based out right there, what am I looking for? I'm looking for the stock to change directions. And so the moment the first candle makes a new high right there, the trend has shifted. And so that becomes my entry indicator.

A rapid move up attracts traders. This is especially true when the move is driven by breaking news. And so I use scanners to search the market. This scanner is actively searching the entire market for stocks that meet my five pillars of stock selection.

So as this stock first hit the scanner at 7:00 AM right here, the stock only had 30,000 shares of volume, but it already had 343 times higher volume at 7:00 AM than it would have on a typical day. Next thing you know, it goes to 8:30, up to $10, up to $25 a share.

Now there's a couple of important considerations. One consideration is: what are traders currently focusing on? And is the market hot or cold?

So the initial move up attracts traders. Then the first pullback — this is formed by profit-taking. Now this is kind of the moment of truth: will the stock hold up or will it just go all the way back down?

What I look at is that it should be holding at least 50% of the initial move. So we have a stock here that pops up — one big green candle, maybe two. It then pulls back. So we want to see that the stock can hold at least the 50% retracement. If we drop down further than that, that's displayed weakness — that's not a setup that I would trade.

My entry is the first candle to make a new high after at least one red candle. Two to three red candles is okay, though. The moment that first candle makes a new high, the trend is shifting.

So what would be my max loss? My max loss is always the low of the pullback. And this is important. So I look at the distance between my entry and my max loss. Let's say that's 20 cents per share. What's my profit target? I focus on using a 2:1 profit-to-loss ratio, which means I stand to gain twice what I'm risking. So that means my profit target is always a retest of high of day.

If I trade with a 2:1 profit-loss ratio, how often do I have to be right in order to break even? I only need to be right 33% of the time to break even.

Now, if the move doesn't resolve instantly in my favor, I just get out. I don't even wait for it to come all the way back down to my max loss. I just recognize that when this setup works, it works instantly. And if it doesn't work, I'm just going to get right out of the trade.

In addition to making sure you're trading a stock that meets all five pillars of stock selection, you've also got to make sure you're checking the MACD. You see this stock — you see it's been rallying up, pullbacks, rallying higher. Right now we're on a pullback. We check the MACD, and the MACD has gone negative. The signal line was positive and it crossed over right there. So does this stock work on this pullback as an entry? The answer is no. It just sort of unwinds. The MACD needs to be positive.

I'll remind you again as always that trading is risky. My results are not typical. So please manage your risk, take it slow, and always practice in a simulator before putting real money on the line.

</details>
