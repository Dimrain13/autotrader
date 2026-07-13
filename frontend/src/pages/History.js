import { useState, useEffect, Fragment } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Activity, DollarSign, Target, AlertCircle, Newspaper, ChevronDown, ChevronRight } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function History() {
  const [trades, setTrades] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tradeNews, setTradeNews] = useState({}); // {symbol: news_data}
  const [account, setAccount] = useState(null);
  const [expandedDays, setExpandedDays] = useState({}); // {dateKey: boolean}

  useEffect(() => {
    fetchTradeHistory();
    fetchAnalytics();
    fetchAccount();
  }, []);

  const fetchAccount = async () => {
    try {
      const response = await axios.get(`${API}/account`, { timeout: 10000 });
      setAccount(response.data);
    } catch (error) {
      console.error('Failed to fetch account:', error);
    }
  };

  const fetchTradeHistory = async () => {
    try {
      const response = await axios.get(`${API}/trade-history?limit=100`, { timeout: 10000 });
      setTrades(response.data.trades || []);
    } catch (error) {
      console.error('Failed to fetch trade history:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchAnalytics = async () => {
    try {
      const response = await axios.get(`${API}/trade-history/analytics`, { timeout: 10000 });
      setAnalytics(response.data);
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
      // Set default analytics when API fails
      setAnalytics({
        total_trades: 0,
        winners: 0,
        losers: 0,
        win_rate: 0,
        total_pnl: 0,
        avg_win: 0,
        avg_loss: 0,
        largest_win: 0,
        largest_loss: 0,
        profit_factor: 0,
        best_stock: 'N/A',
        worst_stock: 'N/A',
        expectancy: 0
      });
    }
  };

  // Fetch news for traded symbols
  const fetchNewsForTrades = async (tradeList) => {
    const uniqueSymbols = [...new Set(tradeList.map(t => t.symbol))];
    const newsData = {};
    
    await Promise.all(uniqueSymbols.slice(0, 20).map(async (symbol) => {
      try {
        const response = await axios.get(`${API}/news/${symbol}`, { timeout: 5000 });
        newsData[symbol] = response.data;
      } catch (error) {
        newsData[symbol] = { has_news: false, articles: [] };
      }
    }));
    
    setTradeNews(newsData);
  };

  // Fetch news when trades load
  useEffect(() => {
    if (trades.length > 0) {
      fetchNewsForTrades(trades);
    }
  }, [trades]);

  // Calculate risk/reward ratios
  const getRiskRewardRatio = () => {
    if (!analytics) return { avgRatio: 0, largestRatio: 0 };
    const avgLoss = Math.abs(analytics.avg_loss || 1);
    const largestLoss = Math.abs(analytics.largest_loss || 1);
    return {
      avgRatio: avgLoss > 0 ? (analytics.avg_win / avgLoss).toFixed(2) : 'N/A',
      largestRatio: largestLoss > 0 ? (analytics.largest_win / largestLoss).toFixed(2) : 'N/A'
    };
  };

  // Calculate yearly performance
  const getYearlyPerformance = () => {
    const currentYear = new Date().getFullYear();
    const yearTrades = trades.filter(t => {
      const tradeYear = new Date(t.exit_time || t.entry_time).getFullYear();
      return tradeYear === currentYear;
    });
    
    const yearlyPnL = yearTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);
    const totalTradeSize = yearTrades.reduce((sum, t) => sum + ((t.entry_price || 0) * (t.shares || 0)), 0);
    
    // Calculate based on account size (starting capital estimate)
    const accountValue = account?.portfolio_value || 100000;
    // Estimate starting capital by subtracting total P&L from current value
    const startingCapital = accountValue - yearlyPnL;
    const yearlyPctOnAccount = startingCapital > 0 ? (yearlyPnL / startingCapital) * 100 : 0;
    
    // Calculate based on total capital deployed (trade size)
    const yearlyPctOnTrades = totalTradeSize > 0 ? (yearlyPnL / totalTradeSize) * 100 : 0;
    
    return {
      yearlyPnL,
      yearlyPctOnAccount: yearlyPctOnAccount.toFixed(2),
      yearlyPctOnTrades: yearlyPctOnTrades.toFixed(2),
      totalTradeSize,
      tradeCount: yearTrades.length,
      startingCapital: startingCapital.toFixed(0),
      currentYear
    };
  };

  // Calculate daily P&L breakdown
  // Uses US/Eastern calendar dates (not UTC or raw browser-local) since the
  // trading day itself is defined in ET - keeps "TODAY" and date grouping
  // consistent with when the market actually opened/closed for that session.
  const getETDateKey = (date) => date.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });

  const getDailyPerformance = () => {
    const dailyData = {};
    
    trades.forEach(trade => {
      const exitDate = trade.exit_time ? new Date(trade.exit_time).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        weekday: 'short',
        timeZone: 'America/New_York'
      }) : 'Unknown';
      const dateKey = trade.exit_time ? getETDateKey(new Date(trade.exit_time)) : 'unknown';
      
      if (!dailyData[dateKey]) {
        dailyData[dateKey] = {
          date: exitDate,
          dateKey,
          pnl: 0,
          trades: 0,
          winners: 0,
          losers: 0,
          volume: 0,
          tradeList: []  // Store individual trades for this day
        };
      }
      
      dailyData[dateKey].pnl += trade.pnl || 0;
      dailyData[dateKey].trades += 1;
      dailyData[dateKey].volume += (trade.entry_price || 0) * (trade.shares || 0);
      dailyData[dateKey].tradeList.push(trade);  // Add trade to the day's list
      if (trade.pnl >= 0) {
        dailyData[dateKey].winners += 1;
      } else {
        dailyData[dateKey].losers += 1;
      }
    });
    
    // Sort by date descending (most recent first)
    return Object.values(dailyData)
      .sort((a, b) => new Date(b.dateKey) - new Date(a.dateKey))
      .slice(0, 10); // Show last 10 days with trades
  };

  // Toggle expanded day
  const toggleDayExpanded = (dateKey) => {
    setExpandedDays(prev => ({
      ...prev,
      [dateKey]: !prev[dateKey]
    }));
  };

  if (loading) {
    return <div className="text-center text-white py-20">Loading trade history...</div>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white" style={{ fontFamily: 'Unbounded, sans-serif' }}>
          Trade History & Analytics
        </h1>
        <p className="text-neutral-400 text-sm mt-1">
          Review your trading performance and P&L
        </p>
      </div>

      {/* Analytics Cards */}
      {analytics && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Total P&L */}
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Total P&L</CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-mono font-bold ${analytics.total_pnl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                ${analytics.total_pnl?.toFixed(2) || '0.00'}
              </div>
              <div className="text-xs text-neutral-500 mt-1">
                {analytics.total_trades || 0} trades
              </div>
            </CardContent>
          </Card>

          {/* Win Rate */}
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Win Rate</CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-mono font-bold ${analytics.win_rate >= 50 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                {analytics.win_rate || 0}%
              </div>
              <div className="text-xs text-neutral-500 mt-1">
                {analytics.winners || 0}W / {analytics.losers || 0}L
              </div>
            </CardContent>
          </Card>

          {/* Profit Factor */}
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Profit Factor</CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-mono font-bold ${analytics.profit_factor >= 1.5 ? 'text-[#00E599]' : analytics.profit_factor >= 1 ? 'text-yellow-500' : 'text-[#FF1A40]'}`}>
                {analytics.profit_factor?.toFixed(2) || '0.00'}
              </div>
              <div className="text-xs text-neutral-500 mt-1">
                Gross P / Gross L
              </div>
            </CardContent>
          </Card>

          {/* Expectancy */}
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-neutral-500 uppercase tracking-wider font-mono">Expectancy</CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-mono font-bold ${analytics.expectancy >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                ${analytics.expectancy?.toFixed(2) || '0.00'}
              </div>
              <div className="text-xs text-neutral-500 mt-1">
                Avg per trade
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Yearly Performance Card */}
      {analytics && trades.length > 0 && (
        <Card className="bg-[#0A0A0A] border-white/5 border-l-4 border-l-blue-500">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Target className="w-4 h-4 text-blue-500" />
              {getYearlyPerformance().currentYear} Yearly Performance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Year P&L</div>
                <div className={`text-2xl font-mono font-bold ${getYearlyPerformance().yearlyPnL >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  ${getYearlyPerformance().yearlyPnL.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">% Return (Account)</div>
                <div className={`text-2xl font-mono font-bold ${parseFloat(getYearlyPerformance().yearlyPctOnAccount) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {getYearlyPerformance().yearlyPctOnAccount > 0 ? '+' : ''}{getYearlyPerformance().yearlyPctOnAccount}%
                </div>
                <div className="text-[10px] text-neutral-600">Based on ~${Number(getYearlyPerformance().startingCapital).toLocaleString()} capital</div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">% Return (Trades)</div>
                <div className={`text-2xl font-mono font-bold ${parseFloat(getYearlyPerformance().yearlyPctOnTrades) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {getYearlyPerformance().yearlyPctOnTrades > 0 ? '+' : ''}{getYearlyPerformance().yearlyPctOnTrades}%
                </div>
                <div className="text-[10px] text-neutral-600">P&L / Total Trade Size</div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Capital Deployed</div>
                <div className="text-2xl font-mono font-bold text-white">
                  ${getYearlyPerformance().totalTradeSize.toLocaleString(undefined, {maximumFractionDigits: 0})}
                </div>
                <div className="text-[10px] text-neutral-600">Total trade value</div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Trades This Year</div>
                <div className="text-2xl font-mono font-bold text-white">
                  {getYearlyPerformance().tradeCount}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Daily P&L Breakdown */}
      {trades.length > 0 && (
        <Card className="bg-[#0A0A0A] border-white/5 border-l-4 border-l-green-500">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Activity className="w-4 h-4 text-green-500" />
              Daily P&L Tracker
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-xs text-neutral-500 uppercase border-b border-white/10">
                    <th className="pb-2 pr-4">Date</th>
                    <th className="pb-2 pr-4 text-right">P&L</th>
                    <th className="pb-2 pr-4 text-center">Trades</th>
                    <th className="pb-2 pr-4 text-center">W/L</th>
                    <th className="pb-2 pr-4 text-right">Win Rate</th>
                    <th className="pb-2 text-right">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {getDailyPerformance().map((day, idx) => {
                    const isToday = day.dateKey === getETDateKey(new Date());
                    return (
                    <Fragment key={day.dateKey}>
                      <tr 
                        key={day.dateKey} 
                        className={`text-sm border-b border-white/5 ${isToday ? 'bg-white/5' : ''} cursor-pointer hover:bg-white/10 transition-colors`}
                        onClick={() => toggleDayExpanded(day.dateKey)}
                      >
                        <td className="py-3 pr-4">
                          <div className="flex items-center gap-2">
                            {expandedDays[day.dateKey] ? (
                              <ChevronDown className="w-4 h-4 text-neutral-400" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-neutral-400" />
                            )}
                            <span className={`font-mono ${isToday ? 'text-green-400 font-bold' : 'text-white'}`}>
                              {day.date}
                              {isToday && <span className="ml-2 text-[10px] bg-green-500/20 text-green-400 px-1 py-0.5 rounded">TODAY</span>}
                            </span>
                          </div>
                        </td>
                        <td className={`py-3 pr-4 text-right font-mono font-bold ${day.pnl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                          {day.pnl >= 0 ? '+' : ''}${day.pnl.toFixed(2)}
                        </td>
                        <td className="py-3 pr-4 text-center font-mono text-neutral-400">
                          {day.trades}
                        </td>
                        <td className="py-3 pr-4 text-center font-mono">
                          <span className="text-[#00E599]">{day.winners}W</span>
                          <span className="text-neutral-600 mx-1">/</span>
                          <span className="text-[#FF1A40]">{day.losers}L</span>
                        </td>
                        <td className={`py-3 pr-4 text-right font-mono ${day.trades > 0 ? ((day.winners / day.trades) * 100 >= 50 ? 'text-[#00E599]' : 'text-[#FF1A40]') : 'text-neutral-400'}`}>
                          {day.trades > 0 ? ((day.winners / day.trades) * 100).toFixed(0) : 0}%
                        </td>
                        <td className="py-3 text-right font-mono text-neutral-400">
                          ${day.volume.toLocaleString(undefined, {maximumFractionDigits: 0})}
                        </td>
                      </tr>
                      {/* Expanded trades for this day */}
                      {expandedDays[day.dateKey] && (
                        <tr key={`${day.dateKey}-expanded`}>
                          <td colSpan="6" className="bg-[#111] border-b border-white/10">
                            <div className="p-3">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-neutral-500 uppercase border-b border-white/5">
                                    <th className="pb-2 text-left">Symbol</th>
                                    <th className="pb-2 text-left">Entry</th>
                                    <th className="pb-2 text-left">Exit</th>
                                    <th className="pb-2 text-right">Shares</th>
                                    <th className="pb-2 text-right">P&L</th>
                                    <th className="pb-2 text-right">%</th>
                                    <th className="pb-2 text-left">Exit Reason</th>
                                    <th className="pb-2 text-left">Time</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {day.tradeList
                                    .sort((a, b) => new Date(b.exit_time || 0) - new Date(a.exit_time || 0))
                                    .map((trade, tIdx) => (
                                    <tr key={tIdx} className="border-b border-white/5 hover:bg-white/5">
                                      <td className="py-2 font-mono font-bold text-white">{trade.symbol}</td>
                                      <td className="py-2 font-mono text-neutral-400">${trade.entry_price?.toFixed(2)}</td>
                                      <td className="py-2 font-mono text-neutral-400">${trade.exit_price?.toFixed(2)}</td>
                                      <td className="py-2 text-right font-mono text-neutral-400">{trade.shares?.toLocaleString()}</td>
                                      <td className={`py-2 text-right font-mono font-bold ${trade.pnl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                                        {trade.pnl >= 0 ? '+' : ''}${trade.pnl?.toFixed(2)}
                                      </td>
                                      <td className={`py-2 text-right font-mono ${trade.pnl_pct >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                                        {trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct?.toFixed(2)}%
                                      </td>
                                      <td className="py-2">
                                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                                          trade.exit_reason === 'Take Profit' || trade.exit_reason === 'Partial Take Profit' 
                                            ? 'bg-green-500/20 text-green-400'
                                            : trade.exit_reason === 'Stop Loss'
                                              ? 'bg-red-500/20 text-red-400'
                                              : 'bg-neutral-500/20 text-neutral-400'
                                        }`}>
                                          {trade.exit_reason || 'Unknown'}
                                        </span>
                                      </td>
                                      <td className="py-2 text-neutral-500">
                                        {trade.exit_time ? new Date(trade.exit_time).toLocaleTimeString('en-US', {
                                          hour: '2-digit',
                                          minute: '2-digit'
                                        }) : '-'}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );})}
                </tbody>
                <tfoot>
                  <tr className="text-sm border-t border-white/20 bg-white/5">
                    <td className="py-3 pr-4 font-bold text-white">TOTAL</td>
                    <td className={`py-3 pr-4 text-right font-mono font-bold ${getDailyPerformance().reduce((sum, d) => sum + d.pnl, 0) >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                      {getDailyPerformance().reduce((sum, d) => sum + d.pnl, 0) >= 0 ? '+' : ''}${getDailyPerformance().reduce((sum, d) => sum + d.pnl, 0).toFixed(2)}
                    </td>
                    <td className="py-3 pr-4 text-center font-mono font-bold text-white">
                      {getDailyPerformance().reduce((sum, d) => sum + d.trades, 0)}
                    </td>
                    <td className="py-3 pr-4 text-center font-mono">
                      <span className="text-[#00E599]">{getDailyPerformance().reduce((sum, d) => sum + d.winners, 0)}W</span>
                      <span className="text-neutral-600 mx-1">/</span>
                      <span className="text-[#FF1A40]">{getDailyPerformance().reduce((sum, d) => sum + d.losers, 0)}L</span>
                    </td>
                    <td className="py-3 pr-4 text-right font-mono text-neutral-400">-</td>
                    <td className="py-3 text-right font-mono font-bold text-white">
                      ${getDailyPerformance().reduce((sum, d) => sum + d.volume, 0).toLocaleString(undefined, {maximumFractionDigits: 0})}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            {getDailyPerformance().length === 0 && (
              <div className="text-center py-4 text-neutral-500">
                No daily data available yet.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Additional Stats */}
      {analytics && (
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardHeader>
            <CardTitle className="text-sm font-bold">Performance Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Avg Win</div>
                <div className="text-lg font-mono font-bold text-[#00E599]">
                  ${analytics.avg_win?.toFixed(2) || '0.00'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Avg Loss</div>
                <div className="text-lg font-mono font-bold text-[#FF1A40]">
                  ${analytics.avg_loss?.toFixed(2) || '0.00'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Largest Win</div>
                <div className="text-lg font-mono font-bold text-[#00E599]">
                  ${analytics.largest_win?.toFixed(2) || '0.00'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Largest Loss</div>
                <div className="text-lg font-mono font-bold text-[#FF1A40]">
                  ${analytics.largest_loss?.toFixed(2) || '0.00'}
                </div>
              </div>
            </div>
            
            {/* Risk/Reward Ratios */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t border-white/10">
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Avg Risk/Reward</div>
                <div className={`text-lg font-mono font-bold ${parseFloat(getRiskRewardRatio().avgRatio) >= 1 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {getRiskRewardRatio().avgRatio}:1
                </div>
                <div className="text-[10px] text-neutral-600">Avg Win / Avg Loss</div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Best Risk/Reward</div>
                <div className={`text-lg font-mono font-bold ${parseFloat(getRiskRewardRatio().largestRatio) >= 1 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {getRiskRewardRatio().largestRatio}:1
                </div>
                <div className="text-[10px] text-neutral-600">Largest Win / Largest Loss</div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Best Stock</div>
                <div className="text-sm font-mono font-bold text-white">
                  {analytics.best_stock || 'N/A'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500 uppercase mb-1">Worst Stock</div>
                <div className="text-sm font-mono font-bold text-white">
                  {analytics.worst_stock || 'N/A'}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Trade History Table */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader>
          <CardTitle className="text-sm font-bold">Recent Trades</CardTitle>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <div className="text-center py-8 text-neutral-500">
              No trades recorded yet. Trades will appear here after positions are closed.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-xs text-neutral-500 uppercase border-b border-white/10">
                    <th className="pb-2">#</th>
                    <th className="pb-2">Symbol</th>
                    <th className="pb-2">Entry</th>
                    <th className="pb-2">Exit</th>
                    <th className="pb-2">Shares</th>
                    <th className="pb-2">P&L</th>
                    <th className="pb-2">%</th>
                    <th className="pb-2">Hold Time</th>
                    <th className="pb-2">Exit Reason</th>
                    <th className="pb-2">News Catalyst</th>
                    <th className="pb-2">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade, idx) => (
                    <tr key={trade.id || idx} className="text-sm border-b border-white/5 hover:bg-white/5">
                      <td className="py-3 text-neutral-500">#{trade.id}</td>
                      <td className="py-3">
                        <span className="font-mono font-bold text-white">{trade.symbol}</span>
                      </td>
                      <td className="py-3 font-mono text-white">${trade.entry_price?.toFixed(2)}</td>
                      <td className="py-3 font-mono text-white">${trade.exit_price?.toFixed(2)}</td>
                      <td className="py-3 font-mono text-neutral-400">{trade.shares}</td>
                      <td className={`py-3 font-mono font-bold ${trade.pnl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                        ${trade.pnl?.toFixed(2)}
                      </td>
                      <td className={`py-3 font-mono font-bold ${trade.pnl_pct >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                        {trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct?.toFixed(1)}%
                      </td>
                      <td className="py-3 text-neutral-400 text-xs">{trade.hold_time || 'N/A'}</td>
                      <td className="py-3 text-neutral-400 text-xs">{trade.exit_reason || 'Manual'}</td>
                      <td className="py-3 text-xs max-w-[200px]">
                        {tradeNews[trade.symbol]?.has_news && tradeNews[trade.symbol]?.articles?.length > 0 ? (
                          <a 
                            href={tradeNews[trade.symbol].articles[0].link || tradeNews[trade.symbol].articles[0].url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-400 hover:text-blue-300 truncate block"
                            title={tradeNews[trade.symbol].articles[0].title}
                          >
                            <Newspaper className="inline w-3 h-3 mr-1" />
                            {tradeNews[trade.symbol].articles[0].title?.substring(0, 40)}...
                          </a>
                        ) : (
                          <span className="text-neutral-600">No news</span>
                        )}
                      </td>
                      <td className="py-3 text-neutral-500 text-xs">
                        {trade.exit_time ? new Date(trade.exit_time).toLocaleDateString() : 'N/A'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
