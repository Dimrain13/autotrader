import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Settings as SettingsIcon, Key, Server } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Settings() {
  const [apiKeyMasked, setApiKeyMasked] = useState('');
  const [hasApiKey, setHasApiKey] = useState(false);
  const [secretKeyMasked, setSecretKeyMasked] = useState('');
  const [hasSecretKey, setHasSecretKey] = useState(false);
  const [baseUrl, setBaseUrl] = useState('https://paper-api.alpaca.markets');
  const [paperTrading, setPaperTrading] = useState(true);
  const [smaShort, setSmaShort] = useState(20);
  const [smaLong, setSmaLong] = useState(50);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const response = await axios.get(`${API}/settings`);
      setApiKeyMasked(response.data.api_key_masked || '');
      setHasApiKey(response.data.has_api_key || false);
      setSecretKeyMasked(response.data.secret_key_masked || '');
      setHasSecretKey(response.data.has_secret_key || false);
      setBaseUrl(response.data.base_url || 'https://paper-api.alpaca.markets');
      setPaperTrading(response.data.paper_trading !== false);
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
        sma_short: smaShort,
        sma_long: smaLong
      });
      toast.success('Settings saved successfully');
    } catch (error) {
      console.error('Failed to save settings:', error.message);
      toast.error(error?.response?.data?.detail || 'Failed to save settings');
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
              <strong>Security:</strong> API keys are managed via the backend <code>.env</code> file only and can no longer be edited or viewed here in plaintext. Update <code>ALPACA_API_KEY</code> / <code>ALPACA_SECRET_KEY</code> directly in <code>.env</code> and restart the backend to change them.
            </div>
          </div>

          <div>
            <Label className="text-xs text-neutral-500">
              <Key className="inline mr-1" size={14} />
              API Key
            </Label>
            <Input
              data-testid="input-api-key"
              value={hasApiKey ? apiKeyMasked : 'Not configured'}
              readOnly
              disabled
              className="mt-1 bg-[#121212] border-white/10 text-neutral-400 font-mono cursor-not-allowed"
            />
          </div>

          <div>
            <Label className="text-xs text-neutral-500 flex items-center gap-2">
              <Key className="inline" size={14} />
              Secret Key
              {hasSecretKey && (
                <span className="text-[10px] px-2 py-0.5 bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/30 rounded-full">
                  ✓ SET
                </span>
              )}
            </Label>
            <Input
              data-testid="input-secret-key"
              value={hasSecretKey ? secretKeyMasked : 'Not configured'}
              readOnly
              disabled
              className="mt-1 bg-[#121212] border-white/10 text-neutral-400 font-mono cursor-not-allowed"
            />
          </div>

          <div>
            <Label className="text-xs text-neutral-500">
              <Server className="inline mr-1" size={14} />
              Trading Mode
            </Label>
            <div
              data-testid="trading-mode-display"
              className="mt-1 bg-[#121212] border border-white/10 rounded-sm px-3 py-2 text-white text-sm font-mono"
            >
              {baseUrl}
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              {paperTrading ? (
                <span className="text-[#2E5CFF]">✓ Paper trading mode - No real money at risk</span>
              ) : (
                <span className="text-[#FF1A40]">⚠ LIVE TRADING MODE - Real money is at risk</span>
              )}
            </div>
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

          <div className="pt-4">
            <Button
              onClick={saveSettings}
              disabled={saving || smaShort >= smaLong}
              data-testid="save-settings-button"
              className="w-full bg-[#00E599] text-black font-bold hover:bg-[#00CC88] rounded-sm uppercase tracking-wider text-xs shadow-[0_0_15px_rgba(0,229,153,0.3)]"
            >
              {saving ? 'Saving...' : 'Save SMA Settings'}
            </Button>
          </div>
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