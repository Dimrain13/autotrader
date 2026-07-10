import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Settings as SettingsIcon, Key, Server } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Settings() {
  const [apiKey, setApiKey] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://paper-api.alpaca.markets');
  const [dayTradingMode, setDayTradingMode] = useState(false);
  const [smaShort, setSmaShort] = useState(20);
  const [smaLong, setSmaLong] = useState(50);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const response = await axios.get(`${API}/settings`);
      setApiKey(response.data.api_key || '');
      // Show masked secret key if it exists
      if (response.data.has_secret_key) {
        setSecretKey(response.data.secret_key_masked || '********************************');
      }
      setBaseUrl(response.data.base_url || 'https://paper-api.alpaca.markets');
      setDayTradingMode(response.data.day_trading_mode || false);
      setSmaShort(response.data.sma_short || 20);
      setSmaLong(response.data.sma_long || 50);
    } catch (error) {
      console.error('Failed to fetch settings:', error);
    }
  };

  const saveSettings = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/settings`, {
        api_key: apiKey,
        secret_key: secretKey,
        base_url: baseUrl,
        day_trading_mode: dayTradingMode,
        sma_short: smaShort,
        sma_long: smaLong
      });
      // Settings saved
    } catch (error) {
      console.error('Failed to save settings:', error.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Warrior Trading Strategy Info */}
      <Card className="bg-[#0A0A0A] border-[#00E599]/30">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <SettingsIcon className="inline mr-2" size={18} />
            Warrior Trading Strategy (Active)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-4 bg-[#00E599]/10 border border-[#00E599]/20 rounded-sm">
            <div className="text-sm text-[#00E599] font-bold mb-3">
              Small Cap Momentum Strategy - Pre-Market Trading (7-11 AM EST)
            </div>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Position Sizing</div>
                <div className="text-white font-mono font-bold">5% of account per trade</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Max Positions</div>
                <div className="text-white font-mono font-bold">5 concurrent</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Profit Target</div>
                <div className="text-[#00E599] font-mono font-bold">+10% per trade</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Stop Loss</div>
                <div className="text-[#FF1A40] font-mono font-bold">-5% per trade</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Daily Max Loss</div>
                <div className="text-[#FF1A40] font-mono font-bold">-10% of account</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Max Consecutive Losses</div>
                <div className="text-yellow-500 font-mono font-bold">3 losses (then stop)</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Trading Hours</div>
                <div className="text-white font-mono font-bold">7:00 AM - 11:00 AM EST</div>
              </div>
              <div>
                <div className="text-neutral-500 text-xs uppercase mb-1">Risk/Reward Ratio</div>
                <div className="text-[#00E599] font-mono font-bold">2:1 (Risk $50, Make $100)</div>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-white/10">
              <div className="text-neutral-400 text-xs">
                <strong>Entry Signals:</strong> Micro-pullback (1-3%) + MACD Bullish + Price &gt; SMA20 + Scanner 5/5
              </div>
              <div className="text-neutral-400 text-xs mt-1">
                <strong>Exit Signals:</strong> Profit target (+10%) | Stop loss (-5%) | MACD Bearish | End of window (11 AM)
              </div>
              <div className="text-neutral-400 text-xs mt-2">
                <strong>Note:</strong> All stops are software-managed (pre-market has no broker stops). See <code className="text-[#00E599]">/app/WARRIOR_TRADING_STRATEGY.md</code> for details.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="alpaca-settings-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <SettingsIcon className="inline mr-2" size={18} />
            Alpaca API Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-sm">
            <div className="text-sm text-yellow-500">
              <strong>Important:</strong> Get your API keys from{' '}
              <a 
                href="https://alpaca.markets" 
                target="_blank" 
                rel="noopener noreferrer"
                className="underline hover:text-yellow-400"
              >
                alpaca.markets
              </a>
              . Paper trading keys are free and require no deposit.
            </div>
          </div>

          <div>
            <Label htmlFor="api_key" className="text-xs text-neutral-500">
              <Key className="inline mr-1" size={14} />
              API Key
            </Label>
            <Input
              id="api_key"
              data-testid="input-api-key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              placeholder="PKxxxxxxxxxxxxxxxxxx"
            />
          </div>

          <div>
            <Label htmlFor="secret_key" className="text-xs text-neutral-500 flex items-center gap-2">
              <Key className="inline" size={14} />
              Secret Key
              {secretKey && secretKey.startsWith('*') && (
                <span className="text-[10px] px-2 py-0.5 bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/30 rounded-full">
                  ✓ SET
                </span>
              )}
            </Label>
            <Input
              id="secret_key"
              data-testid="input-secret-key"
              type="password"
              value={secretKey}
              onChange={(e) => setSecretKey(e.target.value)}
              className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              placeholder="Enter your secret key (or leave masked to keep existing)"
            />
          </div>

          <div>
            <Label htmlFor="base_url" className="text-xs text-neutral-500">
              <Server className="inline mr-1" size={14} />
              Trading Mode
            </Label>
            <Select value={baseUrl} onValueChange={setBaseUrl}>
              <SelectTrigger data-testid="select-trading-mode" className="mt-1 bg-[#121212] border-white/10 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="https://paper-api.alpaca.markets">
                  Paper Trading (Recommended)
                </SelectItem>
                <SelectItem value="https://api.alpaca.markets">
                  Live Trading (Real Money)
                </SelectItem>
              </SelectContent>
            </Select>
            <div className="mt-2 text-xs text-neutral-500">
              {baseUrl === 'https://paper-api.alpaca.markets' ? (
                <span className="text-[#2E5CFF]">✓ Paper trading mode - No real money at risk</span>
              ) : (
                <span className="text-[#FF1A40]">⚠ Live trading mode - Real money will be used</span>
              )}
            </div>
          </div>

          <div className="pt-2">
            <div className="flex items-center justify-between p-4 bg-[#121212] border border-white/10 rounded-sm">
              <div className="flex-1">
                <Label htmlFor="day-trading-mode" className="text-sm text-white font-bold cursor-pointer">
                  Enable Day Trading Mode (4x Leverage)
                </Label>
                <div className="text-xs text-neutral-400 mt-1">
                  Simulates Pattern Day Trader status with 4x intraday buying power. Your $100k portfolio becomes $400k buying power.
                </div>
              </div>
              <Switch
                id="day-trading-mode"
                checked={dayTradingMode}
                onCheckedChange={setDayTradingMode}
                data-testid="day-trading-mode-toggle"
              />
            </div>
            {dayTradingMode && (
              <div className="mt-2 p-3 bg-[#00E599]/10 border border-[#00E599]/20 rounded-sm text-xs text-[#00E599]">
                ✓ Day Trading Mode enabled - You will have 4x intraday buying power for momentum trading
              </div>
            )}
          </div>

          <div className="pt-4">
            <Button
              onClick={saveSettings}
              disabled={saving || !apiKey || !secretKey}
              data-testid="save-settings-button"
              className="w-full bg-[#00E599] text-black font-bold hover:bg-[#00CC88] rounded-sm uppercase tracking-wider text-xs shadow-[0_0_15px_rgba(0,229,153,0.3)]"
            >
              {saving ? 'Saving...' : 'Save Settings'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="sma-settings-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <SettingsIcon className="inline mr-2" size={18} />
            SMA Indicator Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-sm">
            <div className="text-sm text-blue-400">
              <strong>Auto-Trader Strategy:</strong> Configure the Simple Moving Averages used for trend confirmation. The auto-trader checks if the short SMA is above the long SMA (bullish crossover) before entering trades.
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="sma_short" className="text-xs text-neutral-500">
                Short SMA Period
              </Label>
              <Select value={smaShort.toString()} onValueChange={(v) => setSmaShort(parseInt(v))}>
                <SelectTrigger data-testid="select-sma-short" className="mt-1 bg-[#121212] border-white/10 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="9">9 MA (Very Fast)</SelectItem>
                  <SelectItem value="20">20 MA (Fast - Default)</SelectItem>
                  <SelectItem value="50">50 MA (Medium)</SelectItem>
                  <SelectItem value="100">100 MA (Slow)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="sma_long" className="text-xs text-neutral-500">
                Long SMA Period
              </Label>
              <Select value={smaLong.toString()} onValueChange={(v) => setSmaLong(parseInt(v))}>
                <SelectTrigger data-testid="select-sma-long" className="mt-1 bg-[#121212] border-white/10 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="20">20 MA (Fast)</SelectItem>
                  <SelectItem value="50">50 MA (Medium - Default)</SelectItem>
                  <SelectItem value="100">100 MA (Slow)</SelectItem>
                  <SelectItem value="200">200 MA (Very Slow)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="mt-2 p-3 bg-[#121212] border border-white/10 rounded-sm">
            <div className="text-xs text-neutral-400">
              <strong className="text-white">Current Setup:</strong> {smaShort} MA / {smaLong} MA
            </div>
            <div className="text-xs text-neutral-500 mt-2">
              <strong>Popular Combinations:</strong>
              <div className="mt-1 space-y-1">
                <div>• 20/50 MA - Fast (Day Trading) ⚡</div>
                <div>• 50/200 MA - Standard (Swing Trading)</div>
                <div>• 9/20 MA - Very Fast (Scalping)</div>
              </div>
            </div>
          </div>

          {smaShort >= smaLong && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-sm text-xs text-red-400">
              ⚠️ Warning: Short SMA must be less than Long SMA for crossover strategy to work properly.
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="setup-guide-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Setup Guide</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#2E5CFF]/20 border border-[#2E5CFF] flex items-center justify-center text-[#2E5CFF] font-mono font-bold text-sm">
                1
              </div>
              <div>
                <div className="text-sm font-bold text-white mb-1">Create Alpaca Account</div>
                <div className="text-sm text-neutral-400">
                  Sign up at{' '}
                  <a href="https://alpaca.markets" target="_blank" rel="noopener noreferrer" className="text-[#2E5CFF] hover:underline">
                    alpaca.markets
                  </a>
                  {' '}for free. No deposit required for paper trading.
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#2E5CFF]/20 border border-[#2E5CFF] flex items-center justify-center text-[#2E5CFF] font-mono font-bold text-sm">
                2
              </div>
              <div>
                <div className="text-sm font-bold text-white mb-1">Get Your API Keys</div>
                <div className="text-sm text-neutral-400">
                  After logging in, navigate to the API section and generate your paper trading API keys.
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#2E5CFF]/20 border border-[#2E5CFF] flex items-center justify-center text-[#2E5CFF] font-mono font-bold text-sm">
                3
              </div>
              <div>
                <div className="text-sm font-bold text-white mb-1">Enter Keys Above</div>
                <div className="text-sm text-neutral-400">
                  Copy your API Key and Secret Key, paste them in the form above, and save.
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#00E599]/20 border border-[#00E599] flex items-center justify-center text-[#00E599] font-mono font-bold text-sm">
                4
              </div>
              <div>
                <div className="text-sm font-bold text-white mb-1">Start Trading</div>
                <div className="text-sm text-neutral-400">
                  You're all set! Use the Scanner to find opportunities and the Trading page to execute orders.
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="strategy-info-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Trading Strategy Overview</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 text-sm">
            <div>
              <div className="text-white font-bold mb-2">Stock Screening Criteria:</div>
              <ul className="text-neutral-400 space-y-1">
                <li>• Stock is up 10% or more for the day</li>
                <li>• Has 5x relative volume compared to average</li>
                <li>• Priced between $2-$20 per share</li>
                <li>• Has a positive news event</li>
                <li>• Float under 20 million shares</li>
              </ul>
            </div>
            <div>
              <div className="text-white font-bold mb-2">Entry Signal:</div>
              <div className="text-neutral-400">
                Wait for a bull flag breakout pattern. Enter on the first candle that makes a new high after the consolidation period.
              </div>
            </div>
            <div>
              <div className="text-white font-bold mb-2">Risk Management:</div>
              <div className="text-neutral-400">
                Use a 2:1 profit target. For every $1 of risk, target $2 of profit.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}