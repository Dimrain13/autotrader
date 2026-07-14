import { useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { DollarSign, TrendingUp, TrendingDown, Activity, Search, Loader2 } from "lucide-react";
import StockChartCard from "@/components/StockChartCard";
import { scannerCache } from "../utils/scannerCache";
import { useMarketDataSocket } from "../hooks/useMarketDataSocket";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Cache for entry conditions to avoid repeated API calls
const entryConditionsCache = {};

export default function Trading() {
  const [demoMode, setDemoMode] = useState(() => {
    const saved = localStorage.getItem('demoMode');
    return saved === 'true';
  });
  const [entryConditions, setEntryConditions] = useState({}); // {symbol: conditionsData}
  const [selectedStocks, setSelectedStocks] = useState(new Set()); // Track multiple selections
  const [scannerResults, setScannerResults] = useState([]);
  const [momentumStocks, setMomentumStocks] = useState([]); // Stocks building momentum (higher highs)
  const [scannerTab, setScannerTab] = useState('all'); // 'all', 'gappers', 'gainers', 'volume', 'momentum', 'news'
  const [positions, setPositions] = useState([]);
  const [qty, setQty] = useState(1);
  const [side, setSide] = useState('buy');
  const [placing, setPlacing] = useState(false);
  const [buyingAll, setBuyingAll] = useState(false);
  const [sellingAll, setSellingAll] = useState(false);
  const [lastAction, setLastAction] = useState(null); // {type: 'buy'/'sell', symbol: string, success: bool}
  const [marketStatus, setMarketStatus] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [showAutoTraderSettings, setShowAutoTraderSettings] = useState(false);

  // Tracks which symbols have already had their full (2-day) chart history
  // fetched, so opening N charts issues exactly N initial fetches - not one
  // per chart on every unrelated scannerResults/momentumStocks/positions
  // poll tick. Cleared for a symbol when its chart is closed, so reopening
  // it later fetches fresh data again.
  const loadedChartsRef = useRef(new Set());

  // Mirror the latest selectedStocks/positions/scannerResults/momentumStocks
  // in refs so the 15s chartUpdateInterval (created once, deps=[demoMode,
  // criteriaFilter]) always reads CURRENT values instead of a stale closure
  // captured at mount time - without needing to recreate the interval (and
  // the other scanner/positions intervals alongside it) on every selection.
  const selectedStocksRef = useRef(selectedStocks);
  const positionsRef = useRef(positions);
  const scannerResultsRef = useRef(scannerResults);
  const momentumStocksRef = useRef(momentumStocks);
  useEffect(() => {
    selectedStocksRef.current = selectedStocks;
    positionsRef.current = positions;
    scannerResultsRef.current = scannerResults;
    momentumStocksRef.current = momentumStocks;
  }, [selectedStocks, positions, scannerResults, momentumStocks]);
  
  // Auto-Trader Entry Condition Settings
  const [autoTraderSettings, setAutoTraderSettings] = useState({
    // Entry conditions
    pullback_min_pct: 1.0,
    pullback_max_pct: 3.0,
    pullback_lookback_bars: 10,
    require_macd_crossover: true,
    require_sma_crossover: true,
    require_bull_flag: false,
    sma_period: 20,
    trading_start_hour: 7,
    trading_end_hour: 11,
    // Trade management
    profit_target_pct: 2.0,
    stop_loss_pct: 1.0,
    max_positions: 5,
    position_size_pct: 10.0,
    daily_max_loss_pct: 5.0
  });
  
  const [dollarAmountPerStock, setDollarAmountPerStock] = useState(() => {
    const saved = localStorage.getItem('dollarAmountPerStock');
    return saved ? parseInt(saved) : 2000;
  });
  const [stopLossPct, setStopLossPct] = useState(() => {
    const saved = localStorage.getItem('stopLossPct');
    // Migrate old defaults (5%) to new defaults (1%)
    if (saved === '5' || saved === '5.0') {
      localStorage.setItem('stopLossPct', '1');
      return 1.0;
    }
    return saved ? parseFloat(saved) : 1.0;  // 1% stop loss (Warrior Trading quick scalp)
  });
  const [takeProfitPct, setTakeProfitPct] = useState(() => {
    const saved = localStorage.getItem('takeProfitPct');
    // Migrate old defaults (10%) to new defaults (2%)
    if (saved === '10' || saved === '10.0') {
      localStorage.setItem('takeProfitPct', '2');
      return 2.0;
    }
    return saved ? parseFloat(saved) : 2.0;  // 2% take profit (Warrior Trading quick scalp)
  });
  const [criteriaFilter, setCriteriaFilter] = useState(() => {
    const saved = localStorage.getItem('criteriaFilter');
    return saved || 'all'; // 'all', '3+', '4+', '5'
  });
  const [sortBy, setSortBy] = useState(() => {
    const saved = localStorage.getItem('sortBy');
    return saved || 'criteria'; // 'criteria', 'volume', 'change', 'price', 'news'
  });
  const [stopType, setStopType] = useState(() => {
    const saved = localStorage.getItem('stopType');
    return saved || 'fixed'; // 'fixed' or 'trailing'
  });
  const [trailingStopPct, setTrailingStopPct] = useState(() => {
    const saved = localStorage.getItem('trailingStopPct');
    // Migrate old default (5%) to new default (1%)
    if (saved === '5' || saved === '5.0') {
      localStorage.setItem('trailingStopPct', '1');
      return 1.0;
    }
    return saved ? parseFloat(saved) : 1.0;  // 1% trailing stop (matches fixed stop)
  });
  const [partialSellPct, setPartialSellPct] = useState(() => {
    const saved = localStorage.getItem('partialSellPct');
    return saved ? parseFloat(saved) : 50.0;  // Sell 50% at profit target
  });
  const [partialSellTrigger, setPartialSellTrigger] = useState(() => {
    const saved = localStorage.getItem('partialSellTrigger');
    // Default: 2% profit target for partial sell
    if (!saved || saved === '1' || saved === '1.0' || saved === '10' || saved === '10.0') {
      localStorage.setItem('partialSellTrigger', '2');
      return 2.0;
    }
    return parseFloat(saved);
  });
  const [moveToBreakeven, setMoveToBreakeven] = useState(() => {
    const saved = localStorage.getItem('moveToBreakeven');
    // Default: TRUE - move stop to breakeven after partial sell
    if (saved === null || saved === undefined) {
      localStorage.setItem('moveToBreakeven', 'true');
      return true;
    }
    return saved === 'true';
  });
  const [stockData, setStockData] = useState({}); // {symbol: {bars, quote, sma20}}
  const [stockNews, setStockNews] = useState({}); // {symbol: {has_news, articles, last_updated}}
  const [loading, setLoading] = useState(false); // Start with false for instant display

  // Real-time Alpaca WebSocket market data (replaces REST polling for price
  // ticks - REST's free-tier data is ~15min delayed, this is genuinely live).
  const { quotes: liveQuotes, connected: wsConnected, subscribe: wsSubscribe } = useMarketDataSocket();

  // Keep the live stream subscribed to every symbol currently visible on
  // screen (selected charts + open positions + top scanner candidates).
  useEffect(() => {
    const symbols = new Set(selectedStocks);
    positions.forEach(p => symbols.add(p.symbol));
    scannerResults.slice(0, 20).forEach(s => symbols.add(s.symbol));
    momentumStocks.slice(0, 10).forEach(s => symbols.add(s.symbol));
    if (symbols.size > 0) wsSubscribe(Array.from(symbols));
  }, [selectedStocks, positions, scannerResults, momentumStocks, wsSubscribe]);

  // Merge live WS quote ticks straight into stockData - instant bid/ask/price
  // updates for any symbol with a chart open, between the 15s REST poll ticks.
  useEffect(() => {
    setStockData(prev => {
      let changed = false;
      const next = { ...prev };
      Object.keys(prev).forEach(symbol => {
        const q = liveQuotes[symbol];
        if (!q) return;
        next[symbol] = {
          ...next[symbol],
          quote: { ...next[symbol].quote, ...q },
          bid: q.bid_price ?? next[symbol].bid,
          ask: q.ask_price ?? next[symbol].ask,
          spread_pct: (q.bid_price > 0 && q.ask_price > 0)
            ? ((q.ask_price - q.bid_price) / ((q.bid_price + q.ask_price) / 2)) * 100
            : next[symbol].spread_pct
        };
        changed = true;
      });
      return changed ? next : prev;
    });
  }, [liveQuotes]);

  // Fetch market status
  useEffect(() => {
    const fetchMarketStatus = async () => {
      try {
        const response = await axios.get(`${API}/market/status`);
        setMarketStatus(response.data);
      } catch (error) {
        console.error('Failed to fetch market status:', error);
      }
    };
    
    fetchMarketStatus();
    // Update market status every minute
    const interval = setInterval(fetchMarketStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  // Track stock to select from Scanner page
  const [pendingSelection, setPendingSelection] = useState(() => {
    const selectedFromScanner = localStorage.getItem('selectedTradeStock');
    if (selectedFromScanner) {
      localStorage.removeItem('selectedTradeStock');
      return selectedFromScanner;
    }
    return null;
  });

  // Apply pending selection once scanner results are loaded
  useEffect(() => {
    if (pendingSelection && scannerResults.length > 0) {
      setSelectedStocks(new Set([pendingSelection]));
      toast.success(`Opened ${pendingSelection} from Scanner`);
      setPendingSelection(null);
    }
  }, [pendingSelection, scannerResults]);

  // Fetch auto-trader settings on mount
  useEffect(() => {
    const fetchAutoTraderSettings = async () => {
      try {
        const response = await axios.get(`${API}/auto-trader/status`);
        // Merge entry_conditions and strategy settings
        const settings = {
          ...(response.data.entry_conditions || {}),
          profit_target_pct: response.data.strategy?.profit_target_pct || 2.0,
          stop_loss_pct: response.data.strategy?.stop_loss_pct || 1.0,
          max_positions: response.data.max_positions || 5,
          position_size_pct: response.data.strategy?.position_size_pct || 10.0,
          daily_max_loss_pct: response.data.strategy?.daily_max_loss_pct || 5.0
        };
        setAutoTraderSettings(settings);
      } catch (error) {
        console.error('Failed to fetch auto-trader settings:', error);
      }
    };
    fetchAutoTraderSettings();
  }, []);

  // Update auto-trader settings on backend
  const updateAutoTraderSettings = async (newSettings) => {
    try {
      await axios.post(`${API}/auto-trader/settings`, newSettings);
      setAutoTraderSettings(prev => ({ ...prev, ...newSettings }));
      toast.success('Auto-trader settings updated');
      // Clear entry conditions cache to refresh with new settings
      Object.keys(entryConditionsCache).forEach(key => delete entryConditionsCache[key]);
      setEntryConditions({});
      // Re-fetch entry conditions for displayed stocks
      const readyStocks = scannerResults.filter(s => s.criteria_count >= 4);
      readyStocks.forEach(stock => fetchEntryConditions(stock.symbol));
    } catch (error) {
      console.error('Failed to update auto-trader settings:', error);
      toast.error('Failed to update settings');
    }
  };

  useEffect(() => {
    fetchScannerResults();
    fetchPositions();
    fetchMomentumStocks(); // Fetch momentum stocks on load
    
    // Auto-refresh scanner results every 60 seconds (reduced from 30s)
    const scannerInterval = setInterval(() => {
      fetchScannerResults();
    }, 60000);
    
    // Auto-refresh momentum stocks every 2 minutes (reduced frequency)
    const momentumInterval = setInterval(() => {
      fetchMomentumStocks();
    }, 120000);
    
    // Auto-refresh positions every 15 seconds (reduced from 5s)
    const positionsInterval = setInterval(fetchPositions, 15000);
    
    // Auto-update chart data for selected stocks every 15 seconds (fast
    // incremental updates so the newest 1-min candle shows up ASAP - this
    // only fetches the last 10 bars via updateStockData, not a full reload).
    const chartUpdateInterval = setInterval(async () => {
      // Read from refs, not the closed-over selectedStocks/positions/etc
      // state - this interval is only ever created once per
      // demoMode/criteriaFilter change, so it must not rely on a stale
      // snapshot from whenever it was last (re)created.
      const symbolsToUpdate = new Set([...selectedStocksRef.current]);
      positionsRef.current.forEach(p => symbolsToUpdate.add(p.symbol));
      
      if (symbolsToUpdate.size > 0 && symbolsToUpdate.size <= 5) {
        // Only update if reasonable number of symbols (prevent spam)
        for (const symbol of symbolsToUpdate) {
          let stock = scannerResultsRef.current.find(s => s.symbol === symbol);
          if (!stock) stock = momentumStocksRef.current.find(s => s.symbol === symbol);
          if (!stock) {
            const position = positionsRef.current.find(p => p.symbol === symbol);
            if (position) {
              stock = {
                symbol: position.symbol,
                current_price: position.current_price,
                criteria_count: 0
              };
            }
          }
          if (stock) {
            await updateStockData(symbol, stock);
          }
        }
      }
    }, 15000);
    
    return () => {
      clearInterval(scannerInterval);
      clearInterval(momentumInterval);
      clearInterval(positionsInterval);
      clearInterval(chartUpdateInterval);
    };
  }, [demoMode, criteriaFilter]);

  useEffect(() => {
    // Fetch full (2-day) chart history for each NEWLY opened chart - exactly
    // once per symbol (guarded by loadedChartsRef), never re-triggered by
    // scannerResults/momentumStocks/positions refreshing in the background.
    // That used to cause every open chart to re-issue a full 3-day reload
    // on every 15-60s poll tick, hammering the market data API and making
    // charts flicker/reset constantly.
    Array.from(selectedStocks).forEach(symbol => {
      if (loadedChartsRef.current.has(symbol)) return;

      // Try to find in scanner results
      let stock = scannerResults.find(s => s.symbol === symbol);

      // If not in scanner results, check momentum stocks
      if (!stock) {
        stock = momentumStocks.find(s => s.symbol === symbol);
      }

      // If not in momentum, check if it's a position
      if (!stock) {
        const position = positions.find(p => p.symbol === symbol);
        if (position) {
          // Create a stock object from position data
          stock = {
            symbol: position.symbol,
            current_price: position.current_price,
            pct_change: position.unrealized_plpc || 0,
            prev_close: position.avg_entry_price,
            volume_ratio: 0,
            criteria_count: 0
          };
        }
      }

      if (stock) {
        loadedChartsRef.current.add(symbol);
        fetchStockData(stock);
      }
    });

    // A symbol's chart was closed (no longer selected) - drop its loaded
    // flag so reopening it later fetches fresh data again instead of
    // silently reusing whatever was in state before.
    Array.from(loadedChartsRef.current).forEach(symbol => {
      if (!selectedStocks.has(symbol)) loadedChartsRef.current.delete(symbol);
    });
  }, [selectedStocks, scannerResults, momentumStocks, positions]);

  const fetchScannerResults = async () => {
    try {
      // Load from cache first (instant display)
      const cached = scannerCache.get();
      if (cached && cached.data && cached.data.length > 0) {
        const filteredCached = applyFilter(cached.data);
        setScannerResults(filteredCached);
        console.log('Loaded from cache:', cached.data.length, 'stocks, filtered:', filteredCached.length);
      }
      
      // Only fetch fresh data if cache is stale OR empty
      if (!cached || !cached.isFresh || !cached.data || cached.data.length === 0) {
        console.log('Fetching fresh scanner data...');
        const criteria = {
          min_price: 2,
          max_price: 20,
          min_change: 10,
          min_volume_ratio: 5,
          max_float: 20000000
        };
        
        let response;
        let newResults;
        
        if (demoMode) {
          // Use demo endpoint
          response = await axios.get(`${API}/scanner/demo`, { params: criteria });
          newResults = response.data.results;
        } else {
          // Use real Alpaca scanner
          response = await axios.post(`${API}/scanner/scan`, criteria);
          newResults = response.data;
        }
        
        console.log('Scanner API returned:', newResults?.length, 'stocks');
        
        if (newResults && newResults.length > 0) {
          // Cache the fresh results
          scannerCache.set(newResults);
          
          // Apply filter and update
          const filteredResults = applyFilter(newResults);
          console.log('After filter:', filteredResults?.length, 'stocks');
          setScannerResults(filteredResults);
        } else {
          console.warn('Scanner returned empty results');
        }
      }
      
    } catch (error) {
      console.error('Failed to fetch scanner results:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch momentum stocks (higher highs, 3/5 criteria)
  const fetchMomentumStocks = async () => {
    try {
      console.log('Fetching momentum stocks...');
      const response = await axios.get(`${API}/scanner/momentum`, { timeout: 10000 });
      const data = response.data;
      
      if (data.stocks && data.stocks.length > 0) {
        setMomentumStocks(data.stocks);
        console.log(`Momentum scan: ${data.stocks.length} stocks building momentum`);
      } else {
        // Only clear if we got a valid empty response (not an error)
        console.log('No momentum stocks found in response');
      }
    } catch (error) {
      // Don't clear momentum stocks on error - keep existing data
      console.error('Failed to fetch momentum stocks:', error.message);
    }
  };
  
  const applyFilter = (results) => {
    let filtered = results;
    if (criteriaFilter === '3+') {
      filtered = results.filter(stock => (stock.criteria_count || 0) >= 3);
    } else if (criteriaFilter === '4+') {
      filtered = results.filter(stock => (stock.criteria_count || 0) >= 4);
    } else if (criteriaFilter === '5') {
      filtered = results.filter(stock => (stock.criteria_count || 0) === 5);
    }
    
    // Sort results by criteria count (highest first), then by volume ratio
    filtered.sort((a, b) => {
      // First, sort by criteria count (5/5 at top, then 4/5, etc.)
      const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
      if (criteriaCompare !== 0) return criteriaCompare;
      
      // If same criteria count, sort by volume ratio (highest first)
      return (b.volume_ratio || 0) - (a.volume_ratio || 0);
    });
    
    return filtered;
  };

  // Get stocks filtered/sorted based on current tab
  const getFilteredStocks = () => {
    if (scannerTab === 'momentum') {
      return momentumStocks;
    }
    
    let stocks = [...scannerResults];
    
    // For momentum tab, return momentum stocks
    if (scannerTab === 'momentum') {
      return momentumStocks;
    }
    
    // Apply criteria filter
    if (criteriaFilter === '4+') {
      stocks = stocks.filter(s => (s.criteria_count || 0) >= 4);
    } else if (criteriaFilter === '5') {
      stocks = stocks.filter(s => (s.criteria_count || 0) === 5);
    }
    
    // Sort by criteria count, then volume
    stocks.sort((a, b) => {
      const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
      if (criteriaCompare !== 0) return criteriaCompare;
      return (b.volume_ratio || 0) - (a.volume_ratio || 0);
    });
    
    return stocks;
  };

  const fetchPositions = async () => {
    try {
      const response = await axios.get(`${API}/positions`);
      setPositions(response.data);
      // If we have positions but scanner is still loading, show the page anyway
      if (response.data.length > 0 && loading) {
        setLoading(false);
      }
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    }
  };

  const updateStockData = async (symbol, stock) => {
    try {
      // Fetch only new bars (last 10 bars) for smooth updates
      const [bars1MinResponse, bars5MinResponse, quoteResponse] = await Promise.all([
        axios.get(`${API}/market/bars/${symbol}?timeframe=1Min&limit=10`),
        axios.get(`${API}/market/bars/${symbol}?timeframe=5Min&limit=10`),
        axios.get(`${API}/market/quote/${symbol}`)
      ]);
      
      // Handle both old format (array) and new format ({bars: [], source: ''})
      const newBars1Min = Array.isArray(bars1MinResponse.data) 
        ? bars1MinResponse.data 
        : (bars1MinResponse.data.bars || []);
      const newBars5Min = Array.isArray(bars5MinResponse.data) 
        ? bars5MinResponse.data 
        : (bars5MinResponse.data.bars || []);
      const newQuote = quoteResponse.data;
      
      // Update existing data by appending new bars
      setStockData(prev => {
        if (!prev[symbol]) return prev; // Stock not loaded yet
        
        const existingData = prev[symbol];
        
        // Merge new bars with existing (update existing timestamps, add new ones)
        const updated1Min = [...existingData.bars1Min];
        const updated5Min = [...existingData.bars5Min];
        
        // Add or update bars
        newBars1Min.forEach(bar => {
          const existingIdx = updated1Min.findIndex(b => b.timestamp === bar.timestamp);
          if (existingIdx >= 0) {
            // Update existing bar (price may have changed)
            updated1Min[existingIdx] = bar;
          } else {
            updated1Min.push(bar);
          }
        });
        
        newBars5Min.forEach(bar => {
          const existingIdx = updated5Min.findIndex(b => b.timestamp === bar.timestamp);
          if (existingIdx >= 0) {
            // Update existing bar (price may have changed)
            updated5Min[existingIdx] = bar;
          } else {
            updated5Min.push(bar);
          }
        });
        
        // Sort by timestamp and keep only last N bars
        updated1Min.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        updated5Min.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        
        const trimmed1Min = updated1Min.slice(-780); // keep the full 2-day window (see fetchStockData)
        const trimmed5Min = updated5Min.slice(-156); // keep the full 2-day window (see fetchStockData)
        
        // Recalculate indicators with new data
        let sma20 = existingData.sma20, sma50 = existingData.sma50, rsi = existingData.rsi, vwap = existingData.vwap;
        
        if (trimmed5Min.length >= 20) {
          const closes = trimmed5Min.slice(-20).map(b => b.close);
          sma20 = closes.reduce((a, b) => a + b, 0) / closes.length;
        }
        
        if (trimmed5Min.length >= 50) {
          const closes = trimmed5Min.slice(-50).map(b => b.close);
          sma50 = closes.reduce((a, b) => a + b, 0) / closes.length;
        }
        
        // Update VWAP
        if (trimmed1Min.length > 0) {
          let totalPV = 0, totalVolume = 0;
          trimmed1Min.forEach(bar => {
            const typical = (bar.high + bar.low + bar.close) / 3;
            totalPV += typical * bar.volume;
            totalVolume += bar.volume;
          });
          vwap = totalVolume > 0 ? totalPV / totalVolume : vwap;
        }
        
        return {
          ...prev,
          [symbol]: {
            ...existingData, // Preserve existing properties like 'stock' and 'barsDaily'
            bars1Min: trimmed1Min,
            bars5Min: trimmed5Min,
            quote: newQuote,
            sma20,
            sma50,
            rsi: existingData.rsi, // Keep existing RSI for now
            vwap
          }
        };
      });
      
    } catch (error) {
      console.error(`Failed to update data for ${symbol}:`, error);
    }
  };
  
  const fetchStockData = async (stock) => {
    try {
      // Fetch 2 days of intraday data (ASAP-fresh charts, not stale 3-day loads)
      // 1-min bars: 2 days * 390 bars/day = 780 bars
      // 5-min bars: 2 days * 78 bars/day = 156 bars
      // Daily bars: 30 days for longer-term trend (unrelated to the intraday window)
      const [bars1MinResponse, bars5MinResponse, barsDailyResponse, quoteResponse] = await Promise.all([
        axios.get(`${API}/market/bars/${stock.symbol}?timeframe=1Min&limit=780`), // 2 days of 1-min bars
        axios.get(`${API}/market/bars/${stock.symbol}?timeframe=5Min&limit=156`), // 2 days of 5-min bars
        axios.get(`${API}/market/bars/${stock.symbol}?timeframe=1Day&limit=30&use_fallback=false`), // 30 days of daily bars
        axios.get(`${API}/market/quote/${stock.symbol}`)
      ]);
      
      // Handle both old format (array) and new format ({bars: [], source: ''})
      const bars1Min = Array.isArray(bars1MinResponse.data) 
        ? bars1MinResponse.data 
        : (bars1MinResponse.data.bars || []);
      const bars5Min = Array.isArray(bars5MinResponse.data) 
        ? bars5MinResponse.data 
        : (bars5MinResponse.data.bars || []);
      const barsDaily = Array.isArray(barsDailyResponse.data) 
        ? barsDailyResponse.data 
        : (barsDailyResponse.data.bars || []);
      const quoteData = quoteResponse.data;
      
      // Log data source for debugging
      const dataSource = bars5MinResponse.data.source || 'alpaca';
      console.log(`${stock.symbol} chart data source: ${dataSource}, bars: 1m=${bars1Min.length}, 5m=${bars5Min.length}, daily=${barsDaily.length}`);
      
      // Calculate Technical Indicators
      let sma20 = null, sma50 = null, rsi = null, vwap = null;
      
      // SMA20
      if (bars5Min.length >= 20) {
        const closes = bars5Min.slice(-20).map(b => b.close);
        sma20 = closes.reduce((a, b) => a + b, 0) / closes.length;
      }
      
      // SMA50
      if (bars5Min.length >= 50) {
        const closes = bars5Min.slice(-50).map(b => b.close);
        sma50 = closes.reduce((a, b) => a + b, 0) / closes.length;
      }
      
      // RSI (14 period)
      if (bars5Min.length >= 15) {
        const closes = bars5Min.slice(-15).map(b => b.close);
        let gains = 0, losses = 0;
        
        for (let i = 1; i < closes.length; i++) {
          const change = closes[i] - closes[i - 1];
          if (change > 0) gains += change;
          else losses += Math.abs(change);
        }
        
        const avgGain = gains / 14;
        const avgLoss = losses / 14;
        
        if (avgLoss === 0) rsi = 100;
        else {
          const rs = avgGain / avgLoss;
          rsi = 100 - (100 / (1 + rs));
        }
      }
      
      // VWAP (Volume Weighted Average Price)
      if (bars1Min.length > 0) {
        let totalPV = 0, totalVolume = 0;
        bars1Min.forEach(bar => {
          const typical = (bar.high + bar.low + bar.close) / 3;
          totalPV += typical * bar.volume;
          totalVolume += bar.volume;
        });
        vwap = totalVolume > 0 ? totalPV / totalVolume : null;
      }
      
      setStockData(prev => ({
        ...prev,
        [stock.symbol]: {
          bars1Min: bars1Min,
          bars5Min: bars5Min,
          barsDaily: barsDaily,
          quote: quoteData,
          sma20: sma20,
          sma50: sma50,
          rsi: rsi,
          vwap: vwap,
          stock: stock,
          // Spread data from quote
          bid: quoteData?.bid_price || 0,
          ask: quoteData?.ask_price || 0,
          spread_pct: quoteData?.spread_pct || 0
        }
      }));
    } catch (error) {
      console.error(`Failed to fetch data for ${stock.symbol}:`, error);
    }
  };

  // Fetch entry conditions for stocks meeting 5/5 criteria
  const fetchEntryConditions = async (symbol) => {
    // Check cache first (valid for 30 seconds)
    const cached = entryConditionsCache[symbol];
    if (cached && Date.now() - cached.timestamp < 30000) {
      setEntryConditions(prev => ({ ...prev, [symbol]: cached.data }));
      return;
    }
    
    try {
      const response = await axios.get(`${API}/auto-trader/entry-conditions/${symbol}`);
      const data = response.data;
      
      // Cache the result
      entryConditionsCache[symbol] = { data, timestamp: Date.now() };
      
      setEntryConditions(prev => ({ ...prev, [symbol]: data }));
    } catch (error) {
      console.error(`Failed to fetch entry conditions for ${symbol}:`, error);
    }
  };

  // Fetch news for a single stock
  const fetchNewsForStock = async (symbol) => {
    try {
      const response = await axios.get(`${API}/news/${symbol}`);
      setStockNews(prev => ({
        ...prev,
        [symbol]: {
          ...response.data,
          last_updated: Date.now()
        }
      }));
    } catch (error) {
      console.error(`Failed to fetch news for ${symbol}:`, error);
    }
  };

  // Fetch news for all 3/5+ stocks (parallel)
  const fetchNewsForHighCriteriaStocks = async (stocks) => {
    const stocksToFetch = stocks.filter(s => (s.criteria_count || 0) >= 3);
    if (stocksToFetch.length === 0) return;
    
    // Fetch news in parallel for all 3/5+ stocks
    await Promise.all(stocksToFetch.map(stock => fetchNewsForStock(stock.symbol)));
  };

  // Fetch entry conditions for 3/5+ stocks when scanner results update
  useEffect(() => {
    const readyStocks = scannerResults.filter(s => s.criteria_count >= 3);
    readyStocks.forEach(stock => {
      fetchEntryConditions(stock.symbol);
    });
    
    // Also fetch news for 3/5+ stocks
    fetchNewsForHighCriteriaStocks(scannerResults);
  }, [scannerResults]);

  const toggleStockSelection = (symbol) => {
    setSelectedStocks(prev => {
      const newSet = new Set(prev);
      if (newSet.has(symbol)) {
        // Remove if already selected
        newSet.delete(symbol);
      } else {
        // Add to selection (max 6 stocks for buying)
        if (newSet.size >= 6) {
          return prev;
        }
        newSet.add(symbol);
      }
      return newSet;
    });
  };

  const placeOrder = async (symbol) => {
    if (!symbol) return;
    setPlacing(true);
    toast.loading(`Placing buy order for ${symbol}...`, { id: `buy-${symbol}` });
    
    try {
      // Get current price from stockData
      const data = stockData[symbol];
      let currentPrice = 10; // Fallback
      
      if (data) {
        const latestBar5Min = data.bars5Min?.[data.bars5Min.length - 1];
        const latestBar1Min = data.bars1Min?.[data.bars1Min.length - 1];
        currentPrice = latestBar1Min?.close || latestBar5Min?.close || currentPrice;
      }
      
      // Calculate quantity based on dollarAmountPerStock setting
      const calculatedQty = Math.floor(dollarAmountPerStock / currentPrice);
      const orderQty = Math.max(1, calculatedQty); // At least 1 share
      
      // Calculate stop loss and take profit prices
      const stopLossPrice = currentPrice * (1 - stopLossPct / 100);
      const takeProfitPrice = currentPrice * (1 + takeProfitPct / 100);
      
      const response = await axios.post(`${API}/orders`, {
        symbol: symbol,
        qty: orderQty,
        side: 'buy',
        stop_loss_pct: stopLossPct,
        take_profit_pct: takeProfitPct,
        entry_price: currentPrice,
        stop_type: stopType,
        trailing_stop_pct: trailingStopPct,
        partial_sell_pct: partialSellPct,
        partial_sell_trigger_pct: partialSellTrigger,
        move_to_breakeven: moveToBreakeven
      }, { timeout: 15000 });  // 15 second timeout for orders
      
      const result = response.data;
      const actualPrice = result.actual_price || result.filled_avg_price || currentPrice;
      const totalCost = (orderQty * actualPrice).toFixed(2);
      
      // Check if price changed (fallback was used)
      if (result.price_changed || result.warning) {
        toast.warning(`⚠️ Bought ${orderQty} ${symbol} @ $${actualPrice.toFixed(2)} - Price moved! Using trailing stop.`, { 
          id: `buy-${symbol}`,
          duration: 6000
        });
        // Refresh chart data since price changed
        const stock = scannerResults.find(s => s.symbol === symbol);
        if (stock) {
          fetchStockData(stock);
        }
        fetchScannerResults();
      } else {
        // Check if there's a spread warning
        if (result.spread_warning) {
          toast.warning(`⚠️ ${symbol}: Wide spread (${result.spread_pct?.toFixed(1)}%) - Stop calculated from BID. Bought ${orderQty} @ $${actualPrice.toFixed(2)}`, { 
            id: `buy-${symbol}`,
            duration: 8000
          });
        } else {
          toast.success(`✅ Bought ${orderQty} ${symbol} @ $${actualPrice.toFixed(2)} ($${totalCost})`, { id: `buy-${symbol}` });
        }
      }
      
      setLastAction({ 
        type: 'buy', 
        symbol: symbol, 
        success: true, 
        qty: orderQty, 
        price: actualPrice.toFixed(2), 
        warning: result.warning,
        spread_warning: result.spread_warning,
        spread_pct: result.spread_pct
      });
      setTimeout(() => setLastAction(null), 5000);
      setTimeout(fetchPositions, 1000); // Refresh positions after 1s
    } catch (error) {
      const errorMsg = error.response?.data?.detail || error.message;
      console.error('Order failed:', errorMsg);
      
      // Check if error is due to price movement / stale data
      const isPriceError = errorMsg.toLowerCase().includes('price') || 
                          errorMsg.toLowerCase().includes('moved') ||
                          errorMsg.toLowerCase().includes('base_price') ||
                          errorMsg.toLowerCase().includes('limit_price') ||
                          errorMsg.toLowerCase().includes('not filled');
      
      if (isPriceError) {
        // Price-related failure - refresh chart data and show specific message
        toast.error(`❌ ${symbol} order failed - price moved too fast! Refreshing chart...`, { 
          id: `buy-${symbol}`,
          duration: 5000
        });
        
        // Refresh the scanner to get latest prices
        fetchScannerResults();
        
        // Refresh chart data for this specific stock
        const stock = scannerResults.find(s => s.symbol === symbol);
        if (stock) {
          toast.info(`🔄 Updating ${symbol} data...`, { duration: 2000 });
          await fetchStockData(stock);
        }
        
        setLastAction({ 
          type: 'buy', 
          symbol: symbol, 
          success: false, 
          error: 'Price moved too fast - chart refreshed with latest data. Try again.',
          priceError: true
        });
      } else {
        toast.error(`❌ Buy ${symbol} failed: ${errorMsg}`, { id: `buy-${symbol}` });
        setLastAction({ type: 'buy', symbol: symbol, success: false, error: errorMsg });
      }
      
      setTimeout(() => setLastAction(null), 8000); // Show error longer
    } finally {
      setPlacing(false);
    }
  };

  const buyAllSelected = async () => {
    if (selectedStocks.size === 0) {
      return;
    }
    
    setBuyingAll(true);
    let successCount = 0;
    let failCount = 0;
    let priceErrorSymbols = [];
    
    try {
      const selectedArray = Array.from(selectedStocks);
      console.log('buyAllSelected: Starting buy for', selectedArray.length, 'stocks:', selectedArray);
      console.log('buyAllSelected: scannerResults count:', scannerResults.length);
      console.log('buyAllSelected: momentumStocks count:', momentumStocks.length);
      
      for (const symbol of selectedArray) {
        // Check scanner results first, then momentum stocks
        let stock = scannerResults.find(s => s.symbol === symbol);
        if (!stock) {
          stock = momentumStocks.find(s => s.symbol === symbol);
          if (stock) console.log(`${symbol}: Found in momentumStocks`);
        } else {
          console.log(`${symbol}: Found in scannerResults`);
        }
        if (!stock) {
          console.log(`${symbol}: NOT FOUND in either array - skipping`);
          continue;
        }
        
        try {
          const currentPrice = stock.current_price;
          const orderQty = Math.floor(dollarAmountPerStock / currentPrice);
          console.log(`${symbol}: price=${currentPrice}, dollarAmount=${dollarAmountPerStock}, qty=${orderQty}`);
          
          if (orderQty < 1) {
            console.log(`${symbol}: qty < 1, skipping`);
            continue;
          }
          
          const stopLossPrice = currentPrice * (1 - stopLossPct / 100);
          const takeProfitPrice = currentPrice * (1 + takeProfitPct / 100);
          
          console.log(`${symbol}: Placing order...`);
          const response = await axios.post(`${API}/orders`, {
            symbol: symbol,
            qty: orderQty,
            side: 'buy',
            stop_loss_pct: stopLossPct,
            take_profit_pct: takeProfitPct,
            entry_price: currentPrice,
            stop_type: stopType,
            trailing_stop_pct: trailingStopPct,
            partial_sell_pct: partialSellPct,
            partial_sell_trigger_pct: partialSellTrigger,
            move_to_breakeven: moveToBreakeven
          }, { timeout: 15000 });  // 15 second timeout for orders
          console.log(`${symbol}: Order response:`, response.data);
          
          successCount++;
        } catch (error) {
          failCount++;
          const errorMsg = error.response?.data?.detail || error.message || '';
          console.error(`${symbol}: Order FAILED:`, errorMsg);
          // Track price-related errors
          if (errorMsg.toLowerCase().includes('price') || 
              errorMsg.toLowerCase().includes('moved') ||
              errorMsg.toLowerCase().includes('not filled')) {
            priceErrorSymbols.push(symbol);
          }
          console.error(`${symbol}: Order failed`, error);
        }
      }
      
      // Handle price errors - refresh data
      if (priceErrorSymbols.length > 0) {
        toast.warning(`⚠️ ${priceErrorSymbols.join(', ')} failed - prices moved too fast! Refreshing...`, { duration: 5000 });
        // Refresh scanner data
        fetchScannerResults();
        fetchMomentumStocks();
        // Refresh chart data for failed symbols
        for (const symbol of priceErrorSymbols) {
          let stock = scannerResults.find(s => s.symbol === symbol);
          if (!stock) stock = momentumStocks.find(s => s.symbol === symbol);
          if (stock) {
            fetchStockData(stock);
          }
        }
      }
      
      // Completion status
      if (successCount > 0) {
        setLastAction({ type: 'bulk-buy', success: true, count: successCount, failed: failCount, priceErrors: priceErrorSymbols.length });
        setTimeout(() => setLastAction(null), 5000);
        fetchPositions(); // Refresh positions
        setSelectedStocks(new Set()); // Clear selections after buying
      } else if (failCount > 0) {
        setLastAction({ type: 'bulk-buy', success: false, failed: failCount, priceErrors: priceErrorSymbols.length });
        setTimeout(() => setLastAction(null), 8000);
      }
    } catch (error) {
      console.error('Buy all failed:', error.message);
    } finally {
      setBuyingAll(false);
    }
  };

  const [sellingSelected, setSellingSelected] = useState(false);

  // Get selected stocks that have open positions
  const selectedWithPositions = useMemo(() => {
    return Array.from(selectedStocks).filter(symbol => 
      positions.some(p => p.symbol === symbol)
    );
  }, [selectedStocks, positions]);

  const sellSelectedPositions = async () => {
    if (selectedWithPositions.length === 0) {
      toast.error('No selected stocks have open positions');
      return;
    }
    
    setSellingSelected(true);
    let successCount = 0;
    let failCount = 0;
    
    try {
      for (const symbol of selectedWithPositions) {
        const position = positions.find(p => p.symbol === symbol);
        if (!position) continue;
        
        try {
          await axios.post(`${API}/orders`, {
            symbol: position.symbol,
            qty: position.qty,
            side: 'sell'
          });
          successCount++;
        } catch (error) {
          failCount++;
          console.error(`Failed to sell ${position.symbol}:`, error);
        }
      }
      
      if (successCount > 0) {
        toast.success(`Sold ${successCount} position${successCount > 1 ? 's' : ''}`);
        setLastAction({ type: 'sell-selected', success: true, count: successCount });
        setTimeout(() => setLastAction(null), 5000);
        // Clear sold stocks from selection
        setSelectedStocks(prev => {
          const newSet = new Set(prev);
          selectedWithPositions.forEach(s => newSet.delete(s));
          return newSet;
        });
      }
      if (failCount > 0) {
        toast.error(`Failed to sell ${failCount} position${failCount > 1 ? 's' : ''}`);
      }
      
      setTimeout(fetchPositions, 2000);
    } catch (error) {
      console.error('Error selling selected positions:', error.message);
    } finally {
      setSellingSelected(false);
    }
  };

  const sellAllPositions = async () => {
    if (positions.length === 0) {
      return;
    }
    
    // INSTANT SELL - No confirmation dialog
    setSellingAll(true);
    let successCount = 0;
    let failCount = 0;
    
    try {
      // Sell each position
      for (const position of positions) {
        try {
          await axios.post(`${API}/orders`, {
            symbol: position.symbol,
            qty: position.qty,
            side: 'sell'
          });
          successCount++;
        } catch (error) {
          failCount++;
          console.error(`Failed to sell ${position.symbol}:`, error);
        }
      }
      
      // Positions liquidated
      if (successCount > 0) {
        setLastAction({ type: 'sell-all', success: true, count: successCount });
        setTimeout(() => setLastAction(null), 5000);
      }
      
      // Refresh positions after selling
      setTimeout(fetchPositions, 2000);
    } catch (error) {
      console.error('Error liquidating positions:', error.message);
    } finally {
      setSellingAll(false);
    }
  };

  // Removed old single-chart code

  // Show loading only if both scanner and positions are loading
  if (loading && positions.length === 0) {
    return (
      <div className="flex justify-center items-center h-96">
        <div className="text-lg text-neutral-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Live Update Indicator */}
      {isUpdating && (
        <div className="fixed top-4 right-4 z-50 px-3 py-2 bg-blue-500/20 border border-blue-500/40 rounded-lg backdrop-blur-sm">
          <div className="flex items-center gap-2 text-blue-400 text-xs">
            <div className="animate-pulse w-2 h-2 bg-blue-400 rounded-full"></div>
            <span>Updating charts...</span>
          </div>
        </div>
      )}
      
      {/* No Results Message */}
      {getFilteredStocks().length === 0 && (
        <Card className="bg-yellow-500/10 border-yellow-500/30">
          <CardContent className="pt-6">
            <div className="text-center">
              <Search className="mx-auto mb-4 text-yellow-500" size={48} />
              <div className="text-yellow-500 font-bold mb-2">
                {scannerTab === 'momentum' ? 'No Momentum Stocks Found' : 'No Stocks Found'}
              </div>
              <div className="text-sm text-neutral-400">
                {scannerTab === 'momentum' 
                  ? 'Looking for stocks with 3/5 criteria making higher highs.'
                  : scannerTab === 'news'
                  ? 'No stocks with positive news catalysts found.'
                  : 'No stocks match the current filter criteria.'}
              </div>
              <Button
                onClick={scannerTab === 'momentum' ? fetchMomentumStocks : fetchScannerResults}
                className="mt-4 bg-[#00E599] text-black hover:bg-[#00CC88]"
              >
                Refresh Scanner
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Market Status Banner */}
      {marketStatus && !marketStatus.is_open && (
        <div className="p-4 mb-4 rounded-lg border bg-yellow-500/10 border-yellow-500/30 text-yellow-400">
          <div className="flex items-center gap-3">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <div>
              <div className="font-bold">⚠️ Market is CLOSED</div>
              <div className="text-sm text-yellow-300">
                Trading disabled. Extended hours: {marketStatus.extended_hours || "4:00 AM - 8:00 PM ET"}
              </div>
              <div className="text-xs text-yellow-400 mt-1">
                Current time: {marketStatus.current_time_et} ({marketStatus.day_of_week})
              </div>
            </div>
          </div>
        </div>
      )}
      
      {/* Status Banner */}
      {lastAction && (
        <div className={`p-3 mb-4 rounded-lg border ${
          lastAction.success 
            ? 'bg-[#00E599]/10 border-[#00E599]/30 text-[#00E599]' 
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {lastAction.success ? (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
              <span className="text-sm font-medium">
                {lastAction.type === 'buy' && lastAction.success && `✓ Bought ${lastAction.qty} ${lastAction.symbol} @ $${lastAction.price}`}
                {lastAction.type === 'buy' && !lastAction.success && `✗ Failed to buy ${lastAction.symbol}`}
                {lastAction.type === 'bulk-buy' && lastAction.success && `✓ Bought ${lastAction.count} stock(s)${lastAction.failed > 0 ? ` (${lastAction.failed} failed)` : ''}`}
                {lastAction.type === 'bulk-buy' && !lastAction.success && `✗ All ${lastAction.failed} order(s) failed`}
                {lastAction.type === 'sell-all' && `✓ Sold ${lastAction.count} position(s)`}
              </span>
            </div>
            <button onClick={() => setLastAction(null)} className="text-neutral-500 hover:text-white">
              ×
            </button>
          </div>
        </div>
      )}

      {/* Top Action Bar - Always show so filter is accessible */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardContent className="pt-4">
          {/* Simple View Toggle: Opportunities vs Momentum */}
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs text-neutral-500">View:</span>
            <Button
              size="sm"
              variant={scannerTab !== 'momentum' ? 'default' : 'outline'}
              className={`h-8 px-4 text-sm ${scannerTab !== 'momentum' ? 'bg-[#00E599] text-black font-bold' : 'bg-transparent border-white/20 text-neutral-400 hover:text-white'}`}
              onClick={() => setScannerTab('all')}
            >
              🎯 Opportunities ({scannerResults.length})
            </Button>
            <Button
              size="sm"
              variant={scannerTab === 'momentum' ? 'default' : 'outline'}
              className={`h-8 px-4 text-sm ${scannerTab === 'momentum' ? 'bg-[#F59E0B] text-black font-bold' : 'bg-transparent border-white/20 text-neutral-400 hover:text-white'}`}
              onClick={() => { setScannerTab('momentum'); fetchMomentumStocks(); }}
            >
              ⚡ Momentum ({momentumStocks.length})
            </Button>
            <span className="text-xs text-neutral-500 ml-2">
              {scannerTab === 'momentum' ? 'Stocks making higher highs (3/5 criteria) - watch for pullbacks' : 'Stocks meeting scanner criteria'}
            </span>
          </div>

          {/* Row 1: Stats + Filter + Actions */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              {/* Left side: Stats and Filter */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="text-sm">
                  <span className="text-neutral-500">{scannerTab === 'momentum' ? 'Momentum' : 'Scanner'}: </span>
                  <span className="font-mono text-[#00E599]">{scannerTab === 'momentum' ? momentumStocks.length : scannerResults.length} stocks</span>
                </div>
                <div className="h-6 w-px bg-white/10" />
                {/* Quick Filter Buttons - Only show for Opportunities view */}
                {scannerTab !== 'momentum' && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-neutral-500 mr-1">Filter:</span>
                  <Button
                    size="sm"
                    variant={criteriaFilter === 'all' ? 'default' : 'outline'}
                    className={`h-7 px-2 text-xs ${criteriaFilter === 'all' ? 'bg-[#2E5CFF] text-white' : 'bg-transparent border-white/20 text-neutral-400 hover:text-white'}`}
                    onClick={() => { setCriteriaFilter('all'); localStorage.setItem('criteriaFilter', 'all'); }}
                  >
                    All
                  </Button>
                  <Button
                    size="sm"
                    variant={criteriaFilter === '4+' ? 'default' : 'outline'}
                    className={`h-7 px-2 text-xs ${criteriaFilter === '4+' ? 'bg-[#F59E0B] text-black font-bold' : 'bg-transparent border-white/20 text-neutral-400 hover:text-white'}`}
                    onClick={() => { setCriteriaFilter('4+'); localStorage.setItem('criteriaFilter', '4+'); }}
                  >
                    4/5+
                  </Button>
                  <Button
                    size="sm"
                    variant={criteriaFilter === '5' ? 'default' : 'outline'}
                    className={`h-7 px-2 text-xs ${criteriaFilter === '5' ? 'bg-[#00E599] text-black font-bold' : 'bg-transparent border-white/20 text-neutral-400 hover:text-white'}`}
                    onClick={() => { setCriteriaFilter('5'); localStorage.setItem('criteriaFilter', '5'); }}
                  >
                    5/5
                  </Button>
                </div>
                )}
                {/* Sort Dropdown - Show for both tabs */}
                <div className="flex items-center gap-2 bg-[#121212] border border-white/10 rounded-md px-2 py-1">
                  <Label className="text-xs text-neutral-500 whitespace-nowrap">Sort:</Label>
                  <Select value={scannerTab === 'momentum' ? 'momentum' : sortBy} onValueChange={(v) => {
                    setSortBy(v);
                    localStorage.setItem('sortBy', v);
                  }}>
                    <SelectTrigger className="h-7 w-28 bg-transparent border-0 text-white text-xs focus:ring-0">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {scannerTab !== 'momentum' ? (
                        <>
                          <SelectItem value="criteria">Criteria (5→1)</SelectItem>
                          <SelectItem value="news">📰 News Impact</SelectItem>
                          <SelectItem value="volume">Volume (High)</SelectItem>
                          <SelectItem value="change">% Change (High)</SelectItem>
                          <SelectItem value="price">Price (Low)</SelectItem>
                        </>
                      ) : (
                        <>
                          <SelectItem value="momentum">Momentum Score</SelectItem>
                          <SelectItem value="highs">Higher Highs</SelectItem>
                          <SelectItem value="trend">Trend %</SelectItem>
                        </>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="h-6 w-px bg-white/10" />
                <div className="text-sm">
                  <span className="text-neutral-500">Selected: </span>
                  <span className="font-mono text-[#2E5CFF]">{selectedStocks.size} stocks</span>
                  {selectedWithPositions.length > 0 && (
                    <span className="text-neutral-500 ml-1">({selectedWithPositions.length} in pos)</span>
                  )}
                </div>
                <div className="h-6 w-px bg-white/10" />
                <div className="text-sm">
                  <span className="text-neutral-500">Positions: </span>
                  <span className="font-mono text-white">{positions.length} open</span>
                </div>
              </div>
              
              {/* Right side: Action Buttons */}
              <div className="flex items-center gap-2">
                {/* Buy Selected Button */}
                {selectedStocks.size > 0 && (
                  <Button
                    onClick={buyAllSelected}
                    disabled={buyingAll}
                    className="bg-[#00E599] text-black hover:bg-[#00CC88] font-bold text-xs uppercase shadow-[0_0_15px_rgba(0,229,153,0.3)]"
                  >
                    {buyingAll ? 'BUYING...' : `BUY SELECTED (${selectedStocks.size})`}
                  </Button>
                )}
                {/* Sell Selected Button - only show when selected stocks have positions */}
                {selectedWithPositions.length > 0 && (
                  <Button
                    onClick={sellSelectedPositions}
                    disabled={sellingSelected}
                    className="bg-[#FF6B00] text-white hover:bg-[#E65C00] font-bold text-xs uppercase shadow-[0_0_15px_rgba(255,107,0,0.4)]"
                  >
                    {sellingSelected ? 'SELLING...' : `SELL SELECTED (${selectedWithPositions.length})`}
                  </Button>
                )}
                {/* Sell All Button */}
                {positions.length > 0 && (
                  <Button
                    onClick={sellAllPositions}
                    disabled={sellingAll}
                    className="bg-[#FF1A40] text-white hover:bg-[#E61739] font-bold text-xs uppercase shadow-[0_0_15px_rgba(255,26,64,0.5)]"
                    data-testid="sell-all-button"
                  >
                    {sellingAll ? 'SELLING...' : `SELL ALL (${positions.length})`}
                  </Button>
                )}
                <div className="text-[10px] text-neutral-500 flex items-center gap-1.5" data-testid="stream-status-indicator">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-[#00E599] animate-pulse' : 'bg-neutral-600'}`} />
                  {wsConnected ? 'Live stream connected' : 'Reconnecting...'}
                </div>
              </div>
            </div>
            
            {/* Row 2: Trade Settings */}
            <div className="flex flex-wrap items-center gap-3 py-2 border-t border-white/5">
              <div className="text-xs text-neutral-400 font-bold uppercase">Trade Settings:</div>
              
              {/* Dollar Amount */}
              <div className="flex items-center gap-2">
                <Label className="text-xs text-neutral-500 whitespace-nowrap">$ per stock:</Label>
                <Input
                  type="number"
                  value={dollarAmountPerStock}
                  onChange={(e) => {
                    const value = parseInt(e.target.value) || 2000;
                    setDollarAmountPerStock(value);
                    localStorage.setItem('dollarAmountPerStock', value.toString());
                  }}
                  className="w-20 h-7 bg-[#121212] border-white/10 text-white text-xs"
                  step="100"
                  min="100"
                />
              </div>
              
              <div className="h-5 w-px bg-white/10" />
              
              {/* Stop Loss */}
              <div className="flex items-center gap-2">
                <Label className="text-xs text-red-400 whitespace-nowrap">Stop:</Label>
                <Input
                  type="number"
                  value={stopLossPct}
                  onChange={(e) => {
                    const value = parseFloat(e.target.value) || 5.0;
                    setStopLossPct(value);
                    localStorage.setItem('stopLossPct', value.toString());
                  }}
                  className="w-14 h-7 bg-[#121212] border-red-500/30 text-red-400 text-xs"
                  step="0.5"
                  min="1"
                  max="20"
                />
                <span className="text-xs text-red-400">%</span>
              </div>
              
              {/* Take Profit */}
              <div className="flex items-center gap-2">
                <Label className="text-xs text-green-400 whitespace-nowrap">Target:</Label>
                <Input
                  type="number"
                  value={takeProfitPct}
                  onChange={(e) => {
                    const value = parseFloat(e.target.value) || 10.0;
                    setTakeProfitPct(value);
                    localStorage.setItem('takeProfitPct', value.toString());
                  }}
                  className="w-14 h-7 bg-[#121212] border-green-500/30 text-green-400 text-xs"
                  step="0.5"
                  min="1"
                  max="50"
                />
                <span className="text-xs text-green-400">%</span>
              </div>
              
              <div className="h-5 w-px bg-white/10" />
              
              {/* Stop Type */}
              <div className="flex items-center gap-2">
                <Label className="text-xs text-neutral-500">Type:</Label>
                <Select value={stopType} onValueChange={(v) => {
                  setStopType(v);
                  localStorage.setItem('stopType', v);
                }}>
                  <SelectTrigger className="h-7 w-24 bg-[#121212] border-white/10 text-white text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fixed">Fixed</SelectItem>
                    <SelectItem value="trailing">Trailing</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              {stopType === 'trailing' && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-orange-400">Trail:</Label>
                  <Input
                    type="number"
                    value={trailingStopPct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 5.0;
                      setTrailingStopPct(value);
                      localStorage.setItem('trailingStopPct', value.toString());
                    }}
                    className="w-14 h-7 bg-[#121212] border-orange-500/30 text-orange-400 text-xs"
                    step="0.5"
                    min="1"
                    max="20"
                  />
                  <span className="text-xs text-orange-400">%</span>
                </div>
              )}
            </div>
            
            {/* Row 3: Advanced Settings (collapsible feel) */}
            <div className="flex flex-wrap items-center gap-3 py-2 border-t border-white/5">
              <div className="text-xs text-neutral-400 font-bold uppercase">Advanced:</div>
              
              {/* Partial Sell */}
              <div className="flex items-center gap-2">
                <Label className="text-xs text-yellow-400">Partial @:</Label>
                <Input
                  type="number"
                  value={partialSellTrigger}
                  onChange={(e) => {
                    const value = parseFloat(e.target.value) || 10.0;
                    setPartialSellTrigger(value);
                    localStorage.setItem('partialSellTrigger', value.toString());
                  }}
                  className="w-14 h-7 bg-[#121212] border-yellow-500/30 text-yellow-400 text-xs"
                  step="1"
                  min="0"
                  max="100"
                />
                <span className="text-xs text-yellow-400">%</span>
              </div>
              
              <div className="flex items-center gap-2">
                <Label className="text-xs text-yellow-400">Sell:</Label>
                <Input
                  type="number"
                  value={partialSellPct}
                  onChange={(e) => {
                    const value = parseFloat(e.target.value) || 50.0;
                    setPartialSellPct(value);
                    localStorage.setItem('partialSellPct', value.toString());
                  }}
                  className="w-14 h-7 bg-[#121212] border-yellow-500/30 text-yellow-400 text-xs"
                  step="5"
                  min="10"
                  max="100"
                />
                <span className="text-xs text-yellow-400">%</span>
              </div>
              
              <div className="h-5 w-px bg-white/10" />
              
              {/* Move to Breakeven */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="move-breakeven"
                  checked={moveToBreakeven}
                  onChange={(e) => {
                    setMoveToBreakeven(e.target.checked);
                    localStorage.setItem('moveToBreakeven', e.target.checked.toString());
                  }}
                  className="w-4 h-4 rounded border-white/10 bg-[#121212] text-[#00E599]"
                />
                <Label htmlFor="move-breakeven" className="text-xs text-neutral-400 cursor-pointer">
                  Move SL to B/E after partial
                </Label>
              </div>
              
              <div className="h-5 w-px bg-white/10" />
              
              {/* Toggle Auto-Trader Settings */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAutoTraderSettings(!showAutoTraderSettings)}
                className="h-7 text-xs bg-transparent border-purple-500/30 text-purple-400 hover:bg-purple-500/20"
              >
                {showAutoTraderSettings ? '▲ Hide' : '▼ Entry Conditions'}
              </Button>
            </div>
            
            {/* Row 4: Auto-Trader Entry Condition Settings (Collapsible) */}
            {showAutoTraderSettings && (
              <div className="border-t border-purple-500/20 mt-3 bg-purple-500/5 rounded-md px-3 py-3">
                {/* Row 1: Entry Conditions */}
                <div className="flex flex-wrap items-center gap-3">
                  <div className="text-xs text-purple-400 font-bold uppercase">Entry Conditions:</div>
                
                  {/* Pullback Range */}
                  <div className="flex items-center gap-2">
                    <Label className="text-xs text-purple-300">Pullback:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.pullback_min_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 1.0;
                      updateAutoTraderSettings({ pullback_min_pct: value });
                    }}
                    className="w-12 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="0.5"
                    min="0"
                    max="10"
                  />
                  <span className="text-xs text-purple-300">-</span>
                  <Input
                    type="number"
                    value={autoTraderSettings.pullback_max_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 3.0;
                      updateAutoTraderSettings({ pullback_max_pct: value });
                    }}
                    className="w-12 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="0.5"
                    min="0"
                    max="10"
                  />
                  <span className="text-xs text-purple-300">%</span>
                </div>
                
                {/* Pullback Lookback Bars */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-purple-300">Bars:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.pullback_lookback_bars}
                    onChange={(e) => {
                      const value = parseInt(e.target.value) || 10;
                      updateAutoTraderSettings({ pullback_lookback_bars: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="1"
                    min="5"
                    max="30"
                  />
                </div>
                
                <div className="h-5 w-px bg-purple-500/20" />
                
                {/* MACD Crossover Toggle */}
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="macd-crossover"
                    checked={autoTraderSettings.require_macd_crossover}
                    onChange={(e) => updateAutoTraderSettings({ require_macd_crossover: e.target.checked })}
                    className="w-4 h-4 rounded border-purple-500/30 bg-[#121212] text-purple-400"
                  />
                  <Label htmlFor="macd-crossover" className="text-xs text-purple-300 cursor-pointer">
                    MACD Crossover
                  </Label>
                </div>
                
                {/* SMA Crossover Toggle */}
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="sma-crossover"
                    checked={autoTraderSettings.require_sma_crossover}
                    onChange={(e) => updateAutoTraderSettings({ require_sma_crossover: e.target.checked })}
                    className="w-4 h-4 rounded border-purple-500/30 bg-[#121212] text-purple-400"
                  />
                  <Label htmlFor="sma-crossover" className="text-xs text-purple-300 cursor-pointer">
                    SMA Crossover
                  </Label>
                </div>
                
                {/* SMA Period - Fast SMA over 50 */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-purple-300">SMA</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.sma_period}
                    onChange={(e) => {
                      const value = parseInt(e.target.value) || 20;
                      updateAutoTraderSettings({ sma_period: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="1"
                    min="5"
                    max="49"
                  />
                  <span className="text-xs text-purple-300">/50</span>
                </div>
                
                <div className="h-5 w-px bg-purple-500/20" />
                
                {/* Bull Flag Toggle */}
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="bull-flag"
                    checked={autoTraderSettings.require_bull_flag}
                    onChange={(e) => updateAutoTraderSettings({ require_bull_flag: e.target.checked })}
                    className="w-4 h-4 rounded border-yellow-500/30 bg-[#121212] text-yellow-400"
                  />
                  <Label htmlFor="bull-flag" className="text-xs text-yellow-400 cursor-pointer">
                    Bull Flag Required
                  </Label>
                </div>
                
                <div className="h-5 w-px bg-purple-500/20" />
                
                {/* Trading Hours */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-purple-300">Hours:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.trading_start_hour}
                    onChange={(e) => {
                      const value = parseInt(e.target.value) || 7;
                      updateAutoTraderSettings({ trading_start_hour: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="1"
                    min="4"
                    max="20"
                  />
                  <span className="text-xs text-purple-300">-</span>
                  <Input
                    type="number"
                    value={autoTraderSettings.trading_end_hour}
                    onChange={(e) => {
                      const value = parseInt(e.target.value) || 11;
                      updateAutoTraderSettings({ trading_end_hour: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="1"
                    min="4"
                    max="20"
                  />
                  <span className="text-xs text-purple-300">AM ET</span>
                </div>
              </div>
              
              {/* Row 2: Trade Management Settings */}
              <div className="flex flex-wrap items-center gap-3 py-2 border-t border-purple-500/10 mt-2">
                <div className="text-xs text-purple-400 font-bold uppercase">Trade Management:</div>
                
                {/* Profit Target */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-green-400">Target:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.profit_target_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 2.0;
                      updateAutoTraderSettings({ profit_target_pct: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-green-500/30 text-green-400 text-xs"
                    step="0.5"
                    min="0.5"
                    max="20"
                  />
                  <span className="text-xs text-green-400">%</span>
                </div>
                
                {/* Stop Loss */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-red-400">Stop:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.stop_loss_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 1.0;
                      updateAutoTraderSettings({ stop_loss_pct: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-red-500/30 text-red-400 text-xs"
                    step="0.5"
                    min="0.5"
                    max="10"
                  />
                  <span className="text-xs text-red-400">%</span>
                </div>
                
                <div className="h-5 w-px bg-purple-500/20" />
                
                {/* Position Size */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-blue-400">Size:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.position_size_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 10.0;
                      updateAutoTraderSettings({ position_size_pct: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-blue-500/30 text-blue-400 text-xs"
                    step="1"
                    min="1"
                    max="50"
                  />
                  <span className="text-xs text-blue-400">%</span>
                </div>
                
                {/* Max Positions */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-purple-300">Max Pos:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.max_positions}
                    onChange={(e) => {
                      const value = parseInt(e.target.value) || 5;
                      updateAutoTraderSettings({ max_positions: value });
                    }}
                    className="w-12 h-7 bg-[#121212] border-purple-500/30 text-purple-300 text-xs"
                    step="1"
                    min="1"
                    max="10"
                  />
                </div>
                
                {/* Daily Max Loss */}
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-orange-400">Max Loss:</Label>
                  <Input
                    type="number"
                    value={autoTraderSettings.daily_max_loss_pct}
                    onChange={(e) => {
                      const value = parseFloat(e.target.value) || 5.0;
                      updateAutoTraderSettings({ daily_max_loss_pct: value });
                    }}
                    className="w-14 h-7 bg-[#121212] border-orange-500/30 text-orange-400 text-xs"
                    step="0.5"
                    min="1"
                    max="20"
                  />
                  <span className="text-xs text-orange-400">%</span>
                </div>
                
                <div className="text-[10px] text-purple-400/70 ml-auto">
                  ✓ = Crossover required | □ = Just above/below
                </div>
              </div>
            </div>
            )}
          </CardContent>
        </Card>

      {/* Scanner Results + Positions List */}
      {(scannerResults.length > 0 || positions.length > 0 || momentumStocks.length > 0) && (
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardHeader>
            <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
              <Activity className="inline mr-2" size={18} />
              Select Stocks to View (Click to Toggle)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {/* Open Positions */}
              {positions.length > 0 && (
                <div>
                  <div className="text-xs text-neutral-500 mb-2 uppercase tracking-wider">Your Positions</div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {positions.map((position, idx) => {
                      const matchingStock = scannerResults.find(s => s.symbol === position.symbol) || {
                        symbol: position.symbol,
                        current_price: position.current_price,
                        pct_change: (position.unrealized_plpc || 0),
                        volume_ratio: 0,
                        has_bull_flag: false
                      };
                      const isSelected = selectedStocks.has(position.symbol);
                      
                      return (
                        <button
                          key={idx}
                          onClick={() => toggleStockSelection(position.symbol)}
                          className={`p-3 rounded-sm border transition-all text-left ${
                            isSelected
                              ? 'bg-[#00E599]/20 border-[#00E599]'
                              : 'bg-[#121212] border-white/5 hover:border-white/20'
                          }`}
                        >
                          <div className="font-mono font-bold text-white">{position.symbol}</div>
                          <div className={`text-xs ${position.unrealized_pl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                            {position.unrealized_pl >= 0 ? '+' : ''}${position.unrealized_pl.toFixed(2)}
                          </div>
                          <div className="text-xs text-neutral-500">{position.qty} shares</div>
                          <div className="text-[10px] text-[#00E599] mt-1">OPEN ●</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              
              {/* Scanner Opportunities or Momentum Stocks */}
              {getFilteredStocks().length > 0 && (
                <div>
                  <div className="text-xs text-neutral-500 mb-2 uppercase tracking-wider">
                    {scannerTab === 'momentum' ? '⚡ Momentum Stocks (Higher Highs)' : 'Scanner Opportunities'}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                    {getFilteredStocks()
                      .slice(0, 40) // Limit to 40 stocks for performance
                      .map((stock, idx) => {
                      const isSelected = selectedStocks.has(stock.symbol);
                      const hasPosition = positions.find(p => p.symbol === stock.symbol);
                      
                      // Check if we have live data for this stock
                      const data = stockData[stock.symbol];
                      if (data) {
                        const latestBar5Min = data.bars5Min?.[data.bars5Min.length - 1];
                        const latestBar1Min = data.bars1Min?.[data.bars1Min.length - 1];
                        const currentPrice = latestBar1Min?.close || latestBar5Min?.close || stock.current_price;
                        
                        // Hide if price moved outside $2-$20 range
                        if (currentPrice < 2 || currentPrice > 20) {
                          return null;
                        }
                      }
                      
                      // Get criteria status from stock.criteria_met object
                      const criteriaMet = stock.criteria_met || {};
                      
                      return (
                        <button
                          key={idx}
                          onClick={() => toggleStockSelection(stock.symbol)}
                          className={`p-3 rounded-sm border transition-all text-left relative ${
                            isSelected
                              ? 'bg-[#00E599]/20 border-[#00E599] shadow-lg'
                              : scannerTab === 'momentum'
                              ? 'bg-orange-500/10 border-orange-500/30 hover:border-orange-500/50'
                              : 'bg-[#121212] border-white/5 hover:border-white/20'
                          }`}
                        >
                          {/* Momentum badge for momentum stocks */}
                          {scannerTab === 'momentum' && stock.higher_highs && (
                            <div className="absolute -top-2 -right-2 text-[10px] bg-orange-500 text-black font-bold px-1.5 py-0.5 rounded">
                              {stock.higher_highs}HH
                            </div>
                          )}
                          {/* Selection Checkbox Indicator */}
                          {isSelected && (
                            <div className="absolute top-1 right-1 w-5 h-5 bg-[#00E599] rounded-full flex items-center justify-center">
                              <svg className="w-3 h-3 text-black" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                              </svg>
                            </div>
                          )}
                          
                          <div className="flex items-center justify-between mb-1">
                            <div className="font-mono font-bold text-white">{stock.symbol}</div>
                            {stock.criteria_count !== undefined && (
                              <div className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                                stock.ready_to_trade 
                                  ? 'bg-[#00E599]/20 text-[#00E599] border border-[#00E599]/30' 
                                  : 'bg-neutral-800 text-neutral-400'
                              }`}>
                                {stock.criteria_count}/5
                              </div>
                            )}
                          </div>
                          <div className="text-xs text-[#00E599]">+{stock.pct_change.toFixed(1)}%</div>
                          <div className="text-xs text-neutral-500">{stock.volume_ratio.toFixed(1)}x vol</div>
                          
                          {/* Spread Warning - Show if spread > 3% */}
                          {(stockData[stock.symbol]?.spread_pct > 3 || stock.spread_pct > 3) && (
                            <div className={`text-[9px] mt-1 px-1.5 py-0.5 rounded ${
                              (stockData[stock.symbol]?.spread_pct || stock.spread_pct) > 5 
                                ? 'bg-red-500/20 text-red-400' 
                                : 'bg-orange-500/20 text-orange-400'
                            }`} title={`Bid: $${(stockData[stock.symbol]?.bid || stock.bid_price || 0).toFixed(2)} | Ask: $${(stockData[stock.symbol]?.ask || stock.ask_price || 0).toFixed(2)}`}>
                              ⚠️ {(stockData[stock.symbol]?.spread_pct || stock.spread_pct || 0).toFixed(1)}% spread
                            </div>
                          )}
                          
                          {/* Criteria Status - Show what's met vs pending */}
                          <div className="mt-2 pt-2 border-t border-white/5">
                            <div className="grid grid-cols-5 gap-0.5">
                              {/* Price Range */}
                              <div className="text-center" title="Price $2-$20">
                                <span className={`text-[10px] ${criteriaMet.price_range ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                  {criteriaMet.price_range ? '✓' : '○'}
                                </span>
                                <div className="text-[8px] text-neutral-600">$</div>
                              </div>
                              {/* % Change */}
                              <div className="text-center" title="Up 10%+">
                                <span className={`text-[10px] ${criteriaMet.pct_change ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                  {criteriaMet.pct_change ? '✓' : '○'}
                                </span>
                                <div className="text-[8px] text-neutral-600">%</div>
                              </div>
                              {/* Volume */}
                              <div className="text-center" title="5x Volume">
                                <span className={`text-[10px] ${criteriaMet.volume_ratio ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                  {criteriaMet.volume_ratio ? '✓' : '○'}
                                </span>
                                <div className="text-[8px] text-neutral-600">Vol</div>
                              </div>
                              {/* Float */}
                              <div className="text-center" title="Float <20M">
                                <span className={`text-[10px] ${criteriaMet.float ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                  {criteriaMet.float ? '✓' : '○'}
                                </span>
                                <div className="text-[8px] text-neutral-600">Flt</div>
                              </div>
                              {/* News */}
                              <div className="text-center" title="Positive News">
                                <span className={`text-[10px] ${criteriaMet.positive_news ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                  {criteriaMet.positive_news ? '✓' : '○'}
                                </span>
                                <div className="text-[8px] text-neutral-600">News</div>
                              </div>
                            </div>
                          </div>
                          
                          {/* News Headlines for 3/5+ stocks */}
                          {stock.criteria_count >= 3 && (stockNews[stock.symbol] || stock.has_positive_news || stock.news_headline) && (
                            <div className="mt-2 pt-2 border-t border-blue-500/20">
                              <div className="text-[9px] text-blue-400 font-bold mb-1 flex items-center gap-1">
                                📰 NEWS
                                {/* News Freshness Badge */}
                                {(stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) && (
                                  <span className={`px-1.5 py-0.5 rounded text-[7px] font-bold uppercase ${
                                    (stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'breaking' 
                                      ? 'bg-red-500/20 text-red-400 animate-pulse' 
                                      : (stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'warm'
                                        ? 'bg-orange-500/20 text-orange-400'
                                        : (stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'cold'
                                          ? 'bg-blue-500/20 text-blue-400'
                                          : 'bg-neutral-500/20 text-neutral-400'
                                  }`}>
                                    {(stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'breaking' ? '🔥 BREAKING' 
                                      : (stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'warm' ? '🌡️ WARM'
                                      : (stock.news_freshness || stockNews[stock.symbol]?.articles?.[0]?.freshness) === 'cold' ? '❄️ COLD'
                                      : ''}
                                  </span>
                                )}
                                {stockNews[stock.symbol]?.last_updated && (
                                  <span className="text-[7px] text-neutral-600 font-normal">
                                    {Math.round((Date.now() - stockNews[stock.symbol].last_updated) / 60000)}m ago
                                  </span>
                                )}
                              </div>
                              {/* Show news from stockNews state (detailed) */}
                              {stockNews[stock.symbol]?.has_news && stockNews[stock.symbol]?.articles?.length > 0 ? (
                                <div className="space-y-1">
                                  {stockNews[stock.symbol].articles.slice(0, 2).map((article, aidx) => (
                                    <a
                                      key={aidx}
                                      href={article.link || article.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="block text-[8px] text-neutral-400 hover:text-blue-400 truncate"
                                      title={`${article.title} (${article.freshness || 'unknown'} - ${article.days_old !== null ? article.days_old + ' days old' : ''})`}
                                    >
                                      {(article.sentiment === 'positive' || article.sentiment === 'strong_catalyst') && <span className="text-[#00E599]">▲</span>}
                                      {article.sentiment === 'negative' && <span className="text-red-500">▼</span>}
                                      {' '}{article.title}
                                    </a>
                                  ))}
                                </div>
                              ) : stock.has_positive_news && stock.news_headline && stock.news_headline !== 'No recent news found' && stock.news_headline !== 'News check pending...' ? (
                                /* Fallback: Show news from scanner data */
                                <div className="text-[8px] text-neutral-400">
                                  <span className="text-[#00E599]">▲</span> {stock.news_headline}
                                </div>
                              ) : (
                                <div className="text-[8px] text-neutral-600">No recent news</div>
                              )}
                            </div>
                          )}
                          
                          {/* Entry Conditions for 3/5+ stocks - Show what auto-trader is waiting for */}
                          {stock.criteria_count >= 3 && (
                            <div className="mt-2 pt-2 border-t border-yellow-500/20">
                              <div className="text-[9px] text-yellow-400 font-bold mb-1">
                                {stock.criteria_count >= 5 ? 'AUTO-TRADE ENTRY:' : 'ENTRY CONDITIONS:'}
                              </div>
                              {entryConditions[stock.symbol] ? (
                                <div className="grid grid-cols-2 gap-1">
                                  {/* Micro Pullback */}
                                  <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.micro_pullback?.detail || ''}>
                                    <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.micro_pullback?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                      {entryConditions[stock.symbol].conditions?.micro_pullback?.met ? '✓' : '⏳'}
                                    </span>
                                    <span className="text-[8px] text-neutral-500">Pullback</span>
                                  </div>
                                  {/* MACD - show crossover or bullish based on settings */}
                                  {entryConditions[stock.symbol].conditions?.macd_crossover ? (
                                    <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.macd_crossover?.detail || ''}>
                                      <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.macd_crossover?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                        {entryConditions[stock.symbol].conditions?.macd_crossover?.met ? '✓' : '⏳'}
                                      </span>
                                      <span className="text-[8px] text-neutral-500">MACD×</span>
                                    </div>
                                  ) : (
                                    <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.macd_bullish?.detail || ''}>
                                      <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.macd_bullish?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                        {entryConditions[stock.symbol].conditions?.macd_bullish?.met ? '✓' : '⏳'}
                                      </span>
                                      <span className="text-[8px] text-neutral-500">MACD</span>
                                    </div>
                                  )}
                                  {/* SMA - show crossover or above based on settings (SMA20 vs SMA50) */}
                                  {entryConditions[stock.symbol].conditions?.sma_crossover ? (
                                    <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.sma_crossover?.detail || ''}>
                                      <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.sma_crossover?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                        {entryConditions[stock.symbol].conditions?.sma_crossover?.met ? '✓' : '⏳'}
                                      </span>
                                      <span className="text-[8px] text-neutral-500">20/50×</span>
                                    </div>
                                  ) : (
                                    <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.above_sma?.detail || ''}>
                                      <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.above_sma?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                        {entryConditions[stock.symbol].conditions?.above_sma?.met ? '✓' : '⏳'}
                                      </span>
                                      <span className="text-[8px] text-neutral-500">20&gt;50</span>
                                    </div>
                                  )}
                                  {/* Bull Flag */}
                                  <div className="flex items-center gap-1" title={entryConditions[stock.symbol].conditions?.bull_flag?.detail || ''}>
                                    <span className={`text-[9px] ${entryConditions[stock.symbol].conditions?.bull_flag?.met ? 'text-[#00E599]' : 'text-neutral-600'}`}>
                                      {entryConditions[stock.symbol].conditions?.bull_flag?.met ? '✓' : '⏳'}
                                    </span>
                                    <span className="text-[8px] text-neutral-500">Flag</span>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-1 text-[8px] text-neutral-500">
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                  <span>Loading...</span>
                                </div>
                              )}
                              {entryConditions[stock.symbol]?.ready_for_auto_trade && (
                                <div className="text-[9px] text-[#00E599] mt-1 font-bold">🚀 AUTO-TRADE READY</div>
                              )}
                              {entryConditions[stock.symbol] && !entryConditions[stock.symbol].is_trading_hours && (
                                <div className="text-[8px] text-yellow-500 mt-1">⏰ Outside Trading Hours (7 AM - 3:30 PM ET)</div>
                              )}
                            </div>
                          )}
                          
                          {stock.ready_to_trade && !entryConditions[stock.symbol] && (
                            <div className="text-[10px] text-[#00E599] mt-2 font-bold text-center">READY TO TRADE ✓</div>
                          )}
                          {hasPosition && (
                            <div className="text-[10px] text-yellow-500 mt-1 text-center">IN POSITION</div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Multi-Chart View - Vertical Stack for Easy Scrolling */}
      {selectedStocks.size > 0 && (
        <div className="flex flex-col gap-4">
          {Array.from(selectedStocks).map((symbol) => {
            // Try to find in scanner results first
            let stock = scannerResults.find(s => s.symbol === symbol);
            
            // If not in scanner results, check momentum stocks
            if (!stock) {
              stock = momentumStocks.find(s => s.symbol === symbol);
            }
            
            // If not in momentum, check positions
            if (!stock) {
              const position = positions.find(p => p.symbol === symbol);
              if (position) {
                stock = {
                  symbol: position.symbol,
                  current_price: position.current_price,
                  pct_change: position.unrealized_plpc || 0,
                  prev_close: position.avg_entry_price,
                  volume_ratio: 0,
                  criteria_count: 0,
                  criteria_met: {}
                };
              }
            }
            
            if (!stock) return null;
            
            const data = stockData[symbol];
            if (!data) return <div key={symbol} className="text-center text-neutral-500">Loading {symbol}...</div>;
            
            // Get the most recent price - PRIORITIZE FRESH QUOTE DATA
            const quote = data.quote;
            // Use mid-price from quote (or bid/ask if one is missing)
            const quotePrice = quote ? (
              (quote.bid_price > 0 && quote.ask_price > 0) 
                ? (quote.bid_price + quote.ask_price) / 2 
                : (quote.bid_price || quote.ask_price || 0)
            ) : 0;
            
            const latestBar5Min = data.bars5Min?.[data.bars5Min.length - 1];
            const latestBar1Min = data.bars1Min?.[data.bars1Min.length - 1];
            
            // Find the real-time bar (marked with realtime: true)
            const realtimeBar5Min = data.bars5Min?.find(b => b.realtime);
            const realtimeBar1Min = data.bars1Min?.find(b => b.realtime);
            
            // Priority: QUOTE (most accurate) > real-time bar > scanner price > latest bar
            const currentPrice = quotePrice > 0 ? quotePrice :
                                 realtimeBar1Min?.close || realtimeBar5Min?.close || 
                                 stock.current_price || 
                                 latestBar1Min?.close || latestBar5Min?.close || 0;
            
            const position = positions.find(p => p.symbol === stock.symbol);
            
            // Calculate % change based on chart data
            const prevClose = stock.prev_close;
            const pctChange = prevClose > 0 ? ((currentPrice - prevClose) / prevClose) * 100 : stock.pct_change;
            
            // Round prices to 2 decimals to prevent micro-changes from causing re-renders
            const roundedPrice = Math.round(currentPrice * 100) / 100;
            const roundedPctChange = Math.round(pctChange * 100) / 100;
            
            // Calculate stop loss and profit target using user's settings
            // If position exists, use actual entry price; otherwise use current price
            const entryPrice = position ? position.avg_entry_price : roundedPrice;
            const calculatedStopLoss = Math.round(entryPrice * (1 - stopLossPct / 100) * 100) / 100;
            const calculatedProfitTarget = Math.round(entryPrice * (1 + takeProfitPct / 100) * 100) / 100;
            
            // Calculate trailing stop based on current price (trails from high)
            const trailingStopPrice = stopType === 'trailing' 
              ? Math.round(roundedPrice * (1 - trailingStopPct / 100) * 100) / 100
              : null;
            
            return (
              <StockChartCard
                key={stock.symbol}
                symbol={stock.symbol}
                currentPrice={roundedPrice}
                pctChange={roundedPctChange}
                stock={stock}
                data={data}
                position={position}
                entry={entryPrice}
                stopLoss={calculatedStopLoss}
                profitTarget={calculatedProfitTarget}
                trailingStop={trailingStopPrice}
                stopLossPct={stopLossPct}
                takeProfitPct={takeProfitPct}
                trailingStopPct={trailingStopPct}
                stopType={stopType}
                onRemove={() => toggleStockSelection(stock.symbol)}
                onTrade={placeOrder}
              />
            );
          })}
        </div>
      )}

      {/* Strategy Reminder */}
      <Card className="bg-[#0A0A0A] border-white/5" data-testid="strategy-reminder-card">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>Strategy Reminder</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-2">Entry Signal</div>
              <div className="text-white mb-2">First Pullback breakout confirmed</div>
              <div className="text-xs text-neutral-500 mb-1">Look for:</div>
              <ul className="text-sm text-neutral-400 space-y-1">
                <li>• Stock already up 10%+ (from scanner, 5/5 criteria)</li>
                <li>• 1-3 red candle pullback, holding 50%+ of the surge</li>
                <li>• Breakout candle breaks the pullback's high</li>
              </ul>
            </div>
            <div className="p-4 bg-[#121212] border border-white/5 rounded-sm">
              <div className="text-xs text-neutral-500 mb-2">Risk Management</div>
              <div className="text-white mb-2">2:1 Risk/Reward Ratio</div>
              <div className="text-xs text-neutral-500 mb-1">Example (stop = low of pullback):</div>
              <div className="text-sm text-neutral-400 space-y-1">
                <div>Entry: <span className="font-mono text-white">$10.00</span></div>
                <div>Stop Loss: <span className="font-mono text-[#FF1A40]">$9.90</span> (structural)</div>
                <div>Target: <span className="font-mono text-[#00E599]">$10.20</span> (2:1)</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}