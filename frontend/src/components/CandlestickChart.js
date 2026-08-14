import { useEffect, useRef, memo } from 'react';
import { createChart } from 'lightweight-charts';

/**
 * Optimized CandlestickChart — keeps indicator series alive across updates
 * instead of tearing them down and recreating every render. Uses setData()
 * for incremental updates, sliding-window SMA, and only recreates lines when
 * the underlying value changes (e.g. VWAP, levels).
 */
function CandlestickChart({ data, height = 300, sma20, sma50, vwap, levels, blockTrades, livePrice }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const seriesRefs = useRef({});
  const isFollowingRef = useRef(true);
  const suppressRangeEventRef = useRef(false);
  const rangeChangeDebounceRef = useRef(null);
  const isFirstLoadRef = useRef(true);
  const lastBarRef = useRef(null);
  // Track previous values to avoid rebuilding series unnecessarily
  const prevRef = useRef({ vwap: null, levels: null, blockTradeCount: 0 });

  // Effect 1: Create chart once on mount
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        backgroundColor: '#0A0A0A',
        textColor: '#999999',
      },
      grid: {
        vertLines: { color: '#333333' },
        horzLines: { color: '#333333' },
      },
      crosshair: { mode: 1 },
      localization: {
        locale: 'en',
        timeFormatter: (time) => {
          const date = new Date(time * 1000);
          const hours = date.getUTCHours().toString().padStart(2, '0');
          const mins = date.getUTCMinutes().toString().padStart(2, '0');
          return `${hours}:${mins}`;
        },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#444444',
        barSpacing: 8,
        minBarSpacing: 4,
        rightOffset: 5,
      },
      rightPriceScale: {
        borderColor: '#444444',
        visible: true,
      },
      leftPriceScale: {
        borderColor: '#444444',
        visible: true,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#00E599',
      downColor: '#FF1A40',
      borderVisible: false,
      wickUpColor: '#00E599',
      wickDownColor: '#FF1A40',
    });

    const volumeSeries = chart.addHistogramSeries({
      color: '#2E5CFF',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    seriesRefs.current.candlestick = candlestickSeries;
    seriesRefs.current.volume = volumeSeries;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
      if (suppressRangeEventRef.current) return;
      if (rangeChangeDebounceRef.current) clearTimeout(rangeChangeDebounceRef.current);
      rangeChangeDebounceRef.current = setTimeout(() => {
        if (suppressRangeEventRef.current) return;
        let pos = 0;
        try { pos = chart.timeScale().scrollPosition(); } catch (e) {}
        if (pos < -1.5) {
          isFollowingRef.current = false;
        } else {
          isFollowingRef.current = true;
          suppressRangeEventRef.current = true;
          try { chart.timeScale().scrollToRealTime(); } catch (e) {}
          requestAnimationFrame(() => { suppressRangeEventRef.current = false; });
        }
      }, 200);
    });

    return () => {
      window.removeEventListener('resize', handleResize);
      if (rangeChangeDebounceRef.current) clearTimeout(rangeChangeDebounceRef.current);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        seriesRefs.current = {};
      }
    };
  }, [height]);

  // Helper: prepare candle/volume arrays (sorted, deduplicated)
  const prepareData = (rawData) => {
    if (!rawData || rawData.length === 0) return { candleData: [], volumeData: [] };

    const parsed = rawData
      .map(bar => {
        const timestamp = new Date(bar.timestamp);
        if (isNaN(timestamp.getTime())) return null;
        return {
          time: Math.floor(timestamp.getTime() / 1000),
          open: parseFloat(bar.open),
          high: parseFloat(bar.high),
          low: parseFloat(bar.low),
          close: parseFloat(bar.close),
          volume: parseFloat(bar.volume),
          up: bar.close >= bar.open,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    // Deduplicate
    const candleData = [];
    for (const bar of parsed) {
      if (candleData.length === 0 || candleData[candleData.length - 1].time < bar.time) {
        candleData.push(bar);
      } else if (candleData[candleData.length - 1].time === bar.time) {
        candleData[candleData.length - 1] = bar;
      }
    }

    const volumeData = candleData.map(b => ({
      time: b.time,
      value: b.volume,
      color: b.up ? '#00E59966' : '#FF1A4066',
    }));

    return { candleData, volumeData };
  };

  // Helper: sliding-window SMA (O(n) instead of O(n*k))
  const computeSMA = (candleData, period) => {
    if (candleData.length < period) return [];
    const result = [];
    let sum = 0;
    for (let i = 0; i < period; i++) sum += candleData[i].close;
    result.push({ time: candleData[period - 1].time, value: sum / period });
    for (let i = period; i < candleData.length; i++) {
      sum += candleData[i].close - candleData[i - period].close;
      result.push({ time: candleData[i].time, value: sum / period });
    }
    return result;
  };

  // Effect 2: Update data (candles, volume, indicators)
  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;

    const chart = chartRef.current;
    const { candlestick: candlestickSeries, volume: volumeSeries } = seriesRefs.current;
    if (!candlestickSeries || !volumeSeries) return;

    const { candleData, volumeData } = prepareData(data);
    if (candleData.length === 0) return;

    // Update main series (setData is incremental if series exists)
    candlestickSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    lastBarRef.current = { ...candleData[candleData.length - 1] };

    // --- SMA20: create once, update with setData ---
    if (candleData.length >= 20) {
      if (!seriesRefs.current.sma20) {
        seriesRefs.current.sma20 = chart.addLineSeries({
          color: '#2E5CFF', lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: 'SMA20', priceScaleId: 'left',
        });
      }
      seriesRefs.current.sma20.setData(computeSMA(candleData, 20));
    } else {
      if (seriesRefs.current.sma20) {
        try { chart.removeSeries(seriesRefs.current.sma20); } catch (e) {}
        seriesRefs.current.sma20 = null;
      }
    }

    // --- SMA50: create once, update with setData ---
    if (candleData.length >= 50) {
      if (!seriesRefs.current.sma50) {
        seriesRefs.current.sma50 = chart.addLineSeries({
          color: '#FFB800', lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: 'SMA50', priceScaleId: 'left',
        });
      }
      seriesRefs.current.sma50.setData(computeSMA(candleData, 50));
    } else {
      if (seriesRefs.current.sma50) {
        try { chart.removeSeries(seriesRefs.current.sma50); } catch (e) {}
        seriesRefs.current.sma50 = null;
      }
    }

    // --- VWAP: only rebuild series if value changed ---
    if (vwap && candleData.length > 0) {
      const vwapData = candleData.map(c => ({ time: c.time, value: vwap }));
      if (prevRef.current.vwap !== vwap || !seriesRefs.current.vwap) {
        // VWAP value changed — recreate series
        if (seriesRefs.current.vwap) {
          try { chart.removeSeries(seriesRefs.current.vwap); } catch (e) {}
        }
        seriesRefs.current.vwap = chart.addLineSeries({
          color: '#9333EA', lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: 'VWAP', priceScaleId: 'left',
        });
        prevRef.current.vwap = vwap;
      }
      seriesRefs.current.vwap.setData(vwapData);
    } else {
      if (seriesRefs.current.vwap) {
        try { chart.removeSeries(seriesRefs.current.vwap); } catch (e) {}
        seriesRefs.current.vwap = null;
        prevRef.current.vwap = null;
      }
    }

    // --- Trade levels (entry, stop, target, trail) ---
    const levelsChanged = JSON.stringify(levels) !== JSON.stringify(prevRef.current.levels);

    const levelDefs = [];
    if (levels) {
      levelDefs.push({ key: 'entryLine', color: '#FFFFFF', width: 2, title: 'ENTRY', value: levels.entry });
      levelDefs.push({ key: 'stopLine', color: '#FF1A40', width: 3, lineStyle: 2, title: 'STOP', value: levels.stopLoss });
      levelDefs.push({ key: 'targetLine', color: '#00E599', width: 3, lineStyle: 2, title: 'TARGET', value: levels.profitTarget });
      if (levels.psychTarget) {
        levelDefs.push({ key: 'psychLine', color: '#00E599', width: 2, lineStyle: 3, title: '1ST TARGET', value: levels.psychTarget });
      }
      if (levels.trailingStop) {
        levelDefs.push({ key: 'trailLine', color: '#FF9500', width: 3, lineStyle: 2, title: 'TRAIL', value: levels.trailingStop });
      }
    }

    // Remove level lines that no longer exist
    for (const key of ['entryLine', 'stopLine', 'targetLine', 'trailLine', 'psychLine']) {
      if (!levelDefs.find(d => d.key === key) && seriesRefs.current[key]) {
        try { chart.removeSeries(seriesRefs.current[key]); } catch (e) {}
        seriesRefs.current[key] = null;
      }
    }

    // Create or update level lines
    for (const def of levelDefs) {
      const lineData = candleData.map(c => ({ time: c.time, value: def.value }));
      if (!seriesRefs.current[def.key] || levelsChanged) {
        if (seriesRefs.current[def.key]) {
          try { chart.removeSeries(seriesRefs.current[def.key]); } catch (e) {}
        }
        seriesRefs.current[def.key] = chart.addLineSeries({
          color: def.color, lineWidth: def.width,
          lineStyle: def.lineStyle || 0,
          priceLineVisible: true, lastValueVisible: true,
          title: def.title, crosshairMarkerVisible: true,
          priceScaleId: 'left',
        });
      }
      seriesRefs.current[def.key].setData(lineData);
    }
    prevRef.current.levels = levels ? JSON.parse(JSON.stringify(levels)) : null;

    // --- Block trade lines ---
    const btCount = blockTrades ? blockTrades.length : 0;
    if (btCount !== prevRef.current.blockTradeCount) {
      // Count changed — rebuild
      (seriesRefs.current.blockTradeLines || []).forEach(line => {
        try { chart.removeSeries(line); } catch (e) {}
      });
      seriesRefs.current.blockTradeLines = [];

      if (blockTrades && blockTrades.length > 0 && candleData.length > 0) {
        blockTrades.slice(0, 8).forEach(bt => {
          const line = chart.addLineSeries({
            color: bt.side === 'buy' ? '#00E59988' : bt.side === 'sell' ? '#FF1A4088' : '#A3A3A388',
            lineWidth: 1, lineStyle: 3,
            priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: `${bt.side === 'buy' ? 'Buy' : bt.side === 'sell' ? 'Sell' : ''} block ${bt.size.toLocaleString()}sh`,
            priceScaleId: 'left',
          });
          line.setData(candleData.map(c => ({ time: c.time, value: bt.price })));
          seriesRefs.current.blockTradeLines.push(line);
        });
      }
      prevRef.current.blockTradeCount = btCount;
    }

    // Scroll handling
    if (isFirstLoadRef.current) {
      chart.timeScale().fitContent();
      isFirstLoadRef.current = false;
    } else if (isFollowingRef.current) {
      suppressRangeEventRef.current = true;
      try { chart.timeScale().scrollToRealTime(); } catch (e) {}
      requestAnimationFrame(() => { suppressRangeEventRef.current = false; });
    }

  }, [data, vwap, levels, blockTrades]);

  // Effect 3: live tick updates
  useEffect(() => {
    if (!livePrice || !livePrice.price || !seriesRefs.current.candlestick || !lastBarRef.current) return;
    const bar = lastBarRef.current;
    const newClose = livePrice.price;
    const updated = {
      time: bar.time,
      open: bar.open,
      high: Math.max(bar.high, newClose),
      low: Math.min(bar.low, newClose),
      close: newClose,
    };
    lastBarRef.current = updated;
    try {
      seriesRefs.current.candlestick.update(updated);
    } catch (e) {}
  }, [livePrice]);

  return <div ref={chartContainerRef} style={{ position: 'relative', width: '100%' }} />;
}

export default memo(CandlestickChart);