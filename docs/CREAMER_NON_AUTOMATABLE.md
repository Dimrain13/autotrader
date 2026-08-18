# Creamer Strategy — Non-Automatable Rules (Futures/Options Only)

These are rules from Chris Creamer's World Cup strategy and Order Flow series
that require data or platforms not available via Alpaca equities API. They are
documented here for future implementation when we add futures or options trading.

---

## 1. Order Flow / Footprint Chart Rules

These require a footprint chart platform (ATAS, Sierra Chart, etc.) showing
Bid×Ask volume at each price level within a candle.

| Rule | Source | Description |
|---|---|---|
| Delta analysis | Order Flow Series #6 | Delta = aggressive buys - aggressive sells. Effort vs result: positive delta with no price extension = absorption. |
| Imbalance ratio 400% | ATAS Settings video | Highlight cells where aggressive volume on one side is 4x the other side. Minimum 10 contracts. |
| Stacked imbalances | ATAS Settings video | Consecutive price levels with 400% imbalance drawn as support/resistance boxes. Active until touched. |
| Big trade retest | Win Streak video | Minimum 300 contracts on MNQ. Wait for price to retest the big trade level, watch for absorption, enter on re-engagement. |
| Absorption mechanics | Absorption video | Seller failure at candle lows = negative delta + no further downside. Buyer re-engagement on next candle = entry. |
| Two-candle entry trigger | Win Streak video | First candle = aggression/absorption confirmation. Second candle = execution (enter on pullback retest). |

---

## 2. Gamma Exposure (GEX) Rules

These require options chain data (CBOE or equivalent) to calculate gamma exposure.

| Rule | Source | Description |
|---|---|---|
| Naive GEX regime | World Cup video | Positive gamma = volatility dampening (dealers sell rips/buy dips). Negative gamma = volatility amplifier (dealers buy rips/sell dips). |
| Gamma flip zone | World Cup video | The price level where gamma flips from positive to negative. Acts as a "line in the sand" for volatility regime shift. |
| Call wall / Put wall | World Cup video | Largest gamma strikes. Price tends to be drawn toward the largest gamma level (pin risk). |
| Ideal combo | World Cup video | Value-up structure + negative gamma = amplified trending moves with trend direction. |

---

## 3. Volume Profile Rules

These require volume profile data at specific price levels (not just bar volume).

| Rule | Source | Description |
|---|---|---|
| POC (Point of Control) | World Cup video | Price level with most volume. First profit target. |
| Value Area High/Low | Premium & Discount video | 70% of volume around POC. Premium above VA high, discount below VA low. |
| Low Volume Nodes | Volume Profile video | Price gaps through low-volume areas quickly. Reversals often happen at LVN extremes. |
| Composite profile | Volume Profile video | Multi-day volume profile showing where institutions accumulated positions. |

---

## 4. Prop Firm Specific Rules

| Rule | Source | Description |
|---|---|---|
| Eval sizing (aggressive) | Stacked Imbalances video | 4 E-minis per trade, $1,000 max risk, $5,000 daily loss limit on $250K Topstep. |
| Live sizing (conservative) | Stacked Imbalances video | 1-2 Micros, $100 risk per trade, add to winners only. |
| 1.5R prop firm math | World Cup video | $2,000 drawdown vs $3,000 profit target = 1.5R. Take 1.5R trades, pass evals. |

---

## 5. Session-Specific Rules (Futures)

| Rule | Source | Description |
|---|---|---|
| Asia builds range | 4 Layers video | Asia session establishes the daily balance/range. |
| London hunts + moves | 4 Layers video | London probes/manipulates the Asia range, then expands away. |
| NY trend | 4 Layers video | NY session often trends in direction of the London expansion. |
| Tokyo hourly opens | Stacked Imbalances video | 8:00 PM and 9:00 PM EST hourly opens. His most profitable session. |
| Avoid CME open | Stacked Imbalances video | Don't trade exactly at the futures open. Wait for the candle to establish. |

---

## 6. Platform/Tool Specific

| Rule | Source | Description |
|---|---|---|
| ATAS platform | Multiple videos | Footprint charts, cluster statistics, stacked imbalances indicator. |
| Dark Pool Decoder | Premium & Discount video | Zone tool that automatically draws 3-level zones on swing points. Proprietary indicator. |
| ATAS template (.cts) | ATAS Settings video | Pre-configured Bid×Ask cluster, volume proportion colors, 400% imbalance, bold white font. |
| Tanuki Trade | World Cup video | Web-based platform for naive GEX calculations on NQ (free/cheap alternative to CBOE data). |