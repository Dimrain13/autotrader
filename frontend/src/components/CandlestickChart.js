import { useEffect, useRef, memo, useCallback } from 'react';
import { createChart } from 'lightweight-charts';

function CandlestickChart({ data, height = 300, sma20, sma50, vwap, levels, blockTrades, livePrice }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const seriesRefs = useRef({});
  const userHasZoomedRef = useRef(false);
  const isFirstLoadRef = useRef(true);
  const lastBarRef = useRef(null);

  // Effect 1: Create chart once on mount
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
        vertLines: { color: '#333333' },
        horzLines: { color: '#333333' },
      },
      crosshair: {
        mode: 1,
      },
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

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#00E599',
      downColor: '#FF1A40',
      borderVisible: false,
      wickUpColor: '#00E599',
      wickDownColor: '#FF1A40',
    });

    // Add volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#2E5CFF',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    // Store references
    chartRef.current = chart;
    seriesRefs.current.candlestick = candlestickSeries;
    seriesRefs.current.volume = volumeSeries;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    // Track when user manually zooms/pans - this is the key!
    chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      userHasZoomedRef.current = true;
    });

    // Cleanup ONLY on unmount
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        seriesRefs.current = {};
      }
    };
  }, [height]); // Only recreate if height changes

  // Effect 2: Update data without destroying chart
  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;

    const chart = chartRef.current;
    const { candlestick: candlestickSeries, volume: volumeSeries } = seriesRefs.current;
    
    if (!candlestickSeries || !volumeSeries) return;

    // SAVE current visible range BEFORE updating data
    let savedRange = null;
    if (userHasZoomedRef.current) {
      try {
        savedRange = chart.timeScale().getVisibleRange();
      } catch (e) {
        // Range not available
      }
    }

    // Prepare candle data - sort and deduplicate by timestamp
    const candleDataRaw = data
      .map(bar => {
        const timestamp = new Date(bar.timestamp);
        if (isNaN(timestamp.getTime())) return null;
        return {
          time: Math.floor(timestamp.getTime() / 1000),
          open: parseFloat(bar.open),
          high: parseFloat(bar.high),
          low: parseFloat(bar.low),
          close: parseFloat(bar.close),
        };
      })
      .filter(bar => bar !== null)
      .sort((a, b) => a.time - b.time);
    
    // Remove duplicates - keep latest value for each timestamp
    const candleData = candleDataRaw.reduce((acc, bar) => {
      if (acc.length === 0 || acc[acc.length - 1].time < bar.time) {
        acc.push(bar);
      } else if (acc[acc.length - 1].time === bar.time) {
        acc[acc.length - 1] = bar; // Replace with latest
      }
      return acc;
    }, []);

    // Prepare volume data - sort and deduplicate
    const volumeDataRaw = data
      .map(bar => {
        const timestamp = new Date(bar.timestamp);
        if (isNaN(timestamp.getTime())) return null;
        return {
          time: Math.floor(timestamp.getTime() / 1000),
          value: parseFloat(bar.volume),
          color: bar.close >= bar.open ? '#00E59966' : '#FF1A4066',
        };
      })
      .filter(bar => bar !== null)
      .sort((a, b) => a.time - b.time);
    
    // Remove duplicates
    const volumeData = volumeDataRaw.reduce((acc, bar) => {
      if (acc.length === 0 || acc[acc.length - 1].time < bar.time) {
        acc.push(bar);
      } else if (acc[acc.length - 1].time === bar.time) {
        acc[acc.length - 1] = bar;
      }
      return acc;
    }, []);

    // Update main series (this preserves zoom automatically)
    candlestickSeries.setData(candleData);
    volumeSeries.setData(volumeData);
    lastBarRef.current = candleData.length > 0 ? { ...candleData[candleData.length - 1] } : null;

    // Remove old indicator series
    ['sma20', 'sma50', 'vwap', 'entryLine', 'stopLine', 'targetLine', 'trailLine'].forEach(key => {
      if (seriesRefs.current[key]) {
        try {
          chart.removeSeries(seriesRefs.current[key]);
        } catch (e) {}
        seriesRefs.current[key] = null;
      }
    });
    // Block-trade (large order print) support/resistance lines get
    // recreated every update since the count varies
    (seriesRefs.current.blockTradeLines || []).forEach(line => {
      try { chart.removeSeries(line); } catch (e) {}
    });
    seriesRefs.current.blockTradeLines = [];

    // Add SMA20 - LEFT SIDE
    if (candleData.length >= 20) {
      const sma20Series = chart.addLineSeries({
        color: '#2E5CFF',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: 'SMA20',
        priceScaleId: 'left',
      });
      const sma20Data = [];
      for (let i = 19; i < candleData.length; i++) {
        const slice = candleData.slice(i - 19, i + 1);
        const avg = slice.reduce((acc, bar) => acc + bar.close, 0) / 20;
        sma20Data.push({ time: candleData[i].time, value: avg });
      }
      sma20Series.setData(sma20Data);
      seriesRefs.current.sma20 = sma20Series;
    }

    // Add SMA50 - LEFT SIDE
    if (candleData.length >= 50) {
      const sma50Series = chart.addLineSeries({
        color: '#FFB800',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: 'SMA50',
        priceScaleId: 'left',
      });
      const sma50Data = [];
      for (let i = 49; i < candleData.length; i++) {
        const slice = candleData.slice(i - 49, i + 1);
        const avg = slice.reduce((acc, bar) => acc + bar.close, 0) / 50;
        sma50Data.push({ time: candleData[i].time, value: avg });
      }
      sma50Series.setData(sma50Data);
      seriesRefs.current.sma50 = sma50Series;
    }

    // Add VWAP - LEFT SIDE
    if (vwap && candleData.length > 0) {
      const vwapSeries = chart.addLineSeries({
        color: '#9333EA',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: 'VWAP',
        priceScaleId: 'left',
      });
      vwapSeries.setData(candleData.map(c => ({ time: c.time, value: vwap })));
      seriesRefs.current.vwap = vwapSeries;
    }

    // Add trade levels with prominent styling - ON LEFT PRICE SCALE for better candle visibility
    if (levels) {
      // Entry line (white, solid) - LEFT SIDE
      const entryLine = chart.addLineSeries({
        color: '#FFFFFF',
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
        title: 'ENTRY',
        crosshairMarkerVisible: true,
        priceScaleId: 'left',
      });
      entryLine.setData(candleData.map(c => ({ time: c.time, value: levels.entry })));
      seriesRefs.current.entryLine = entryLine;

      // Stop loss line (red, dashed, thicker) - LEFT SIDE
      const stopLine = chart.addLineSeries({
        color: '#FF1A40',
        lineWidth: 3,
        lineStyle: 2, // Dashed
        priceLineVisible: true,
        lastValueVisible: true,
        title: 'STOP',
        crosshairMarkerVisible: true,
        priceScaleId: 'left',
      });
      stopLine.setData(candleData.map(c => ({ time: c.time, value: levels.stopLoss })));
      seriesRefs.current.stopLine = stopLine;

      // Profit Target line (green, dashed, thicker) - LEFT SIDE
      const targetLine = chart.addLineSeries({
        color: '#00E599',
        lineWidth: 3,
        lineStyle: 2, // Dashed
        priceLineVisible: true,
        lastValueVisible: true,
        title: 'TARGET',
        crosshairMarkerVisible: true,
        priceScaleId: 'left',
      });
      targetLine.setData(candleData.map(c => ({ time: c.time, value: levels.profitTarget })));
      seriesRefs.current.targetLine = targetLine;

      // Trailing Stop line (orange, dashed) - LEFT SIDE - only if trailing stop is set
      if (levels.trailingStop) {
        const trailLine = chart.addLineSeries({
          color: '#FF9500', // Orange for trailing
          lineWidth: 3,
          lineStyle: 2, // Dashed
          priceLineVisible: true,
          lastValueVisible: true,
          title: 'TRAIL',
          crosshairMarkerVisible: true,
          priceScaleId: 'left',
        });
        trailLine.setData(candleData.map(c => ({ time: c.time, value: levels.trailingStop })));
        seriesRefs.current.trailLine = trailLine;
      }
    }

    // Block-trade (large order print) support/resistance markers - real
    // trade-tick data, not fabricated: unusually large prints flagged by
    // the backend's tick-rule side detection (buy = potential support,
    // sell = potential resistance around pullbacks/breakouts).
    if (blockTrades && blockTrades.length > 0 && candleData.length > 0) {
      blockTrades.slice(0, 8).forEach((bt, idx) => {
        const line = chart.addLineSeries({
          color: bt.side === 'buy' ? '#00E59988' : bt.side === 'sell' ? '#FF1A4088' : '#A3A3A388',
          lineWidth: 1,
          lineStyle: 3, // dotted
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: `${bt.side === 'buy' ? 'Buy' : bt.side === 'sell' ? 'Sell' : ''} block ${bt.size.toLocaleString()}sh`,
          priceScaleId: 'left',
        });
        line.setData(candleData.map(c => ({ time: c.time, value: bt.price })));
        seriesRefs.current.blockTradeLines.push(line);
      });
    }

    // RESTORE zoom after data update, or fit on first load
    if (userHasZoomedRef.current && savedRange) {
      // User has zoomed - restore their exact view
      try {
        chart.timeScale().setVisibleRange(savedRange);
      } catch (e) {
        console.warn('Could not restore zoom range');
      }
    } else if (isFirstLoadRef.current) {
      // First load only - fit content
      chart.timeScale().fitContent();
      isFirstLoadRef.current = false;
    }
    // Otherwise leave zoom as-is

  }, [data, vwap, levels, blockTrades]); // Update when data changes, but don't destroy chart

  // Effect 3: live tick updates - moves the LAST candle in real-time as new
  // trades stream in over the WebSocket, instead of the chart sitting frozen
  // between periodic REST bar refreshes. Bar-boundary transitions are still
  // reconciled by the next REST refresh (Effect 2), this just fills the gap.
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
