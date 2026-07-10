# Auto-Scan Feature Guide

## Overview
The MomentumX Auto-Scan feature continuously monitors the market for stocks meeting your momentum trading criteria. When new opportunities are detected, you receive instant notifications.

## How It Works

### 1. **Automatic Monitoring**
- Scans the market **every 60 seconds**
- Monitors your watchlist of volatile small-cap stocks
- Checks all 5 criteria automatically:
  - ✓ Up 10%+ for the day
  - ✓ 5x relative volume  
  - ✓ Price $2-$20
  - ✓ Positive news event
  - ✓ Float <20M shares

### 2. **Real-Time Notifications**
When a stock enters your criteria:
- **Visual Alert**: Toast notification shows the symbol(s)
- **Audio Alert**: Brief sound notification
- **Bull Flag Detection**: Automatically checks for bull flag patterns
- **Banner**: Green "READY TO TRADE" badge appears

### 3. **Continuous Operation**
- Runs in the background while you're on any page
- Tracks total scan count
- Shows last scan timestamp
- Displays countdown to next scan

## Using Auto-Scan

### Enable Auto-Scan
1. Navigate to the **Scanner** page
2. Toggle the **"Auto-Scan"** switch in the header (top right)
3. Green "Auto-Scan Active" banner appears
4. Scanner immediately begins monitoring

### Disable Auto-Scan  
1. Toggle the **"Auto-Scan"** switch again
2. Status changes to "PAUSED"
3. Manual scan button becomes available again

### Adjust Criteria
- Change any criteria while auto-scan is active
- Scanner automatically applies new criteria on next cycle
- **Tip**: Start with default criteria during your first sessions

## Best Practices

### 📅 Timing
- **Enable during market hours**: 9:30 AM - 4:00 PM ET
- **Peak momentum window**: 7:00 AM - 10:00 AM ET
- Most opportunities occur in the first 90 minutes of trading

### 🎯 Strategy
1. **Enable auto-scan** at market open (9:30 AM ET)
2. **Monitor notifications** for new opportunities
3. **Check bull flag indicator** - only trade stocks with ✓
4. **Review chart** on Trading page before entering
5. **Set 2:1 profit target** based on entry price

### ⚠️ Important Notes
- Auto-scan runs **client-side** (in your browser)
- Keep the browser tab open for continuous monitoring
- Close tab = auto-scan stops
- Battery-efficient: runs only every 60 seconds

## Notification Types

### 🚨 New Opportunity Alert
**When:** A stock newly enters all 5 criteria  
**Action:** Review immediately - fresh momentum  
**Sound:** Single beep notification

### 🔔 Bull Flag Detected  
**When:** Stock shows bull flag pattern  
**Action:** High-priority - ready to trade  
**Visual:** Green "READY TO TRADE" badge

### 📊 Scan Complete
**When:** Each scan cycle completes  
**Display:** Updated timestamp and scan count  
**No sound** - background operation

## Technical Details

### Scan Frequency
- **Interval**: 60 seconds (1 minute)
- **Watchlist Size**: ~20 stocks per scan
- **Response Time**: 3-10 seconds per scan
- **Data Source**: Alpaca Markets API (real-time)

### Data Freshness
- **Price Data**: Real-time (sub-second delay)
- **Volume Data**: Updated every bar (5-min or 1-min)
- **News Detection**: Currently simulated (upgrade available)
- **Float Data**: Currently simulated (upgrade available)

### Performance
- **CPU Usage**: Minimal (<1% average)
- **Network**: ~50KB per scan
- **Battery Impact**: Low (60-second intervals)
- **Memory**: <10MB additional

## Troubleshooting

### Auto-Scan Not Finding Stocks
**Possible Reasons:**
1. **Market Conditions**: No stocks currently meet strict criteria
2. **Market Hours**: After 10 AM, momentum decreases
3. **Criteria Too Strict**: Try reducing min_change to 8% or volume_ratio to 4x

**Solutions:**
- Check Demo page to see what results should look like
- Adjust criteria temporarily for testing
- Most active period is 9:30-10:30 AM ET

### Notifications Not Appearing
**Check:**
1. Browser notifications enabled
2. Sound enabled in browser settings
3. Tab is focused (some browsers suppress background tabs)

**Fix:**
- Reload the page
- Toggle auto-scan off and on again
- Check browser console for errors

### High CPU Usage
**If scanner is using too much CPU:**
1. Close other resource-intensive tabs
2. Reduce number of stocks in watchlist
3. Increase scan interval (requires code change)

## Advanced Features (Coming Soon)

### Planned Enhancements
- [ ] **Variable Intervals**: Scan every 30s, 60s, or 120s
- [ ] **Custom Watchlists**: Add your own symbols
- [ ] **Historical Scans**: Backtest on past data
- [ ] **Slack/Email Alerts**: Remote notifications
- [ ] **Multi-Strategy**: Multiple criteria sets running simultaneously
- [ ] **Float Data Integration**: Real fundamentals data
- [ ] **News Sentiment AI**: True positive news detection

## FAQ

**Q: Can I leave auto-scan running all day?**  
A: Yes, but it's most effective during morning momentum (7-10 AM ET). You may want to disable it in the afternoon when volume drops.

**Q: Why don't I see any results?**  
A: The criteria are strict (10%+, 5x volume, bull flag). This is intentional - we want high-quality setups only. Check the Demo page to see examples.

**Q: Does auto-scan work when I'm on other pages?**  
A: Yes! Once enabled, it runs in the background. You'll get notifications even if you're on the Dashboard or Trading page.

**Q: How do I know if a stock is ready to trade?**  
A: Look for the green ✓ in the "Bull Flag" column and "READY TO TRADE" badge. These indicate the pattern is confirmed.

**Q: Can I adjust the scan interval?**  
A: Currently fixed at 60 seconds. Contact support if you need custom intervals for your trading style.

## Support
- **Platform Issues**: Check `/var/log/supervisor/backend.err.log`
- **Alpaca API**: https://alpaca.markets/support
- **Feature Requests**: Contact your platform administrator

---

**Remember**: Auto-scan finds opportunities, but you make the trading decisions. Always verify the setup manually before placing trades!
