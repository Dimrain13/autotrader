# Position Sizing Strategy - 20% Per Trade

## Overview
The auto-trader uses **20% of buying power per trade** for aggressive momentum day trading. This is designed for small accounts to maximize growth while managing risk through tight stop losses and 2:1 profit targets.

## Position Sizing Examples

### Example 1: $2k Account (Starting)
```
Portfolio Value: $2,000
Day Trading Leverage: 4x
Buying Power: $2,000 × 4 = $8,000

Position Size per Trade:
$8,000 × 20% = $1,600 per trade

Max Positions: 5
Max Capital Deployed: $1,600 × 5 = $8,000 (uses full buying power)

Example Trade:
Stock: PLTR @ $16.00
Shares: $1,600 / $16.00 = 100 shares
Entry: $16.00
Stop Loss: $15.20 (-5%)
Profit Target: $17.60 (+10%)
Risk: $80 per trade
Reward: $160 per trade (2:1 ratio)
```

### Example 2: $5k Account (Growing)
```
Portfolio Value: $5,000
Day Trading Leverage: 4x
Buying Power: $5,000 × 4 = $20,000

Position Size per Trade:
$20,000 × 20% = $4,000 per trade

Max Positions: 5
Max Capital Deployed: $4,000 × 5 = $20,000

Example Trade:
Stock: RIVN @ $12.00
Shares: $4,000 / $12.00 = 333 shares
Entry: $12.00
Stop Loss: $11.40 (-5%)
Profit Target: $13.20 (+10%)
Risk: $200 per trade
Reward: $400 per trade (2:1 ratio)
```

### Example 3: $10k Account (Target Reached)
```
Portfolio Value: $10,000
Day Trading Leverage: 4x
Buying Power: $10,000 × 4 = $40,000

Position Size per Trade:
$40,000 × 20% = $8,000 per trade

Max Positions: 5
Max Capital Deployed: $8,000 × 5 = $40,000

Example Trade:
Stock: NIO @ $8.00
Shares: $8,000 / $8.00 = 1,000 shares
Entry: $8.00
Stop Loss: $7.60 (-5%)
Profit Target: $8.80 (+10%)
Risk: $400 per trade
Reward: $800 per trade (2:1 ratio)
```

## Why 20% Position Sizing?

### Advantages:
1. **Aggressive Growth** - Small accounts need bigger positions to grow
2. **Multiple Opportunities** - Can take 5 positions simultaneously
3. **Full Leverage Use** - Maximizes 4x buying power efficiently
4. **Risk Management** - 5% stop loss limits risk per trade

### Risk Per Trade:
- Position Size: 20% of buying power
- Stop Loss: 5% below entry
- **Actual Risk: 20% × 5% = 1% of total buying power per trade**
- With 5 positions: Max risk = 5% of buying power

### Example Risk Calculation:
```
$2k account with 4x leverage = $8k buying power

Single Trade:
Position: $1,600 (20% of $8k)
Stop Loss: 5%
Risk: $1,600 × 5% = $80
Risk as % of buying power: $80 / $8,000 = 1%

5 Simultaneous Trades:
Total Capital: $8,000
Total Risk (all hit stops): $400
Risk as % of buying power: 5%
Risk as % of account value: $400 / $2,000 = 20%
```

## When Position Sizing Changes

### Small Account Phase ($2k - $10k):
- **Position Size**: 20% of buying power
- **Goal**: Aggressive growth
- **Max Positions**: 5
- **Strategy**: Take every valid signal

### Established Account Phase ($10k+):
- **Position Size**: 20% of buying power (same)
- **Goal**: Consistent profits
- **Max Positions**: 5
- **Strategy**: More selective entries

**Note**: Position size percentage stays at 20% throughout. What changes is the absolute dollar amount as account grows.

## Risk Management Rules

### Built-In Protections:
1. **Stop Loss**: Automatic 5% exit on all positions
2. **Profit Target**: Automatic 10% exit (2:1 ratio)
3. **Max Positions**: Limited to 5 concurrent trades
4. **Same-Day Exit**: All positions closed by market close
5. **Pattern Recognition**: Only trades confirmed bull flags

### Position Sizing Limits:
- Minimum: 1 share (for very expensive stocks)
- Maximum: 20% of buying power
- No position can exceed 20% allocation
- Total exposure capped at 100% (5 positions × 20%)

## Daily Trading Example

**Starting Balance**: $2,000 (with 4x leverage = $8,000 buying power)

**Morning Session (9:30 AM - 10:30 AM)**:
```
9:32 AM - PLTR Entry
Price: $18.00
Shares: 88 shares ($1,600 position)
Stop: $17.10 | Target: $19.80

9:35 AM - RIVN Entry  
Price: $12.00
Shares: 133 shares ($1,600 position)
Stop: $11.40 | Target: $13.20

9:38 AM - NIO Entry
Price: $8.80
Shares: 181 shares ($1,600 position)
Stop: $8.36 | Target: $9.68

Total Capital Deployed: $4,800 (60% of buying power)
Total Risk if all stop: $240 (3% of buying power)
```

**Exit Results**:
```
10:15 AM - PLTR exits at target $19.80
Profit: +$158 (+10%)

10:20 AM - RIVN exits at target $13.20
Profit: +$159 (+10%)

10:25 AM - NIO exits at target $9.68
Profit: +$159 (+10%)

Daily P&L: +$476
Account Balance: $2,476 (+23.8% day)
```

## Compounding Growth Example

**Starting**: $2,000

**Month 1** (20 trading days, 50% win rate, conservative):
- Winning days: 10 days × $200 avg = +$2,000
- Losing days: 10 days × -$100 avg = -$1,000
- **Month End**: $3,000 (+50%)

**Month 2** (same performance on larger base):
- Starting: $3,000
- Buying Power: $12,000
- Position Size: $2,400
- **Month End**: $4,500 (+50%)

**Month 3**:
- Starting: $4,500
- **Month End**: $6,750

**Month 4**:
- Starting: $6,750
- **Month End**: $10,125 ✓ **$10k milestone reached!**

## Important Notes

### This is Aggressive:
- 20% sizing is for experienced day traders
- Requires strict discipline on stops
- Best for momentum strategies
- Not for swing trading or overnight holds

### Requirements:
- Pattern Day Trader status (>$25k) OR
- Paper trading account OR
- Small account with <3 day trades per week limit

### Risk Disclosure:
- Can lose money quickly with 20% sizing
- Requires 4x leverage (day trading margin)
- Stop losses must be honored
- Not suitable for beginners without practice

## Platform Configuration

**Current Settings**:
- Position Size: 20% of buying power ✓
- Max Positions: 5 ✓
- Stop Loss: 5% ✓
- Profit Target: 10% (2:1) ✓
- Day Trading Leverage: 4x ✓

**To Modify** (if needed):
Edit `/app/backend/services/auto_trader_service.py`:
```python
self.max_position_size = 0.20  # Change to 0.10 for 10%, 0.15 for 15%, etc.
```

## Summary

**Position Sizing Strategy**: 20% of buying power per trade

**For $2k Account**:
- Buying Power: $8,000 (4x leverage)
- Position Size: $1,600 per trade
- Max Positions: 5
- Max Deployed: $8,000

**For $10k+ Account**:
- Buying Power: $40,000+ (4x leverage)
- Position Size: $8,000+ per trade
- Max Positions: 5
- Max Deployed: $40,000+

**Risk Per Trade**: 1% of buying power (20% position × 5% stop)

**This aggressive sizing is designed for momentum day trading with tight stops and quick exits!**
