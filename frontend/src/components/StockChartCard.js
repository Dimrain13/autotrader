import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TrendingUp, X, Newspaper } from "lucide-react";
import { useState, useEffect } from "react";
import CandlestickChart from "./CandlestickChart";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

export default function StockChartCard({ stock, symbol, currentPrice, pctChange, data, position, entry, stopLoss, profitTarget, trailingStop, psychTarget, partialSold, stopLossPct, takeProfitPct, trailingStopPct, stopType, onRemove, onTrade }) {
  // Create levels object from individual props for backward compatibility
  const levels = entry ? { entry, stopLoss, profitTarget, trailingStop, psychTarget } : null;
  
  // Use override prices if provided, otherwise fall back to stock props
  const displayPrice = currentPrice !== undefined ? currentPrice : stock.current_price;
  const displayPctChange = pctChange !== undefined ? pctChange : stock.pct_change;
  const [timeframe, setTimeframe] = useState('1Min');
  const [newsData, setNewsData] = useState(null);
  const [loadingNews, setLoadingNews] = useState(false);
  
  // Select bars based on timeframe (1Min, 5Min, or Daily)
  const bars = timeframe === '1Min' 
    ? data.bars1Min 
    : timeframe === '1Day' 
      ? data.barsDaily 
      : data.bars5Min;
  
  // Fetch news when component mounts
  useEffect(() => {
    const fetchNews = async () => {
      setLoadingNews(true);
      try {
        const response = await axios.get(`${API}/api/news/${stock.symbol}`);
        setNewsData(response.data);
      } catch (error) {
        console.error('Failed to fetch news:', error);
        setNewsData({ symbol: stock.symbol, has_news: false, articles: [] });
      } finally {
        setLoadingNews(false);
      }
    };
    
    fetchNews();
  }, [stock.symbol]);

  return (
    <Card className="bg-[#0A0A0A] border-white/5">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <span className="font-mono">{stock.symbol}</span>
            {/* Timeframe Selector */}
            <div className="flex gap-1">
              <button
                onClick={() => setTimeframe('1Min')}
                className={`px-2 py-0.5 text-[10px] font-mono rounded-sm transition-colors ${
                  timeframe === '1Min'
                    ? 'bg-[#2E5CFF] text-white'
                    : 'bg-[#121212] text-neutral-500 hover:bg-[#1a1a1a]'
                }`}
              >
                1M
              </button>
              <button
                onClick={() => setTimeframe('5Min')}
                className={`px-2 py-0.5 text-[10px] font-mono rounded-sm transition-colors ${
                  timeframe === '5Min'
                    ? 'bg-[#2E5CFF] text-white'
                    : 'bg-[#121212] text-neutral-500 hover:bg-[#1a1a1a]'
                }`}
              >
                5M
              </button>
              <button
                onClick={() => setTimeframe('1Day')}
                className={`px-2 py-0.5 text-[10px] font-mono rounded-sm transition-colors ${
                  timeframe === '1Day'
                    ? 'bg-[#2E5CFF] text-white'
                    : 'bg-[#121212] text-neutral-500 hover:bg-[#1a1a1a]'
                }`}
              >
                1D
              </button>
            </div>
            {position && (
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${partialSold ? 'bg-[#FFB800]/20 text-[#FFB800] border-[#FFB800]/40' : 'bg-[#00E599]/20 text-[#00E599] border-[#00E599]/30'}`}>
                {partialSold ? 'RUNNER' : 'OPEN'}
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <div className="text-xs text-neutral-500">
              <span className="text-white font-mono">${displayPrice.toFixed(2)}</span>
              <span className="ml-2 text-[#00E599]">+{displayPctChange.toFixed(1)}%</span>
            </div>
            <Button
              onClick={onRemove}
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0 hover:bg-white/10"
            >
              <X size={14} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Chart Section - Full Width */}
          <div>
            {/* Warning if real-time price differs significantly from chart data */}
            {(() => {
              const lastHistoricalBar = bars?.filter(b => !b.realtime).slice(-1)[0];
              const lastHistoricalPrice = lastHistoricalBar?.close || 0;
              const priceDiff = lastHistoricalPrice > 0 ? Math.abs((displayPrice - lastHistoricalPrice) / lastHistoricalPrice) * 100 : 0;
              if (priceDiff > 10 && lastHistoricalPrice > 0) {
                return (
                  <div className="mb-2 p-2 bg-yellow-500/10 border border-yellow-500/30 rounded text-xs text-yellow-400">
                    ⚠️ Chart data delayed (~15-20 min). Last bar: ${lastHistoricalPrice.toFixed(2)} | Current: ${displayPrice.toFixed(2)} ({priceDiff > 0 ? '+' : ''}{((displayPrice - lastHistoricalPrice) / lastHistoricalPrice * 100).toFixed(1)}%)
                  </div>
                );
              }
              return null;
            })()}
            {!bars || bars.length === 0 ? (
              <div className="h-[400px] flex items-center justify-center border border-white/5 rounded-sm bg-[#121212]">
                <div className="text-center text-neutral-500">
                  <div className="text-lg font-semibold text-yellow-500">⚠️ No Historical Data</div>
                  <div className="text-sm mt-2">Real-time chart data unavailable for {stock.symbol}</div>
                  <div className="text-xs mt-1 text-neutral-600">Free data tier limitation</div>
                </div>
              </div>
            ) : bars.length === 1 && bars[0]?.realtime ? (
              <div className="h-[400px] flex items-center justify-center border border-white/5 rounded-sm bg-[#121212]">
                <div className="text-center">
                  <div className="text-lg font-semibold text-yellow-500">⚠️ Real-Time Price Only</div>
                  <div className="text-2xl font-bold text-white mt-2">${bars[0].close?.toFixed(2)}</div>
                  <div className="text-sm mt-2 text-neutral-500">No historical chart data available for {stock.symbol}</div>
                  <div className="text-xs mt-1 text-neutral-600">Only current price shown</div>
                </div>
              </div>
            ) : (
              <CandlestickChart 
                data={bars} 
                height={400} 
                sma20={data.sma20}
                sma50={data.sma50}
                vwap={data.vwap}
                levels={levels}
              />
            )}
            
            {/* Indicators Row 1 */}
            <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">SMA20</div>
                <div className={`font-mono ${displayPrice > (data.sma20 || 0) ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {data.sma20 ? `$${data.sma20.toFixed(2)}` : '-'}
                </div>
              </div>
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">SMA50</div>
                <div className={`font-mono ${displayPrice > (data.sma50 || 0) ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {data.sma50 ? `$${data.sma50.toFixed(2)}` : '-'}
                </div>
              </div>
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">VWAP</div>
                <div className={`font-mono ${displayPrice > (data.vwap || 0) ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                  {data.vwap ? `$${data.vwap.toFixed(2)}` : '-'}
                </div>
              </div>
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">RSI(14)</div>
                <div className={`font-mono ${
                  data.rsi > 70 ? 'text-[#FF1A40]' : 
                  data.rsi < 30 ? 'text-[#00E599]' : 
                  'text-white'
                }`}>
                  {data.rsi ? data.rsi.toFixed(1) : '-'}
                </div>
              </div>
            </div>
            
            {/* Indicators Row 2 */}
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">Volume</div>
                <div className="font-mono text-[#2E5CFF]">{stock.volume_ratio.toFixed(1)}x</div>
              </div>
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">Bull Flag</div>
                <div className={`font-mono ${stock.has_bull_flag ? 'text-[#00E599]' : 'text-neutral-500'}`}>
                  {stock.has_bull_flag ? '✓' : '-'}
                </div>
              </div>
              <div className="p-2 bg-[#121212] border border-white/5 rounded-sm">
                <div className="text-neutral-500">Float</div>
                <div className="font-mono text-neutral-400">
                  {stock.float_shares ? `${(stock.float_shares / 1000000).toFixed(1)}M` : '-'}
                </div>
              </div>
            </div>
            
            {/* Trade Levels */}
        {levels && (
          <div className="mt-3 p-2 bg-[#121212] border border-white/5 rounded-sm text-xs">
            <div className="grid grid-cols-3 gap-2">
              <div>
                <div className="text-neutral-500">Entry</div>
                <div className="font-mono text-white">${levels.entry.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[#FF1A40]">
                  {levels.trailingStop && levels.trailingStop !== levels.stopLoss ? 'Stop (live trail)' : 'Stop (structural)'}
                </div>
                <div className="font-mono text-[#FF1A40]">
                  ${(levels.trailingStop || levels.stopLoss).toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-[#00E599]">Target</div>
                <div className="font-mono text-[#00E599]">${levels.profitTarget.toFixed(2)}</div>
              </div>
            </div>
            {levels.psychTarget && !partialSold && (
              <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between">
                <span className="text-neutral-500">1st Target (partial)</span>
                <span className="font-mono text-[#00E599]">${levels.psychTarget.toFixed(2)}</span>
              </div>
            )}
            {partialSold && (
              <div className="mt-2 pt-2 border-t border-white/5 flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#FFB800]/20 text-[#FFB800] border border-[#FFB800]/40 shrink-0">RUNNER</span>
                <span className="text-neutral-400">1st target hit — holding to final target @ ${levels.profitTarget.toFixed(2)}</span>
              </div>
            )}
          </div>
        )}
            
            {/* Quick Trade Button */}
            {!position && (
              <Button
                onClick={() => onTrade(stock.symbol)}
                className="w-full mt-3 bg-[#00E599] text-black hover:bg-[#00CC88] font-bold text-xs uppercase"
              >
                Quick Buy
              </Button>
            )}
            {position && (
              <div className="mt-3 p-2 bg-[#00E599]/10 border border-[#00E599]/30 rounded-sm">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-neutral-400">P&L:</span>
                  <span className={`font-mono font-bold ${position.unrealized_pl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                    {position.unrealized_pl >= 0 ? '+' : ''}${position.unrealized_pl.toFixed(2)} ({position.unrealized_plpc.toFixed(2)}%)
                  </span>
                </div>
              </div>
            )}
          </div>
          
          {/* News Feed - Below Chart */}
          <div className="border-t border-white/5 pt-4">
            <div className="flex items-center gap-2 mb-3">
              <Newspaper className="text-[#2E5CFF]" size={16} />
              <h3 className="text-xs font-bold text-neutral-400 uppercase">News Feed</h3>
            </div>
            
            {loadingNews ? (
              <div className="text-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[#00E599] mx-auto"></div>
                <p className="text-neutral-500 text-xs mt-2">Loading news...</p>
              </div>
            ) : newsData?.has_news ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-[200px] overflow-y-auto pr-2">
                {newsData.articles.map((article, idx) => (
                  <a
                    key={idx}
                    href={article.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block p-3 bg-[#121212] border border-white/5 rounded-lg hover:border-[#00E599]/30 hover:bg-[#121212]/80 transition-all group"
                  >
                    <div className="flex items-start gap-2">
                      <Newspaper className="text-[#2E5CFF] flex-shrink-0 mt-0.5 group-hover:text-[#00E599] transition-colors" size={14} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start gap-2 mb-1">
                          <h4 className="text-white text-xs font-medium group-hover:text-[#00E599] transition-colors line-clamp-2 flex-1">
                            {article.title}
                          </h4>
                          {article.sentiment === 'strong_catalyst' ? (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/40 whitespace-nowrap">
                              ⭐{article.score || 10}
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-400 border border-blue-500/40 whitespace-nowrap">
                              📈{article.score || 5}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-neutral-500 mb-1">
                          <span className="truncate">{article.source}</span>
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
                          <div className="flex items-center gap-1 flex-wrap mt-1">
                            {article.catalysts.map((catalyst, i) => (
                              <span key={i} className="px-1 py-0.5 bg-[#00E599]/10 text-[#00E599] rounded text-[9px] border border-[#00E599]/20">
                                {catalyst}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <svg className="w-3 h-3 text-neutral-500 group-hover:text-[#00E599] transition-colors flex-shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 border border-white/5 rounded-lg bg-[#121212]">
                <Newspaper className="mx-auto mb-2 text-neutral-700" size={32} />
                <p className="text-neutral-500 text-xs">No recent positive news</p>
                <p className="text-neutral-600 text-[10px] mt-1">Check Scanner for updates</p>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
