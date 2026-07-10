# Warrior Trading Strategy Implementation

## 📋 Overview

This auto-trader implements Ross Cameron's **Small Cap Momentum Strategy** for pre-market/morning trading (7 AM - 11 AM EST).

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

1. **Micro-Pullback Pattern**
   - Recent high established (rally peak)
   - Small pullback of 1-3% from high
   - Price breaking above high (new breakout)

2. **MACD Confirmation**
   - MACD line above signal line (bullish)
   - Indicates momentum is strengthening

3. **SMA20 Confirmation**
   - Price above 20-period SMA
   - Confirms uptrend

4. **Scanner Criteria**
   - Stock must have 5/5 criteria met
   - Top momentum stocks only

---

### **Position Sizing**

**5% of Account Per Trade**

Examples:
- $1,000 account → $50 per trade
- $2,000 account → $100 per trade
- $5,000 account → $250 per trade
- $10,000 account → $500 per trade

This conservative sizing allows for:
- Multiple positions (up to 5 concurrent)
- Room for losses without major damage
- Steady account growth through base hits

---

### **Profit Targets & Stop Losses**

| Metric | Value | Formula |
|--------|-------|---------|
| **Profit Target** | +10% | Entry × 1.10 |
| **Stop Loss** | -5% | Entry × 0.95 |
| **Risk/Reward** | 2:1 | Risk $50 to make $100 |

**Example Trade:**
- Entry: $10.00
- Stop Loss: $9.50 (-5%)
- Profit Target: $11.00 (+10%)
- On 100 shares:
  - Risk: $50
  - Reward: $100

---

### **Exit Signals (Software-Managed)**

The auto-trader monitors positions and exits when:

1. **Profit Target Hit** (+10%)
   - Take profit immediately
   - Lock in gains

2. **Stop Loss Hit** (-5%)
   - Cut losses fast
   - Don't hold and hope

3. **MACD Bearish Cross**
   - MACD crosses below signal line
   - Momentum reversing

4. **End of Trading Window** (11 AM EST)
   - Close all positions
   - Done for the day

---

### **Daily Risk Limits**

#### **Max Daily Loss: -10% of Account**
- $1,000 account → Max loss $100
- $2,000 account → Max loss $200
- When hit: **STOP TRADING** for the day

#### **Max Consecutive Losses: 3**
- After 3 losing trades in a row
- **STOP TRADING** for the day
- Reset next trading day

#### **Trading Hours: 7:00 AM - 11:00 AM EST**
- Pre-market and morning momentum window
- Auto-close all positions at 11 AM
- Software-managed stops (pre-market has no broker stops)

---

## 🛡️ Risk Management Features

### **Daily Tracking**
- Resets automatically each trading day
- Tracks cumulative P&L
- Counts consecutive losses
- Monitors risk limits in real-time

### **Pre-Market Safety**
- **No broker stop-loss orders** (not available pre-market)
- **Software monitors every 30 seconds**
- **Automatic exits** on stop loss or profit target
- **MACD exit signals** for momentum reversal

### **Position Limits**
- Max 5 concurrent positions
- 5% position sizing (conservative)
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
self.position_size_pct = 0.05          # 5% of account per trade
self.profit_target_pct = 0.10          # 10% profit target
self.stop_loss_pct = 0.05              # 5% stop loss
self.daily_max_loss_pct = 0.10         # 10% max daily loss
self.max_consecutive_losses = 3         # Max 3 losses then done
self.trading_start_hour = 7             # 7 AM EST
self.trading_end_hour = 11              # 11 AM EST
```

---

## 📱 UI Status Display

When auto-trader is active, the Scanner page shows:

### **Strategy Metrics**
- Position Size: 5%
- Profit Target: +10%
- Stop Loss: -5%
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
- System trades automatically 7-11 AM EST
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
- **Micro-pullbacks**: 1-3% retracements on front side of momentum
- **Base hits over home runs**: Consistent small wins
- **Cut losses fast**: Don't hold and hope
- **Quality over quantity**: Only A+ setups

---

## 🎓 Learning Path

### **Week 1: Observation**
- Watch scanner results
- Study micro-pullback patterns
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
1. Check if within trading hours (7-11 AM EST)
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
