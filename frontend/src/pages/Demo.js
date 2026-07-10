import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle, TrendingUp, Volume2, DollarSign, Newspaper, CheckCircle, Target, Shield } from "lucide-react";
import { createChart } from 'lightweight-charts';

// Demo chart component showing trading indicators
function DemoChart({ height = 400 }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        backgroundColor: '#0A0A0A',
        textColor: '#999999',
      },
      grid: {
        vertLines: { color: '#222222' },
        horzLines: { color: '#222222' },
      },
      crosshair: { mode: 1 },
      localization: {
        locale: 'en',
        timeFormatter: (time) => {
          const date = new Date(time * 1000);
          return date.toUTCString().slice(17, 22);
        },
      },
      timeScale: {
        borderColor: '#333333',
        barSpacing: 12,
        minBarSpacing: 6,
      },
      rightPriceScale: {
        borderColor: '#333333',
      },
    });

    chartRef.current = chart;

    // Generate demo data showing a bull flag pattern
    // Use simple incrementing business day format for time
    const baseTime = Math.floor(Date.now() / 1000) - (50 * 300); // Start 50 bars ago
    const candleData = [];
    const volumeData = [];
    
    // Phase 1: Pre-rally (bars 0-10)
    let price = 8.50;
    for (let i = 0; i < 10; i++) {
      const time = baseTime + (i * 300);
      const change = (Math.random() - 0.5) * 0.1;
      const open = price;
      const close = price + change;
      const high = Math.max(open, close) + Math.random() * 0.05;
      const low = Math.min(open, close) - Math.random() * 0.05;
      price = close;
      candleData.push({ time, open, high, low, close });
      volumeData.push({ time, value: 50000 + Math.random() * 30000, color: close > open ? '#00E59966' : '#FF1A4066' });
    }

    // Phase 2: Initial Rally (bars 10-20) - Strong uptrend
    for (let i = 10; i < 20; i++) {
      const time = baseTime + (i * 300);
      const change = 0.15 + Math.random() * 0.1; // Strong bullish
      const open = price;
      const close = price + change;
      const high = close + Math.random() * 0.08;
      const low = open - Math.random() * 0.03;
      price = close;
      candleData.push({ time, open, high, low, close });
      volumeData.push({ time, value: 150000 + Math.random() * 100000, color: '#00E59966' }); // High volume
    }

    // Phase 3: Bull Flag Consolidation (bars 20-35) - Tight range, lower volume
    const flagHigh = price;
    const flagLow = price - 0.3;
    for (let i = 20; i < 35; i++) {
      const time = baseTime + (i * 300);
      // Slight downward drift in consolidation
      const drift = -0.02;
      const change = drift + (Math.random() - 0.5) * 0.08;
      const open = price;
      const close = Math.max(flagLow, Math.min(flagHigh, price + change));
      const high = Math.min(flagHigh, Math.max(open, close) + Math.random() * 0.03);
      const low = Math.max(flagLow, Math.min(open, close) - Math.random() * 0.03);
      price = close;
      candleData.push({ time, open, high, low, close });
      volumeData.push({ time, value: 30000 + Math.random() * 20000, color: close > open ? '#00E59966' : '#FF1A4066' }); // Low volume
    }

    // Phase 4: Breakout (bars 35-45) - Break above flag
    for (let i = 35; i < 45; i++) {
      const time = baseTime + (i * 300);
      const change = 0.12 + Math.random() * 0.08; // Breakout candles
      const open = price;
      const close = price + change;
      const high = close + Math.random() * 0.05;
      const low = open - Math.random() * 0.02;
      price = close;
      candleData.push({ time, open, high, low, close });
      volumeData.push({ time, value: 180000 + Math.random() * 120000, color: '#00E59966' }); // Very high volume
    }

    // Phase 5: Continuation (bars 45-50)
    for (let i = 45; i < 50; i++) {
      const time = baseTime + (i * 300);
      const change = 0.05 + Math.random() * 0.1;
      const open = price;
      const close = price + change;
      const high = close + Math.random() * 0.04;
      const low = open - Math.random() * 0.03;
      price = close;
      candleData.push({ time, open, high, low, close });
      volumeData.push({ time, value: 100000 + Math.random() * 80000, color: '#00E59966' });
    }

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#00E599',
      downColor: '#FF1A40',
      borderVisible: false,
      wickUpColor: '#00E599',
      wickDownColor: '#FF1A40',
    });
    candlestickSeries.setData(candleData);

    // Add volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#2E5CFF',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeries.setData(volumeData);

    // Calculate and add SMA 20
    const sma20Data = [];
    for (let i = 19; i < candleData.length; i++) {
      const slice = candleData.slice(i - 19, i + 1);
      const avg = slice.reduce((acc, bar) => acc + bar.close, 0) / 20;
      sma20Data.push({ time: candleData[i].time, value: avg });
    }
    const sma20Series = chart.addLineSeries({
      color: '#2E5CFF',
      lineWidth: 2,
      title: 'SMA20',
    });
    sma20Series.setData(sma20Data);

    // Calculate and add SMA 50 (using available data)
    const sma50Data = [];
    for (let i = 19; i < candleData.length; i++) {
      const slice = candleData.slice(Math.max(0, i - 49), i + 1);
      const avg = slice.reduce((acc, bar) => acc + bar.close, 0) / slice.length;
      sma50Data.push({ time: candleData[i].time, value: avg });
    }
    const sma50Series = chart.addLineSeries({
      color: '#FFB800',
      lineWidth: 2,
      title: 'SMA50',
    });
    sma50Series.setData(sma50Data);

    // Entry line (at breakout point)
    const entryPrice = candleData[35].close;
    const entryLine = chart.addLineSeries({
      color: '#FFFFFF',
      lineWidth: 2,
      lineStyle: 0,
      title: 'ENTRY',
    });
    entryLine.setData(candleData.slice(35).map(c => ({ time: c.time, value: entryPrice })));

    // Stop Loss line (1% below entry)
    const stopLoss = entryPrice * 0.99;
    const stopLine = chart.addLineSeries({
      color: '#FF1A40',
      lineWidth: 2,
      lineStyle: 2,
      title: 'STOP -1%',
    });
    stopLine.setData(candleData.slice(35).map(c => ({ time: c.time, value: stopLoss })));

    // Take Profit line (2% above entry)
    const takeProfit = entryPrice * 1.02;
    const targetLine = chart.addLineSeries({
      color: '#00E599',
      lineWidth: 2,
      lineStyle: 2,
      title: 'TARGET +2%',
    });
    targetLine.setData(candleData.slice(35).map(c => ({ time: c.time, value: takeProfit })));

    // Add markers for key points
    candlestickSeries.setMarkers([
      {
        time: candleData[10].time,
        position: 'belowBar',
        color: '#2E5CFF',
        shape: 'arrowUp',
        text: 'Rally Start',
      },
      {
        time: candleData[20].time,
        position: 'aboveBar',
        color: '#FFB800',
        shape: 'circle',
        text: 'Flag Forms',
      },
      {
        time: candleData[35].time,
        position: 'belowBar',
        color: '#00E599',
        shape: 'arrowUp',
        text: 'BREAKOUT - BUY',
      },
    ]);

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    chart.timeScale().fitContent();

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [height]);

  return <div ref={chartContainerRef} style={{ position: 'relative', width: '100%' }} />;
}

export default function Demo() {
  const demoStock = {
    symbol: "DEMO",
    entry: 10.50,
    stopLoss: 10.40,
    target: 10.71,
    currentPrice: 10.65,
    pctChange: 12.5,
    volume: 2500000,
    avgVolume: 450000,
    relVolume: 5.6,
    float: 15.2,
  };

  return (
    <div className="space-y-4 px-2 sm:px-0">
      {/* Demo Notice */}
      <Card className="bg-[#0A0A0A] border-yellow-500/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold flex items-center gap-2" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <AlertCircle className="text-yellow-500" size={20} />
            Demo Mode - Bull Flag Breakout Strategy
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs sm:text-sm text-yellow-500">
            This demo shows a typical bull flag pattern setup with entry, stop loss, and profit targets using the Warrior Trading quick scalp approach.
          </p>
        </CardContent>
      </Card>

      {/* Chart with Trade Levels */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold flex items-center justify-between" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <span>DEMO - Bull Flag Breakout</span>
            <span className="text-[#00E599] font-mono text-lg">+{demoStock.pctChange}%</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-2 sm:p-4">
          {/* Trade Info - Mobile Responsive Grid */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-4 text-xs">
            <div className="bg-[#121212] p-2 rounded border border-white/5">
              <div className="text-neutral-500">Entry</div>
              <div className="text-white font-mono">${demoStock.entry.toFixed(2)}</div>
            </div>
            <div className="bg-[#121212] p-2 rounded border border-[#FF1A40]/30">
              <div className="text-[#FF1A40]">Stop -1%</div>
              <div className="text-[#FF1A40] font-mono">${demoStock.stopLoss.toFixed(2)}</div>
            </div>
            <div className="bg-[#121212] p-2 rounded border border-[#00E599]/30">
              <div className="text-[#00E599]">Target +2%</div>
              <div className="text-[#00E599] font-mono">${demoStock.target.toFixed(2)}</div>
            </div>
            <div className="bg-[#121212] p-2 rounded border border-white/5">
              <div className="text-neutral-500">Current</div>
              <div className="text-white font-mono">${demoStock.currentPrice.toFixed(2)}</div>
            </div>
            <div className="bg-[#121212] p-2 rounded border border-[#2E5CFF]/30">
              <div className="text-[#2E5CFF]">Rel Vol</div>
              <div className="text-[#2E5CFF] font-mono">{demoStock.relVolume}x</div>
            </div>
            <div className="bg-[#121212] p-2 rounded border border-white/5">
              <div className="text-neutral-500">Float</div>
              <div className="text-white font-mono">{demoStock.float}M</div>
            </div>
          </div>

          {/* Chart */}
          <div className="border border-white/5 rounded">
            <DemoChart height={350} />
          </div>

          {/* Chart Legend - Mobile Responsive */}
          <div className="flex flex-wrap gap-2 sm:gap-4 mt-3 text-xs">
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-[#2E5CFF] rounded-sm"></div>
              <span className="text-neutral-400">SMA20</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-[#FFB800] rounded-sm"></div>
              <span className="text-neutral-400">SMA50</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5 bg-white"></div>
              <span className="text-neutral-400">Entry</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5 bg-[#FF1A40] border-dashed"></div>
              <span className="text-neutral-400">Stop Loss</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-0.5 bg-[#00E599] border-dashed"></div>
              <span className="text-neutral-400">Target</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 5 Criteria Cards - Mobile Responsive */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            5 Criteria for Entry
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            <div className="p-3 bg-[#121212] border border-[#00E599]/20 rounded-sm">
              <CheckCircle className="text-[#00E599] mb-2" size={16} />
              <div className="text-neutral-500 text-xs mb-1">Criteria 1</div>
              <div className="text-[#00E599] font-mono text-xs">✓ Up 10%+</div>
            </div>
            <div className="p-3 bg-[#121212] border border-[#00E599]/20 rounded-sm">
              <CheckCircle className="text-[#00E599] mb-2" size={16} />
              <div className="text-neutral-500 text-xs mb-1">Criteria 2</div>
              <div className="text-[#00E599] font-mono text-xs">✓ 5x Volume</div>
            </div>
            <div className="p-3 bg-[#121212] border border-[#00E599]/20 rounded-sm">
              <CheckCircle className="text-[#00E599] mb-2" size={16} />
              <div className="text-neutral-500 text-xs mb-1">Criteria 3</div>
              <div className="text-[#00E599] font-mono text-xs">✓ $2-$20</div>
            </div>
            <div className="p-3 bg-[#121212] border border-[#00E599]/20 rounded-sm">
              <CheckCircle className="text-[#00E599] mb-2" size={16} />
              <div className="text-neutral-500 text-xs mb-1">Criteria 4</div>
              <div className="text-[#00E599] font-mono text-xs">✓ News</div>
            </div>
            <div className="p-3 bg-[#121212] border border-[#00E599]/20 rounded-sm col-span-2 sm:col-span-1">
              <CheckCircle className="text-[#00E599] mb-2" size={16} />
              <div className="text-neutral-500 text-xs mb-1">Criteria 5</div>
              <div className="text-[#00E599] font-mono text-xs">✓ &lt;20M Float</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Pattern Explanation - Mobile Optimized */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            Bull Flag Pattern Explained
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs sm:text-sm">
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#2E5CFF]/20 border border-[#2E5CFF] flex items-center justify-center font-bold text-[#2E5CFF] text-xs">
              1
            </div>
            <div>
              <div className="font-bold text-white mb-1">Initial Rally</div>
              <div className="text-neutral-400">Stock gaps up 10%+ on high volume with positive news catalyst.</div>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#FFB800]/20 border border-[#FFB800] flex items-center justify-center font-bold text-[#FFB800] text-xs">
              2
            </div>
            <div>
              <div className="font-bold text-white mb-1">Flag Formation (Consolidation)</div>
              <div className="text-neutral-400">Price consolidates in a tight range on decreasing volume. SMA20 catches up to price.</div>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#00E599]/20 border border-[#00E599] flex items-center justify-center font-bold text-[#00E599] text-xs">
              3
            </div>
            <div>
              <div className="font-bold text-white mb-1">Breakout Entry</div>
              <div className="text-neutral-400">Enter when price breaks above flag resistance with increasing volume. Set 1% stop, 2% target.</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Risk Management */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold flex items-center gap-2" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <Shield size={16} className="text-[#2E5CFF]" />
            Risk Management (2:1 Ratio)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
            <div className="p-3 bg-[#121212] rounded border border-white/5">
              <div className="text-white font-bold mb-2">Entry</div>
              <div className="font-mono text-lg text-white">$10.50</div>
              <div className="text-xs text-neutral-500 mt-1">Buy on breakout above flag</div>
            </div>
            <div className="p-3 bg-[#121212] rounded border border-[#FF1A40]/30">
              <div className="text-[#FF1A40] font-bold mb-2">Stop Loss (-1%)</div>
              <div className="font-mono text-lg text-[#FF1A40]">$10.40</div>
              <div className="text-xs text-neutral-500 mt-1">Risk: $0.10/share</div>
            </div>
            <div className="p-3 bg-[#121212] rounded border border-[#00E599]/30">
              <div className="text-[#00E599] font-bold mb-2">Target (+2%)</div>
              <div className="font-mono text-lg text-[#00E599]">$10.71</div>
              <div className="text-xs text-neutral-500 mt-1">Reward: $0.21/share</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
