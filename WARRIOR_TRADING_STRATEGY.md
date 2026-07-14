# Warrior Trading Strategy Implementation

## 📋 Overview

This auto-trader implements Ross Cameron's **"First Pullback" Small Cap
Momentum Strategy** for entries throughout 7 AM - 3:30 PM EST, managing
and closing all positions by 3:30 PM EST.

> **For the full rule-by-rule breakdown with diagrams**, see
> [`WARRIOR_TRADING_FIRST_PULLBACK_STRATEGY.md`](./WARRIOR_TRADING_FIRST_PULLBACK_STRATEGY.md) —
> this file is the quick-reference summary.

---

## 🎯 Strategy Rules

### **Scanner Criteria (5 Required)**
All stocks must meet these criteria before consideration:

1. **Price**: $2 - $20 per share
2. **Relative Volume**: 5x above 20-day average
3. **Float**: Under 20 million shares
4. **Percentage Change**: +10% on the day
5. **News Catalyst**: Positive news event

---

### **Entry Signals (All Must Be Met)**

1. **First Pullback Pattern** (required)
   - Initial high-volume surge, then a recent high established
   - 1-3 RED candle pullback (profit-taking)
   - The 50% Rule: pullback must hold at least 50% of the initial surge
   - Entry: first candle to break the high of the preceding red candle

2. **Volume Confirmation**
   - Green volume bars after a red bar (buying pressure)

3. **MACD Confirmation**
   - MACD line crosses above signal line (bullish crossover)
   - Indicates momentum is strengthening

4. **SMA20/SMA50 Confirmation**
   - Fast SMA(20) crosses above slow SMA(50)
   - Confirms uptrend

5. **Scanner Criteria**
   - Stock must have 5/5 criteria met
   - Top momentum stocks only

---

### **Position Sizing**

**10% of Account Per Trade** (up to 5 concurrent = 50% max exposure)

Examples:
- $1,000 account → $100 per trade
- $2,000 account → $200 per trade
- $5,000 account → $500 per trade
- $10,000 account → $1,000 per trade

This sizing allows for:
- Multiple positions (up to 5 concurrent)
- Room for losses without major damage (structural stop is safety-capped at 3% of entry)
- Steady account growth through base hits

---

### **Profit Targets & Stop Losses**

| Metric | Value | Formula |
|--------|-------|---------|
| **Stop Loss** | Structural | Low of the pullback candles (capped at 3% of entry, safety limit) |
| **Profit Target** | 2:1 | Entry + 2 × (Entry - Stop) — sell 50%, move stop to breakeven |
| **Risk/Reward** | 2:1 | Ross Cameron / Warrior Trading core rule |

**Example Trade:**
- Entry: $10.00 (breakout above the pullback high)
- Stop Loss: $9.90 (the actual low of the pullback candles)
- Risk: $0.10/share
- Profit Target: $10.20 (2:1 — sell half, move stop to breakeven on the rest)
- On 100 shares:
  - Risk: $10
  - Reward: $20

---

### **Exit Signals (Software-Managed)**

The auto-trader monitors positions and exits when:

1. **Profit Target Hit** (2:1 reward:risk)
   - Sell 50% of the position, move stop to break-even on the rest
   - Lock in gains while letting a winner run

2. **Structural Stop Hit** (low of the pullback)
   - Cut losses fast
   - Don't hold and hope

3. **"Breakout or Bailout"** (90s time-stop)
   - If the trade hasn't moved into profit within 90 seconds of entry, exit immediately
   - True momentum resolves almost instantly — don't wait for the full stop to hit

4. **End of Trading Window** (3:30 PM EST)
   - Close all positions
   - Done for the day

---

### **Daily Risk Limits**

#### **Max Daily Loss: -1% of Account (HARD KILL SWITCH)**
- $1,000 account → Max loss $10
- $2,000 account → Max loss $20
- When hit: **ALL new BUY orders are blocked server-side** (manual and auto-trader) for the rest of the day
- This is Ross Cameron's documented "conservative starting" daily risk rule

#### **Max Consecutive Losses: 3**
- After 3 losing trades in a row
- **STOP TRADING** for the day
- Reset next trading day

#### **Trading Hours: Entries + Management 7:00 AM - 3:30 PM EST**
- Entries and position management run the full window (already-fixed
  dead code that once restricted entries to a false "7-11 AM" window
  has been removed - see Session 11 in `/app/memory/PRD.md`)
- Auto-close all positions at 3:30 PM EST
- Software-managed stops (pre-market/extended hours has no broker stops)

---

## 🛡️ Risk Management Features

### **Daily Tracking**
- Resets automatically each trading day
- Tracks cumulative P&L
- Counts consecutive losses
- Monitors risk limits in real-time

### **Pre-Market Safety**
- **No broker stop-loss orders** (not available pre-market)
- **Software monitors every 60 seconds** (auto-trader background loop)
- **Automatic exits** on structural stop, breakout-or-bailout, or profit target
- **"Breakout or bailout"** time-stop for stalled entries

### **Position Limits**
- Max 5 concurrent positions
- 10% position sizing per trade (50% max exposure)
- Prevents over-concentration

---

## 📊 Strategy Performance Metrics

### **Win Rate Target**
- Aim for 50-60% win rate
- With 2:1 risk/reward, profitable even at 40%

### **Average Winners vs Losers**
- Target: Winners 2x size of losers
- Example: Win $100, Lose $50

### **Daily Targets**
- **Novice** (Month 1): 1 green day per week
- **Beginner** (Month 2): 2 green days per week
- **Advanced** (Month 4): 3-5 green days per week
- **Pro**: 5+ green days per week

---

## 🔧 Configuration

### **Environment Variables**
Located in `/app/backend/.env`:

```bash
# SMA Periods (configurable via Settings page)
SMA_SHORT=20        # Fast SMA (default: 20)
SMA_LONG=50         # Slow SMA (default: 50)
```

### **Strategy Parameters**
Located in `/app/backend/services/auto_trader_service.py`:

```python
self.position_size_pct = 0.10               # 10% of account per trade
self.pullback_retracement_max_pct = 0.50    # The 50% Rule
self.max_stop_distance_pct = 0.03           # Safety cap on structural stop distance
self.breakout_bailout_seconds = 90          # Time-stop if trade never turns profitable
self.daily_max_loss_pct = 0.01              # 1% max daily loss (hard kill switch)
self.max_consecutive_losses = 3             # Max 3 losses then done
self.require_micro_pullback = True          # First-pullback pattern required for entry
self.trading_start_hour = 7                 # 7 AM EST (entries)
self.trading_end_hour = 15                  # 3:30 PM EST (manage/close)
self.trading_end_minute = 30
```

---

## 📱 UI Status Display

When auto-trader is active, the Scanner page shows:

### **Strategy Metrics**
- Position Size: 10%
- Profit Target: 2:1 reward:risk (partial)
- Stop Loss: structural (low of pullback, capped at 3%)
- Daily P&L: Real-time tracking
- Loss Streak: X / 3

### **Risk Alerts**
- ⚠️ Warns when approaching limits
- 🛑 Shows when trading halted
- ✅ Displays "Risk limits OK" when clear

---

## 🚀 How to Use

### **1. Enable Auto-Trading**
- Go to Scanner page
- Toggle "Auto-Trade" switch to ON
- Status card will appear at top

### **2. Monitor Status**
- Check daily P&L
- Watch consecutive losses
- Review open positions

### **3. Let It Run**
- System trades automatically 7 AM - 3:30 PM EST
- Follows all rules precisely
- No emotion, no deviation

### **4. Review Results**
- Check end-of-day P&L
- Analyze winning trades
- Learn from losers

---

## ⚠️ Important Notes

### **Pre-Market Trading**
- Broker stop-loss orders **NOT available**
- Software manages all exits
- More volatile than regular hours
- Requires close monitoring

### **Paper Trading First**
- Test strategy with paper trading
- Build confidence
- Understand the patterns
- Then go live with small size

### **Risk Disclaimer**
- Day trading is risky
- Can lose more than invested
- Use only risk capital
- Start small and scale up

---

## 📚 Strategy Resources

Based on Ross Cameron's courses:
- **SAC2024-Strategy-PDF.pdf** - Core strategy rules
- **Sample-Trading-Plan.pdf** - Position sizing & risk management

### **Key Concepts**
- **First Pullback**: 1-3 red candles after a surge, must hold 50%+, entry breaks the pullback high
- **Base hits over home runs**: Consistent small wins
- **Cut losses fast**: Don't hold and hope (structural stop + breakout-or-bailout time-stop)
- **Quality over quantity**: Only A+ setups

---

## 🎓 Learning Path

### **Week 1: Observation**
- Watch scanner results
- Study first-pullback patterns
- Note MACD signals

### **Week 2: Small Positions**
- Start with 1-2 trades/day
- Focus on entry timing
- Practice exits

### **Week 3: Build Consistency**
- Aim for 1 green day
- Follow rules strictly
- Track all trades

### **Month 2+: Scale Up**
- Increase position size gradually
- Add more positions
- Target 2-3 green days/week

---

## 📈 Success Metrics

### **Track These KPIs**
- Win rate (target: 50%+)
- Average win vs average loss (target: 2:1)
- Daily P&L
- Green days per week
- Consecutive losses
- Rule violations (goal: 0)

### **Monthly Review**
- Total P&L
- Best/worst trades
- Pattern recognition
- Rule adherence
- Strategy adjustments

---

## 🛠️ Troubleshooting

### **Auto-Trader Not Executing**
1. Check if within trading hours (7 AM - 3:30 PM EST)
2. Verify risk limits not breached
3. Confirm scanner has 5/5 stocks
4. Check logs for entry signal details

### **Stopped Due to Losses**
- Normal protective feature
- Reset next trading day
- Review losing trades
- Adjust if needed

### **Positions Not Closing**
- Software monitors every 30 seconds
- Check MACD for exit signals
- Verify profit target/stop loss levels
- Manual close available on Trading page

---

## 📞 Support

For questions or issues:
1. Review this documentation
2. Check `/var/log/supervisor/backend.err.log` for detailed logs
3. Test in Demo Mode first
4. Start with paper trading

---

**Remember**: This is a professional trading strategy. Follow the rules, manage risk, and be patient. Success comes from consistency, not home runs. 🎯
