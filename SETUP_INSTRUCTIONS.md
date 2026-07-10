# MomentumX Trading Platform - Setup Instructions

## Overview
MomentumX is a professional momentum trading platform that helps you find and trade small-cap stocks with high momentum using a bull flag breakout strategy.

## Features
- **Stock Scanner**: Automatically scans for stocks matching 5 criteria
  - Up 10%+ for the day
  - 5x relative volume
  - Priced between $2-$20
  - Positive news events
  - Float under 20M shares
- **Bull Flag Detection**: Identifies bull flag patterns for optimal entry
- **Real-time Trading**: Execute trades through Alpaca API
- **Portfolio Tracking**: Monitor positions and P&L in real-time
- **Paper Trading**: Practice with simulated money before going live

## Setup Instructions

### Step 1: Get Alpaca API Keys
1. Go to [alpaca.markets](https://alpaca.markets)
2. Sign up for a free account (no deposit required for paper trading)
3. Navigate to the API section in your account
4. Generate paper trading API keys
5. Copy both your **API Key** and **Secret Key**

### Step 2: Configure the Application
1. Navigate to the **Settings** page in the app
2. Paste your Alpaca API Key
3. Paste your Alpaca Secret Key
4. Select **Paper Trading** mode (recommended to start)
5. Click **Save Settings**

### Step 3: Start Trading
1. Go to the **Scanner** page
2. Click **Run Scan** to find stocks matching criteria
3. Review results and look for stocks with bull flag patterns
4. Navigate to **Trading** page to place orders
5. Monitor your positions on the **Dashboard**

## Trading Strategy

### Scanning Criteria
The scanner looks for stocks with:
1. **10%+ Daily Gain**: Stock must be up at least 10% from previous close
2. **5x Volume**: Current volume must be 5x average volume
3. **Price Range**: Stock must be priced between $2-$20
4. **Positive News**: Recent positive news catalyst
5. **Low Float**: Under 20 million shares outstanding

### Entry Signal
Wait for a **bull flag breakout pattern**:
- Initial rally of 8%+ 
- Consolidation period (tight range)
- Enter on first candle making new high after consolidation

### Risk Management
- **Profit Target**: 2:1 risk/reward ratio
- **Example**: 
  - Entry: $10.00
  - Stop Loss: $9.00 (-10%)
  - Target: $12.00 (+20%)

## Important Notes
- Always start with **paper trading** to test the strategy
- This is a momentum strategy best suited for volatile, small-cap stocks
- Pattern Day Trading rules apply if using live trading with less than $25k
- The scanner uses yfinance data which may have delays
- Always do your own research before placing any trade

## Troubleshooting

### API Not Connected
- Check that your API keys are correctly entered in Settings
- Ensure you're using paper trading keys for testing
- Restart the backend service after saving settings

### Scanner Not Finding Stocks
- Market conditions may not meet the criteria
- Try adjusting the filter parameters
- Some stocks may be filtered out due to float data availability

### Orders Not Executing
- Verify account is funded (for live trading)
- Check that markets are open (9:30 AM - 4:00 PM ET)
- Ensure stock has sufficient liquidity

## Tech Stack
- **Frontend**: React + Shadcn UI + Tailwind CSS
- **Backend**: FastAPI + Python
- **Database**: MongoDB
- **Trading API**: Alpaca Markets
- **Data**: yfinance + Alpaca Market Data

## Support
For issues with:
- Alpaca API: [Alpaca Support](https://alpaca.markets/support)
- Platform bugs: Check backend logs at `/var/log/supervisor/backend.err.log`
