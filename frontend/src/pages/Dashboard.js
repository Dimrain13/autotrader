import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, TrendingDown, DollarSign, Activity, Search } from "lucide-react";
import { scannerCache } from "../utils/scannerCache";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Dashboard({ account }) {
  const [positions, setPositions] = useState([]);
  const [recentOrders, setRecentOrders] = useState([]);
  const [scannerResults, setScannerResults] = useState([]);
  const [scannerLoading, setScannerLoading] = useState(true);

  useEffect(() => {
    // Load cached scanner results immediately
    const cached = scannerCache.get();
    if (cached && cached.data) {
      setScannerResults(cached.data);
      setScannerLoading(false);
    }
    
    fetchPositions();
    fetchRecentOrders();
    
    // Fetch fresh scanner results if cache is stale or missing
    if (!cached || !cached.isFresh) {
      fetchScannerResults();
    }
    
    const interval = setInterval(() => {
      fetchPositions();
      fetchRecentOrders();
      fetchScannerResults(); // Update scanner every 60s
    }, 60000); // 60 seconds
    
    return () => clearInterval(interval);
  }, []);

  const fetchScannerResults = async () => {
    try {
      const response = await axios.post(`${API}/scanner/scan`, {
        min_price: 2,
        max_price: 20,
        min_change: 10,
        min_volume_ratio: 5,
        max_float: 20000000
      });
      
      setScannerResults(response.data);
      scannerCache.set(response.data); // Cache results
      setScannerLoading(false);
    } catch (error) {
      console.error('Failed to fetch scanner results:', error);
      setScannerLoading(false);
    }
  };

  const fetchPositions = async () => {
    try {
      const response = await axios.get(`${API}/positions`);
      setPositions(response.data);
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    }
  };

  const fetchRecentOrders = async () => {
    try {
      const response = await axios.get(`${API}/orders?limit=5`);
      setRecentOrders(response.data);
    } catch (error) {
      console.error('Failed to fetch orders:', error);
    }
  };

  const totalPL = positions.reduce((sum, pos) => sum + pos.unrealized_pl, 0);
  const totalPLPercent = account?.portfolio_value 
    ? (totalPL / account.portfolio_value) * 100 
    : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="bg-[#0A0A0A] border-white/5 hover:border-white/10 transition-colors" data-testid="card-portfolio-value">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Portfolio Value</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-mono text-white">
              ${account?.portfolio_value?.toFixed(2) || '0.00'}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-[#0A0A0A] border-white/5 hover:border-white/10 transition-colors" data-testid="card-buying-power">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Buying Power</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-mono text-[#00E599]">
              ${account?.buying_power?.toFixed(2) || '0.00'}
            </div>
            <div className="text-[10px] text-neutral-500 mt-1">
              {account?.pattern_day_trader ? '4x Day Trading' : '2x Margin'}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-[#0A0A0A] border-white/5 hover:border-white/10 transition-colors" data-testid="card-unrealized-pl">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Unrealized P&L</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-mono ${
              totalPL >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
            }`}>
              {totalPL >= 0 ? <TrendingUp className="inline mr-2" size={24} /> : <TrendingDown className="inline mr-2" size={24} />}
              ${Math.abs(totalPL).toFixed(2)}
            </div>
            <div className={`text-sm font-mono mt-1 ${
              totalPL >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
            }`}>
              {totalPLPercent >= 0 ? '+' : ''}{totalPLPercent.toFixed(2)}%
            </div>
          </CardContent>
        </Card>

        <Card className="bg-[#0A0A0A] border-white/5 hover:border-white/10 transition-colors" data-testid="card-open-positions">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Open Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-mono text-white">
              <Activity className="inline mr-2" size={24} />
              {positions.length}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Scanner Results Summary */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader>
          <CardTitle className="text-sm font-bold flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Search size={18} />
              <span>Scanner Opportunities</span>
              {scannerLoading && (
                <span className="text-xs text-neutral-500 font-normal">(Loading...)</span>
              )}
              {!scannerLoading && scannerCache.getAge() !== null && (
                <span className="text-xs text-neutral-500 font-normal">
                  (Updated {scannerCache.getAge()}s ago)
                </span>
              )}
            </div>
            <div className="text-2xl font-mono text-[#00E599]">
              {scannerResults.length}
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            {/* 5/5 Criteria */}
            <div className="text-center">
              <div className="text-xs text-neutral-500 uppercase mb-1">5/5 Ready</div>
              <div className="text-2xl font-mono font-bold text-[#00E599]">
                {scannerResults.filter(s => s.criteria_count === 5).length}
              </div>
            </div>
            
            {/* 4/5 Criteria */}
            <div className="text-center">
              <div className="text-xs text-neutral-500 uppercase mb-1">4/5 Criteria</div>
              <div className="text-2xl font-mono font-bold text-yellow-500">
                {scannerResults.filter(s => s.criteria_count === 4).length}
              </div>
            </div>
            
            {/* Top Volume */}
            <div className="text-center">
              <div className="text-xs text-neutral-500 uppercase mb-1">Avg Volume</div>
              <div className="text-2xl font-mono font-bold text-white">
                {scannerResults.length > 0 
                  ? (scannerResults.reduce((sum, s) => sum + (s.volume_ratio || 0), 0) / scannerResults.length).toFixed(1)
                  : '0'}x
              </div>
            </div>
          </div>
          
          {/* Top 5 Stocks */}
          {scannerResults.length > 0 && (
            <div className="mt-4 pt-4 border-t border-white/10">
              <div className="text-xs text-neutral-500 uppercase mb-2">Top 5 Opportunities</div>
              <div className="space-y-2">
                {scannerResults
                  .sort((a, b) => {
                    const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
                    if (criteriaCompare !== 0) return criteriaCompare;
                    return (b.volume_ratio || 0) - (a.volume_ratio || 0);
                  })
                  .slice(0, 5)
                  .map((stock, idx) => (
                    <div key={idx} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-white">{stock.symbol}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          stock.criteria_count === 5 
                            ? 'bg-[#00E599]/20 text-[#00E599]' 
                            : 'bg-neutral-800 text-neutral-400'
                        }`}>
                          {stock.criteria_count}/5
                        </span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-[#00E599]">${stock.current_price?.toFixed(2)}</span>
                        <span className="text-neutral-500">{stock.volume_ratio?.toFixed(1)}x vol</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="bg-[#0A0A0A] border-white/5" data-testid="positions-card">
          <CardHeader>
            <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Active Positions</CardTitle>
          </CardHeader>
          <CardContent>
            {positions.length === 0 ? (
              <div className="text-center py-8 text-neutral-500">No open positions</div>
            ) : (
              <div className="space-y-2">
                {positions.map((pos, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 bg-[#121212] border border-white/5 rounded-sm hover:border-white/10 transition-colors" data-testid={`position-${pos.symbol}`}>
                    <div>
                      <div className="text-sm font-mono font-bold text-white">{pos.symbol}</div>
                      <div className="text-xs text-neutral-500">{pos.qty} shares @ ${pos.avg_entry_price.toFixed(2)}</div>
                    </div>
                    <div className="text-right">
                      <div className={`text-lg font-mono ${
                        pos.unrealized_pl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
                      }`}>
                        {pos.unrealized_pl >= 0 ? '+' : ''}${pos.unrealized_pl.toFixed(2)}
                      </div>
                      <div className={`text-xs font-mono ${
                        pos.unrealized_plpc >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'
                      }`}>
                        {pos.unrealized_plpc >= 0 ? '+' : ''}{pos.unrealized_plpc.toFixed(2)}%
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-[#0A0A0A] border-white/5" data-testid="recent-orders-card">
          <CardHeader>
            <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Recent Orders</CardTitle>
          </CardHeader>
          <CardContent>
            {recentOrders.length === 0 ? (
              <div className="text-center py-8 text-neutral-500">No recent orders</div>
            ) : (
              <div className="space-y-2">
                {recentOrders.map((order, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 bg-[#121212] border border-white/5 rounded-sm" data-testid={`order-${order.order_id}`}>
                    <div>
                      <div className="text-sm font-mono font-bold text-white">{order.symbol}</div>
                      <div className="text-xs text-neutral-500">
                        {order.side.toUpperCase()} {order.qty} shares
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-xs px-2 py-1 rounded-sm ${
                        order.status === 'filled' 
                          ? 'bg-[#00E599]/10 text-[#00E599] border border-[#00E599]/20' 
                          : order.status === 'pending_new'
                          ? 'bg-[#2E5CFF]/10 text-[#2E5CFF] border border-[#2E5CFF]/20'
                          : 'bg-neutral-800 text-neutral-400'
                      }`}>
                        {order.status.replace('_', ' ').toUpperCase()}
                      </div>
                      {order.filled_avg_price && (
                        <div className="text-xs font-mono text-neutral-500 mt-1">
                          @ ${order.filled_avg_price.toFixed(2)}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="account-leverage-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Account Leverage</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-2">Current Status</div>
              <div className="text-white font-mono mb-2">
                {account?.pattern_day_trader ? (
                  <span className="text-[#00E599]">✓ Pattern Day Trader</span>
                ) : (
                  <span className="text-yellow-500">Standard Margin Account</span>
                )}
              </div>
              <div className="text-xs text-neutral-400">
                {account?.pattern_day_trader 
                  ? 'You have 4x buying power for day trades (intraday)'
                  : 'You have 2x buying power (standard Reg T margin).'
                }
              </div>
            </div>
            <div className="p-4 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-2">Buying Power Breakdown</div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-neutral-400">Portfolio Value</span>
                  <span className="font-mono text-white">${account?.portfolio_value?.toFixed(2) || '0.00'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Multiplier</span>
                  <span className="font-mono text-[#2E5CFF]">{account?.pattern_day_trader ? '4x' : '2x'}</span>
                </div>
                <div className="flex justify-between border-t border-white/10 pt-1">
                  <span className="text-neutral-400">Total Buying Power</span>
                  <span className="font-mono text-[#00E599]">${account?.buying_power?.toFixed(2) || '0.00'}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-4 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-sm text-xs text-yellow-500" data-testid="pdt-rule-note">
            <strong>Note:</strong> Paper trading simulates the margin tier your broker actually reports (currently {account?.pattern_day_trader ? '4x leverage, PDT status' : '2x margin leverage'}). The SEC/FINRA eliminated the classic "$25k minimum / 3 day trades per 5 days" Pattern Day Trader rule in 2026, replacing it with real-time intraday margin monitoring (broker rollout phases in through Oct 2027) — so this restriction may no longer apply once your broker migrates.
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[#0A0A0A] border-white/5" data-testid="strategy-info-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Trading Strategy</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4 text-sm">
            <div className="p-3 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-1">Criteria 1</div>
              <div className="text-white font-mono">Up 10%+ Today</div>
            </div>
            <div className="p-3 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-1">Criteria 2</div>
              <div className="text-white font-mono">5x Rel. Volume</div>
            </div>
            <div className="p-3 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-1">Criteria 3</div>
              <div className="text-white font-mono">$2-$20 Range</div>
            </div>
            <div className="p-3 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-1">Criteria 4</div>
              <div className="text-white font-mono">Positive News</div>
            </div>
            <div className="p-3 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-1">Criteria 5</div>
              <div className="text-white font-mono">&lt;20M Float</div>
            </div>
          </div>
          <div className="mt-4 p-4 bg-black/60 backdrop-blur-xl border border-white/10 rounded-sm">
            <div className="text-xs text-neutral-500 mb-2">Entry Signal</div>
            <div className="text-white">Bull flag breakout - First candle making new high after consolidation</div>
            <div className="text-xs text-neutral-500 mt-3 mb-2">Profit Target</div>
            <div className="text-[#00E599] font-mono">2:1 Risk/Reward Ratio</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}