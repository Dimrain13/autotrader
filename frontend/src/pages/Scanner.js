import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Search, TrendingUp, Volume2, DollarSign, Newspaper, Users, PlayCircle, PauseCircle, Bell } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Scanner({ scanner }) {
  const navigate = useNavigate();
  const {
    scanning, results, setResults,
    autoScan, setAutoScan,
    demoMode, setDemoMode,
    autoTrade,
    traderStatus,
    lastScanTime, scanCount, nextScanCountdown,
    criteria, updateCriteria,
    runScan
  } = scanner;
  const [momentumStocks, setMomentumStocks] = useState([]); // Stocks building momentum
  const [activeTab, setActiveTab] = useState(() => {
    const saved = localStorage.getItem('scannerActiveTab');
    return saved || 'gappers';
  });
  
  // Fetch momentum stocks
  const fetchMomentumStocks = async () => {
    try {
      const response = await axios.get(`${API}/scanner/momentum`, { timeout: 30000 });
      if (response.data.stocks) {
        setMomentumStocks(response.data.stocks);
      }
    } catch (error) {
      console.error('Failed to fetch momentum stocks:', error);
    }
  };

  // Get sorted results based on active tab
  const getSortedResults = () => {
    // For momentum tab, return momentum stocks
    if (activeTab === 'momentum') {
      return momentumStocks;
    }
    
    let sorted = [...results];
    
    switch (activeTab) {
      case 'gappers':
        // Sort by gap % (highest first)
        sorted.sort((a, b) => (b.gap_pct || 0) - (a.gap_pct || 0));
        break;
      case 'gainers':
        // Sort by % change (highest first)
        sorted.sort((a, b) => (b.pct_change || 0) - (a.pct_change || 0));
        break;
      case 'volume':
        // Sort by volume ratio (highest first)
        sorted.sort((a, b) => (b.volume_ratio || 0) - (a.volume_ratio || 0));
        break;
      case 'news':
        // Filter to only stocks with news
        sorted = sorted.filter(s => s.criteria?.news || s.news_headline);
        break;
      case 'ready':
        // Filter and sort: ready to trade first, then by criteria count, then by volume
        sorted = sorted.filter(s => s.criteria_count >= 4);
        sorted.sort((a, b) => {
          if (a.ready_to_trade !== b.ready_to_trade) {
            return b.ready_to_trade ? 1 : -1;
          }
          const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
          if (criteriaCompare !== 0) return criteriaCompare;
          return (b.volume_ratio || 0) - (a.volume_ratio || 0);
        });
        break;
      default:
        // Default sort: criteria count, then volume
        sorted.sort((a, b) => {
          const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
          if (criteriaCompare !== 0) return criteriaCompare;
          return (b.volume_ratio || 0) - (a.volume_ratio || 0);
        });
    }
    
    return sorted;
  };
  const [newsModalOpen, setNewsModalOpen] = useState(false);
  const [selectedStockNews, setSelectedStockNews] = useState(null);
  const [loadingNews, setLoadingNews] = useState(false);

  const toggleAutoScan = () => setAutoScan(!autoScan);

  const toggleAutoTrade = async () => {
    try {
      await scanner.toggleAutoTrade();
    } catch (error) {
      toast.error('Failed to toggle auto-trading: ' + error.message);
    }
  };

  const toggleDemoMode = () => {
    const newState = !demoMode;
    setDemoMode(newState);
    if (newState) {
      toast.info('Demo Mode ON - Using simulated market data');
    } else {
      toast.info('Demo Mode OFF - Using live Alpaca data');
    }
  };

  return (
    <div className="space-y-4">
      {autoTrade && (
        <Card className="bg-[#00E599]/10 border-[#00E599]/30 animate-pulse">
          <CardContent className="pt-4 pb-4">
            {/* Main Status Row */}
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-shrink-0">
                <div className="h-12 w-12 rounded-full bg-[#00E599]/20 border-2 border-[#00E599] flex items-center justify-center">
                  <PlayCircle className="text-[#00E599]" size={24} />
                </div>
              </div>
              <div className="flex-1">
                <div className="text-sm font-bold text-[#00E599] uppercase tracking-wider">🤖 AUTO-TRADING ACTIVE</div>
                <div className="text-xs text-white font-mono mt-0.5">
                  {traderStatus.strategy?.name || "Warrior Trading - Small Cap Momentum"}
                </div>
                <div className="text-xs text-neutral-400 mt-1">
                  {traderStatus.strategy?.trading_hours || "7:00 AM - 3:30 PM EST"} • Entry: Micro-Pullback + MACD + SMA20
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs text-neutral-500">Positions</div>
                <div className="text-2xl font-mono font-bold text-[#00E599]">
                  {traderStatus.open_positions || 0} / {traderStatus.max_positions || 5}
                </div>
              </div>
            </div>

            {/* Strategy Metrics Grid */}
            <div className="grid grid-cols-5 gap-2 pt-3 border-t border-white/10">
              <div className="text-center">
                <div className="text-[10px] text-neutral-500 uppercase">Position Size</div>
                <div className="text-sm font-mono font-bold text-white">
                  {traderStatus.strategy?.position_size_pct || 5}%
                </div>
              </div>
              <div className="text-center">
                <div className="text-[10px] text-neutral-500 uppercase">Profit Target</div>
                <div className="text-sm font-mono font-bold text-[#00E599]">
                  +{traderStatus.strategy?.profit_target_pct || 10}%
                </div>
              </div>
              <div className="text-center">
                <div className="text-[10px] text-neutral-500 uppercase">Stop Loss</div>
                <div className="text-sm font-mono font-bold text-[#FF1A40]">
                  -{traderStatus.strategy?.stop_loss_pct || 5}%
                </div>
              </div>
              <div className="text-center">
                <div className="text-[10px] text-neutral-500 uppercase">Daily P&L</div>
                <div className={`text-sm font-mono font-bold ${
                  (traderStatus.daily_tracking?.daily_pnl || 0) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
                }`}>
                  ${traderStatus.daily_tracking?.daily_pnl?.toFixed(2) || '0.00'}
                </div>
              </div>
              <div className="text-center">
                <div className="text-[10px] text-neutral-500 uppercase">Loss Streak</div>
                <div className={`text-sm font-mono font-bold ${
                  (traderStatus.daily_tracking?.consecutive_losses || 0) >= 2 ? 'text-yellow-500' : 'text-white'
                }`}>
                  {traderStatus.daily_tracking?.consecutive_losses || 0} / 3
                </div>
              </div>
            </div>

            {/* Risk Warning */}
            {traderStatus.risk_status && !traderStatus.risk_status.can_trade && (
              <div className="mt-3 pt-3 border-t border-white/10">
                <div className="text-xs text-yellow-500 font-bold">
                  ⚠️ {traderStatus.risk_status.reason}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {autoScan && (
        <Card className="bg-[#00E599]/10 border-[#00E599]/30">
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0">
                <div className="h-10 w-10 rounded-full bg-[#00E599]/20 border border-[#00E599] flex items-center justify-center animate-pulse">
                  <Bell className="text-[#00E599]" size={20} />
                </div>
              </div>
              <div className="flex-1">
                <div className="text-sm font-bold text-[#00E599]">
                  Auto-Scan Active {demoMode && "(Demo Mode)"}
                </div>
                <div className="text-xs text-neutral-300">
                  {demoMode 
                    ? `Simulating market momentum with ${criteria.min_price}-$${criteria.max_price} stocks. Demo updates every 60 seconds.`
                    : `Monitoring ${criteria.min_price}-$${criteria.max_price} stocks every 60 seconds. You'll be notified when new opportunities appear.`
                  }
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs text-neutral-500">Next scan in</div>
                <div className="text-lg font-mono font-bold text-[#00E599]">
                  {scanning ? '...' : `${nextScanCountdown}s`}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="bg-[#0A0A0A] border-white/5" data-testid="scanner-criteria-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
              <Search className="inline mr-2" size={18} />
              Scanner Criteria
            </CardTitle>
            <div className="flex items-center gap-4">
              {lastScanTime && (
                <div className="text-xs text-neutral-500 font-mono">
                  Last scan: {lastScanTime.toLocaleTimeString('en-US', { 
                    timeZone: 'America/New_York',
                    hour: 'numeric',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                  })} ET ({scanCount} total)
                </div>
              )}
              <div className="flex items-center gap-2">
                <Label htmlFor="demo-mode" className="text-xs text-neutral-400 cursor-pointer" title="Use simulated market data instead of live Alpaca data">
                  Demo Mode
                </Label>
                <Switch
                  id="demo-mode"
                  checked={demoMode}
                  onCheckedChange={toggleDemoMode}
                  data-testid="demo-mode-toggle"
                  disabled={autoScan}
                />
                {demoMode && (
                  <div className="text-xs text-yellow-500 font-bold">SIMULATED</div>
                )}
              </div>
              <div className="h-6 w-px bg-white/10" />
              <div className="flex items-center gap-2">
                <Label htmlFor="auto-trade" className="text-xs text-neutral-400 cursor-pointer">
                  Auto-Trade
                </Label>
                <Switch
                  id="auto-trade"
                  checked={autoTrade}
                  onCheckedChange={toggleAutoTrade}
                  data-testid="auto-trade-toggle"
                />
                {autoTrade ? (
                  <div className="flex items-center gap-1 text-[#00E599] text-xs font-bold animate-pulse">
                    <PlayCircle size={16} />
                    LIVE
                  </div>
                ) : (
                  <div className="flex items-center gap-1 text-neutral-500 text-xs">
                    <PauseCircle size={16} />
                    OFF
                  </div>
                )}
              </div>
              <div className="h-6 w-px bg-white/10" />
              <div className="flex items-center gap-2">
                <Label htmlFor="auto-scan" className="text-xs text-neutral-400 cursor-pointer">
                  Auto-Scan
                </Label>
                <Switch
                  id="auto-scan"
                  checked={autoScan}
                  onCheckedChange={toggleAutoScan}
                  data-testid="auto-scan-toggle"
                />
                {autoScan ? (
                  <div className="flex items-center gap-1 text-[#00E599] text-xs font-bold animate-pulse">
                    <PlayCircle size={16} />
                    ACTIVE
                  </div>
                ) : (
                  <div className="flex items-center gap-1 text-neutral-500 text-xs">
                    <PauseCircle size={16} />
                    PAUSED
                  </div>
                )}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label htmlFor="min_price" className="text-xs text-neutral-500">Min Price ($)</Label>
              <Input
                id="min_price"
                data-testid="input-min-price"
                type="number"
                value={criteria.min_price}
                onChange={(e) => {
                  const newCriteria = {...criteria, min_price: parseFloat(e.target.value)};
                  updateCriteria(newCriteria);
                }}
                className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <Label htmlFor="max_price" className="text-xs text-neutral-500">Max Price ($)</Label>
              <Input
                id="max_price"
                data-testid="input-max-price"
                type="number"
                value={criteria.max_price}
                onChange={(e) => {
                  const newCriteria = {...criteria, max_price: parseFloat(e.target.value)};
                  updateCriteria(newCriteria);
                }}
                className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <Label htmlFor="min_change" className="text-xs text-neutral-500">Min % Change</Label>
              <Input
                id="min_change"
                data-testid="input-min-change"
                type="number"
                value={criteria.min_change}
                onChange={(e) => {
                  const newCriteria = {...criteria, min_change: parseFloat(e.target.value)};
                  updateCriteria(newCriteria);
                }}
                className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <Label htmlFor="min_volume_ratio" className="text-xs text-neutral-500">Min Volume Ratio (x)</Label>
              <Input
                id="min_volume_ratio"
                data-testid="input-min-volume-ratio"
                type="number"
                value={criteria.min_volume_ratio}
                onChange={(e) => {
                  const newCriteria = {...criteria, min_volume_ratio: parseFloat(e.target.value)};
                  updateCriteria(newCriteria);
                }}
                className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              />
            </div>
            <div>
              <Label htmlFor="max_float" className="text-xs text-neutral-500">Max Float (shares)</Label>
              <Input
                id="max_float"
                data-testid="input-max-float"
                type="number"
                value={criteria.max_float}
                onChange={(e) => {
                  const newCriteria = {...criteria, max_float: parseInt(e.target.value)};
                  updateCriteria(newCriteria);
                }}
                className="mt-1 bg-[#121212] border-white/10 text-white font-mono"
              />
            </div>
            <div className="flex items-end">
              <Button
                onClick={() => runScan()}
                disabled={scanning || autoScan}
                data-testid="scan-button"
                className="w-full bg-[#00E599] text-black font-bold hover:bg-[#00CC88] rounded-sm uppercase tracking-wider text-xs shadow-[0_0_15px_rgba(0,229,153,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {scanning ? 'Scanning...' : autoScan ? 'Auto-Scan Active' : 'Run Manual Scan'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="scanner-results-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
                Scan Results ({results.length})
              </CardTitle>
              {results.length > 0 && (
                <Button
                  onClick={() => setResults([])}
                  variant="outline"
                  size="sm"
                  data-testid="clear-results-button"
                  className="text-xs text-neutral-400 hover:text-white border-white/10 hover:border-white/20"
                >
                  Clear All
                </Button>
              )}
            </div>
            <div className="flex items-center gap-4">
              {autoScan && scanning && (
                <div className="flex items-center gap-2 text-xs text-[#2E5CFF]">
                  <div className="animate-spin h-4 w-4 border-2 border-[#2E5CFF] border-t-transparent rounded-full"></div>
                  Scanning market...
                </div>
              )}
              {results.filter(s => s.has_bull_flag).length > 0 && (
                <div className="flex items-center gap-2 px-3 py-1 bg-[#00E599]/20 border border-[#00E599]/30 rounded-sm">
                  <Bell className="text-[#00E599]" size={16} />
                  <span className="text-xs font-bold text-[#00E599]">
                    {results.filter(s => s.has_bull_flag).length} Bull Flag{results.filter(s => s.has_bull_flag).length !== 1 ? 's' : ''} Detected
                  </span>
                </div>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Scanner Tabs */}
          <div className="flex gap-2 mb-4 border-b border-white/10 pb-2 overflow-x-auto">
            <button
              onClick={() => {
                setActiveTab('gappers');
                localStorage.setItem('scannerActiveTab', 'gappers');
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'gappers'
                  ? 'bg-[#2E5CFF] text-white'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              🚀 Top Gappers
            </button>
            <button
              onClick={() => {
                setActiveTab('gainers');
                localStorage.setItem('scannerActiveTab', 'gainers');
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'gainers'
                  ? 'bg-[#00E599] text-black'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              📈 % Gainers
            </button>
            <button
              onClick={() => {
                setActiveTab('volume');
                localStorage.setItem('scannerActiveTab', 'volume');
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'volume'
                  ? 'bg-purple-500 text-white'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              📊 High Volume
            </button>
            <button
              onClick={() => {
                setActiveTab('momentum');
                localStorage.setItem('scannerActiveTab', 'momentum');
                fetchMomentumStocks();
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'momentum'
                  ? 'bg-[#F59E0B] text-black'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              ⚡ Momentum ({momentumStocks.length})
            </button>
            <button
              onClick={() => {
                setActiveTab('news');
                localStorage.setItem('scannerActiveTab', 'news');
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'news'
                  ? 'bg-pink-500 text-white'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              📰 With News
            </button>
            <button
              onClick={() => {
                setActiveTab('ready');
                localStorage.setItem('scannerActiveTab', 'ready');
              }}
              className={`px-4 py-2 text-xs font-bold rounded-sm transition-all whitespace-nowrap ${
                activeTab === 'ready'
                  ? 'bg-[#00E599] text-black'
                  : 'bg-[#121212] text-neutral-400 hover:text-white border border-white/10'
              }`}
            >
              ✅ Ready to Trade
            </button>
          </div>

          {/* Tab Description */}
          <div className="text-xs text-neutral-500 mb-3">
            {activeTab === 'gappers' && 'Stocks gapping up the most from previous close'}
            {activeTab === 'gainers' && 'Top percentage gainers for the day'}
            {activeTab === 'volume' && 'Stocks with highest relative volume'}
            {activeTab === 'momentum' && 'Stocks making higher highs (3/5 criteria) - watch for pullback entries'}
            {activeTab === 'news' && 'Stocks with positive news catalysts'}
            {activeTab === 'ready' && 'Stocks meeting 4/5+ criteria ready for trading'}
          </div>

          {getSortedResults().length === 0 ? (
            <div className="text-center py-12 text-neutral-500">
              <Search size={48} className="mx-auto mb-4 opacity-50" />
              <div>
                {activeTab === 'momentum' 
                  ? 'Loading momentum stocks... Click the Momentum tab again to refresh.'
                  : 'No stocks found. Run a scan to see results.'}
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5">
                    <th className="text-left py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Symbol</th>
                    <th className="text-center py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Criteria</th>
                    {activeTab === 'momentum' && (
                      <>
                        <th className="text-center py-3 px-2 text-xs text-orange-400 uppercase tracking-wider font-mono">Higher Highs</th>
                        <th className="text-center py-3 px-2 text-xs text-orange-400 uppercase tracking-wider font-mono">Trend</th>
                      </>
                    )}
                    <th className="text-right py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Gap %</th>
                    <th className="text-right py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Price</th>
                    <th className="text-right py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Change %</th>
                    <th className="text-right py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Volume Ratio</th>
                    <th className="text-right py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Float</th>
                    <th className="text-center py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">News</th>
                    <th className="text-center py-3 px-2 text-xs text-neutral-500 uppercase tracking-wider font-mono">Detected</th>
                  </tr>
                </thead>
                <tbody>
                  {getSortedResults().map((stock, idx) => (
                    <tr 
                      key={idx} 
                      data-testid={`scan-result-${stock.symbol}`}
                      className="border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => {
                        // Navigate to Trade page with the stock symbol
                        // Store the selected stock in localStorage so Trade page can pick it up
                        localStorage.setItem('selectedTradeStock', stock.symbol);
                        navigate('/trading');
                      }}
                      title={`Click to trade ${stock.symbol}`}
                    >
                      <td className="py-3 px-2 font-mono font-bold text-white">{stock.symbol}</td>
                      <td className="py-3 px-2 text-center">
                        {stock.criteria_count !== undefined ? (
                          <div className="flex items-center justify-center gap-1">
                            <span className={`font-mono text-xs font-bold ${
                              stock.criteria_count === 5 ? 'text-[#00E599]' : 
                              stock.criteria_count >= 3 ? 'text-[#FFB800]' : 
                              'text-neutral-500'
                            }`}>
                              {stock.criteria_count}/5
                            </span>
                            {stock.ready_to_trade && (
                              <span className="text-[#00E599] text-sm animate-pulse" title="All criteria met - Ready to trade">✓</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-neutral-700">-</span>
                        )}
                      </td>
                      {/* Momentum columns - only show on Momentum tab */}
                      {activeTab === 'momentum' && (
                        <>
                          <td className="py-3 px-2 text-center font-mono">
                            <span className="text-orange-400 font-bold">{stock.higher_highs || 0}</span>
                            <span className="text-neutral-500">/{stock.swing_highs || 0}</span>
                          </td>
                          <td className={`py-3 px-2 text-center font-mono font-bold ${
                            (stock.trend_pct || 0) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
                          }`}>
                            {(stock.trend_pct || 0) >= 0 ? '+' : ''}{(stock.trend_pct || 0).toFixed(1)}%
                          </td>
                        </>
                      )}
                      <td className={`py-3 px-2 text-right font-mono font-bold ${
                        (stock.gap_pct || 0) >= 10 ? 'text-[#00E599]' : 
                        (stock.gap_pct || 0) >= 5 ? 'text-[#FFB800]' : 
                        'text-neutral-400'
                      }`}>
                        {stock.gap_pct >= 0 ? '+' : ''}{(stock.gap_pct || stock.pct_change || 0).toFixed(2)}%
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-white">${stock.current_price?.toFixed(2) || '0.00'}</td>
                      <td className={`py-3 px-2 text-right font-mono ${
                        (stock.pct_change || 0) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
                      }`}>
                        {(stock.pct_change || 0) >= 0 ? '+' : ''}{(stock.pct_change || 0).toFixed(2)}%
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-[#2E5CFF]">
                        {(stock.volume_ratio || 0).toFixed(2)}x
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-neutral-400" data-testid={`float-shares-${stock.symbol}`}>
                        {stock.shares_outstanding ? `${(stock.shares_outstanding / 1000000).toFixed(1)}M` : 'N/A'}
                      </td>
                      <td className="py-3 px-2 text-center max-w-xs">
                        <button
                          onClick={async (e) => {
                            e.stopPropagation(); // Prevent row click navigation
                            setLoadingNews(true);
                            setNewsModalOpen(true);
                            try {
                              const response = await axios.get(`${API}/news/${stock.symbol}`);
                              setSelectedStockNews(response.data);
                            } catch (error) {
                              console.error('Failed to fetch news:', error);
                              setSelectedStockNews({ symbol: stock.symbol, has_news: false, articles: [] });
                            } finally {
                              setLoadingNews(false);
                            }
                          }}
                          className="hover:bg-white/5 px-2 py-1 rounded transition-colors w-full"
                        >
                          {stock.has_positive_news ? (
                            <div className="text-xs text-left flex items-center gap-1">
                              <Newspaper className="inline text-[#2E5CFF] flex-shrink-0" size={14} />
                              <span className="text-neutral-300">News</span>
                              {/* News Freshness Badge */}
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                                stock.news_freshness === 'breaking' 
                                  ? 'bg-red-500/20 text-red-400 animate-pulse' 
                                  : stock.news_freshness === 'warm'
                                    ? 'bg-orange-500/20 text-orange-400'
                                    : stock.news_freshness === 'cold'
                                      ? 'bg-blue-500/20 text-blue-400'
                                      : 'bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/40'
                              }`}>
                                {stock.news_freshness === 'breaking' ? '🔥 BREAKING' 
                                  : stock.news_freshness === 'warm' ? '🌡️ WARM'
                                  : stock.news_freshness === 'cold' ? '❄️ COLD'
                                  : '✓'}
                              </span>
                            </div>
                          ) : (
                            <span className="text-neutral-500 text-xs">Check News</span>
                          )}
                        </button>
                      </td>
                      <td className="py-3 px-2 text-center font-mono text-xs text-neutral-400">
                        {stock.first_detected ? (
                          <div title={new Date(stock.first_detected).toLocaleString('en-US', { timeZone: 'America/New_York' })}>
                            {new Date(stock.first_detected).toLocaleTimeString('en-US', {
                              timeZone: 'America/New_York',
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </div>
                        ) : (
                          <span className="text-neutral-700">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {demoMode && (
        <Card className="bg-yellow-500/10 border-yellow-500/30">
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0">
                <PlayCircle className="text-yellow-500" size={32} />
              </div>
              <div>
                <div className="text-sm font-bold text-yellow-500">Demo Mode Active</div>
                <div className="text-xs text-neutral-300 mt-1">
                  Using <strong>simulated market data</strong> instead of live Alpaca API. Great for testing the scanner without API calls or when markets are closed. 
                  Turn OFF for real trading with live data.
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardContent className="pt-6">
            <div className="text-center">
              <TrendingUp className="mx-auto mb-2 text-[#00E599]" size={32} />
              <div className="text-xs text-neutral-500 mb-1">Criteria 1</div>
              <div className="text-sm text-white font-mono">+10% Daily</div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardContent className="pt-6">
            <div className="text-center">
              <Volume2 className="mx-auto mb-2 text-[#2E5CFF]" size={32} />
              <div className="text-xs text-neutral-500 mb-1">Criteria 2</div>
              <div className="text-sm text-white font-mono">5x Volume</div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardContent className="pt-6">
            <div className="text-center">
              <DollarSign className="mx-auto mb-2 text-[#00E599]" size={32} />
              <div className="text-xs text-neutral-500 mb-1">Criteria 3</div>
              <div className="text-sm text-white font-mono">$2-$20</div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardContent className="pt-6">
            <div className="text-center">
              <Newspaper className="mx-auto mb-2 text-[#2E5CFF]" size={32} />
              <div className="text-xs text-neutral-500 mb-1">Criteria 4</div>
              <div className="text-sm text-white font-mono">Pos. News</div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardContent className="pt-6">
            <div className="text-center">
              <Users className="mx-auto mb-2 text-[#00E599]" size={32} />
              <div className="text-xs text-neutral-500 mb-1">Criteria 5</div>
              <div className="text-sm text-white font-mono">&lt;20M Float</div>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* News Modal */}
      {newsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={() => setNewsModalOpen(false)}>
          <div className="bg-[#0A0A0A] border border-white/10 rounded-lg max-w-3xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="p-6 border-b border-white/10 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Newspaper className="text-[#2E5CFF]" size={24} />
                  News for {selectedStockNews?.symbol}
                </h2>
                <p className="text-xs text-neutral-500 mt-1">Click headlines to read full articles</p>
              </div>
              <button 
                onClick={() => setNewsModalOpen(false)}
                className="text-neutral-500 hover:text-white text-2xl"
              >
                ×
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {loadingNews ? (
                <div className="text-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#00E599] mx-auto"></div>
                  <p className="text-neutral-500 mt-4">Loading news...</p>
                </div>
              ) : selectedStockNews?.has_news ? (
                <div className="space-y-4">
                  {selectedStockNews.articles.map((article, idx) => (
                    <a
                      key={idx}
                      href={article.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block p-4 bg-[#121212] border border-white/5 rounded-lg hover:border-[#00E599]/30 hover:bg-[#121212]/80 transition-all group"
                    >
                      <div className="flex items-start gap-3">
                        <Newspaper className="text-[#2E5CFF] flex-shrink-0 mt-1 group-hover:text-[#00E599] transition-colors" size={20} />
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <h3 className="text-white text-sm font-medium group-hover:text-[#00E599] transition-colors flex-1">
                              {article.title}
                            </h3>
                            {article.sentiment === 'strong_catalyst' ? (
                              <span className="px-2 py-1 rounded text-xs font-bold bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/40 whitespace-nowrap">
                                ⭐ Score: {article.score || 10}
                              </span>
                            ) : (
                              <span className="px-2 py-1 rounded text-xs font-bold bg-blue-500/20 text-blue-400 border border-blue-500/40 whitespace-nowrap">
                                📈 Score: {article.score || 5}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-neutral-500 mb-2">
                            <span>{article.source}</span>
                            {article.pubDate && (
                              <>
                                <span>•</span>
                                <span>{new Date(article.pubDate).toLocaleString('en-US', {
                                  timeZone: 'America/New_York',
                                  month: 'short',
                                  day: 'numeric',
                                  hour: 'numeric',
                                  minute: '2-digit'
                                })}</span>
                              </>
                            )}
                          </div>
                          {article.catalysts && article.catalysts.length > 0 && (
                            <div className="flex items-center gap-1 flex-wrap">
                              <span className="text-[10px] text-neutral-600">Catalysts:</span>
                              {article.catalysts.map((catalyst, i) => (
                                <span key={i} className="px-1.5 py-0.5 bg-[#00E599]/10 text-[#00E599] rounded text-[10px] border border-[#00E599]/20">
                                  {catalyst}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <svg className="w-4 h-4 text-neutral-500 group-hover:text-[#00E599] transition-colors flex-shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                      </div>
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8">
                  <Newspaper className="mx-auto mb-4 text-neutral-700" size={48} />
                  <p className="text-neutral-500">No recent news found for {selectedStockNews?.symbol}</p>
                  <p className="text-neutral-600 text-xs mt-2">Try again later or check financial news websites</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}