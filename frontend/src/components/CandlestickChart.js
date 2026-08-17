import { useEffect, useRef, memo, useState, useCallback } from 'react';
import { createChart } from 'lightweight-charts';

function CandlestickChart({ data, height = 300, sma20, sma50, vwap, levels, blockTrades, livePrice, symbol }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const seriesRefs = useRef({});
  const isFollowingRef = useRef(true);
  const suppressRangeEventRef = useRef(false);
  const rangeChangeDebounceRef = useRef(null);
  const isFirstLoadRef = useRef(true);
  const lastBarRef = useRef(null);
  const prevRef = useRef({ vwap: null, levels: null, blockTradeCount: 0 });
  const [crosshair, setCrosshair] = useState(null);

  const handleCrosshairMove = useCallback((param) => {
    if (!param.time || !param.point || param.seriesData.size === 0) {
      setCrosshair(null);
      return;
    }
    const candle = param.seriesData.get(seriesRefs.current.candlestick);
    if (!candle) { setCrosshair(null); return; }
    setCrosshair({
      x: param.point.x,
      y: param.point.y,
      time: param.time,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    });
  }, []);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    const container = chartContainerRef.current;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: height,
      layout: {
        background: { type: 'solid', color: '#0D1117' },
        textColor: '#8b949e',
      },
      grid: {
        vertLines: { color: '#21262d', style: 1 },
        horzLines: { color: '#21262d', style: 1 },
      },
      crosshair: { mode: 1 },
      localization: {
        locale: 'en',
        timeFormatter: (time) => {
          const d = new Date(time * 1000);
          return new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          }).format(d);
        },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => {
          const d = new Date(time * 1000);
          if (tickMarkType === 3 || tickMarkType === 4) {
            return new Intl.DateTimeFormat('en-US', {
              timeZone: 'America/New_York',
              hour: '2-digit', minute: '2-digit', hour12: false,
            }).format(d);
          }
          return new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            month: 'short', day: 'numeric',
          }).format(d);
        },
        borderColor: '#30363d',
        barSpacing: 8,
        minBarSpacing: 4,
        rightOffset: 6,
      },
      rightPriceScale: {
        borderColor: '#30363d',
        autoScale: true,
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      leftPriceScale: {
        borderColor: '#30363d',
        autoScale: true,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      priceScaleId: 'right',
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    chartRef.current = chart;
    seriesRefs.current.candlestick = candlestickSeries;
    seriesRefs.current.volume = volumeSeries;

    chart.subscribeCrosshairMove(handleCrosshairMove);

    const handleResize = () => {
      if (container && chartRef.current) {
        chartRef.current.applyOptions({ width: container.clientWidth });
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
        if (pos < -0.5) {
          isFollowingRef.current = false;
        } else {
          isFollowingRef.current = true;
          suppressRangeEventRef.current = true;
          try { chart.timeScale().scrollToRealTime(); } catch (e) {}
          requestAnimationFrame(() => { suppressRangeEventRef.current = false; });
        }
      }, 150);
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
  }, [height, handleCrosshairMove]);

  const prepareData = (rawData) => {
    if (!rawData || rawData.length === 0) return { candleData: [], volumeData: [] };
    const parsed = rawData
      .map(bar => {
        const ts = new Date(bar.timestamp);
        if (isNaN(ts.getTime())) return null;
        return {
          time: Math.floor(ts.getTime() / 1000),
          open: +bar.open, high: +bar.high, low: +bar.low, close: +bar.close,
          volume: +bar.volume, up: bar.close >= bar.open,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    const candleData = [];
    for (const b of parsed) {
      const last = candleData[candleData.length - 1];
      if (!last || last.time < b.time) candleData.push(b);
      else if (last.time === b.time) candleData[candleData.length - 1] = b;
    }

    const volumeData = candleData.map(b => ({
      time: b.time,
      value: b.volume,
      color: b.up ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)',
    }));

    return { candleData, volumeData };
  };

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

  const formatPrice = (price) => {
    if (price == null) return '';
    if (price < 1) return price.toFixed(4);
    if (price < 10) return price.toFixed(3);
    if (price < 100) return price.toFixed(2);
    return price.toFixed(2);
  };

  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;
    const chart = chartRef.current;
    const { candlestick: cs, volume: vs } = seriesRefs.current;
    if (!cs || !vs) return;

    const { candleData, volumeData } = prepareData(data);
    if (candleData.length === 0) return;

    cs.setData(candleData);
    vs.setData(volumeData);
    const lastCandle = candleData[candleData.length - 1];
    lastBarRef.current = { ...lastCandle };

    // --- Last-price dotted line ---
    const lastPrice = lastCandle.close;
    if (lastPrice) {
      const priceLineData = [
        { time: candleData[0].time, value: lastPrice },
        { time: lastCandle.time, value: lastPrice },
      ];
      if (!seriesRefs.current.lastPriceLine) {
        seriesRefs.current.lastPriceLine = chart.addLineSeries({
          color: '#8b949e',
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: 'right',
        });
      }
      seriesRefs.current.lastPriceLine.setData(priceLineData);
      seriesRefs.current.lastPriceLine.applyOptions({
        priceFormat: { type: 'price', precision: lastPrice < 1 ? 4 : 2, minMove: lastPrice < 1 ? 0.0001 : 0.01 },
      });
    }

    // --- SMA20 ---
    if (candleData.length >= 20) {
      if (!seriesRefs.current.sma20) {
        seriesRefs.current.sma20 = chart.addLineSeries({
          color: '#58a6ff', lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: 'SMA20', priceScaleId: 'right',
          priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        });
      }
      seriesRefs.current.sma20.setData(computeSMA(candleData, 20));
    } else {
      if (seriesRefs.current.sma20) { try { chart.removeSeries(seriesRefs.current.sma20); } catch (e) {} seriesRefs.current.sma20 = null; }
    }

    // --- SMA50 ---
    if (candleData.length >= 50) {
      if (!seriesRefs.current.sma50) {
        seriesRefs.current.sma50 = chart.addLineSeries({
          color: '#d2a8ff', lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: 'SMA50', priceScaleId: 'right',
          priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        });
      }
      seriesRefs.current.sma50.setData(computeSMA(candleData, 50));
    } else {
      if (seriesRefs.current.sma50) { try { chart.removeSeries(seriesRefs.current.sma50); } catch (e) {} seriesRefs.current.sma50 = null; }
    }

    // --- VWAP ---
    if (vwap && candleData.length > 0) {
      const vwapData = candleData.map(c => ({ time: c.time, value: vwap }));
      if (prevRef.current.vwap !== vwap || !seriesRefs.current.vwap) {
        if (seriesRefs.current.vwap) { try { chart.removeSeries(seriesRefs.current.vwap); } catch (e) {} }
        seriesRefs.current.vwap = chart.addLineSeries({
          color: '#f0883e', lineWidth: 2, lineStyle: 3, priceLineVisible: false,
          lastValueVisible: true, title: 'VWAP', priceScaleId: 'right',
          priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        });
        prevRef.current.vwap = vwap;
      }
      seriesRefs.current.vwap.setData(vwapData);
    } else {
      if (seriesRefs.current.vwap) { try { chart.removeSeries(seriesRefs.current.vwap); } catch (e) {} seriesRefs.current.vwap = null; prevRef.current.vwap = null; }
    }

    // --- Trade levels ---
    const levelsChanged = JSON.stringify(levels) !== JSON.stringify(prevRef.current.levels);
    const levelDefs = [];
    if (levels) {
      if (levels.entry)   levelDefs.push({ key: 'entryLine',  color: '#e6edf3', w: 2, s: 0, title: 'ENTRY',  value: levels.entry });
      if (levels.stopLoss) levelDefs.push({ key: 'stopLine',   color: '#ef5350', w: 3, s: 2, title: 'STOP',   value: levels.stopLoss });
      if (levels.profitTarget) levelDefs.push({ key: 'targetLine', color: '#26a69a', w: 3, s: 2, title: 'TARGET', value: levels.profitTarget });
      if (levels.psychTarget) levelDefs.push({ key: 'psychLine',  color: '#26a69a', w: 2, s: 3, title: '1ST TARGET', value: levels.psychTarget });
      if (levels.trailingStop) levelDefs.push({ key: 'trailLine', color: '#f0883e', w: 3, s: 2, title: 'TRAIL', value: levels.trailingStop });
    }

    for (const key of ['entryLine','stopLine','targetLine','trailLine','psychLine']) {
      if (!levelDefs.find(d => d.key === key) && seriesRefs.current[key]) {
        try { chart.removeSeries(seriesRefs.current[key]); } catch (e) {}
        seriesRefs.current[key] = null;
      }
    }

    for (const def of levelDefs) {
      const lineData = candleData.map(c => ({ time: c.time, value: def.value }));
      if (!seriesRefs.current[def.key] || levelsChanged) {
        if (seriesRefs.current[def.key]) { try { chart.removeSeries(seriesRefs.current[def.key]); } catch (e) {} }
        seriesRefs.current[def.key] = chart.addLineSeries({
          color: def.color, lineWidth: def.w, lineStyle: def.s,
          priceLineVisible: true, lastValueVisible: true,
          title: def.title, priceScaleId: 'right',
          priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        });
      }
      seriesRefs.current[def.key].setData(lineData);
    }
    prevRef.current.levels = levels ? JSON.parse(JSON.stringify(levels)) : null;

    // --- Block trade lines ---
    const btCount = blockTrades ? blockTrades.length : 0;
    if (btCount !== prevRef.current.blockTradeCount) {
      (seriesRefs.current.blockTradeLines || []).forEach(line => { try { chart.removeSeries(line); } catch (e) {} });
      seriesRefs.current.blockTradeLines = [];
      if (blockTrades && blockTrades.length > 0 && candleData.length > 0) {
        blockTrades.slice(0, 8).forEach(bt => {
          const line = chart.addLineSeries({
            color: bt.side === 'buy' ? 'rgba(38,166,154,0.6)' : bt.side === 'sell' ? 'rgba(239,83,80,0.6)' : 'rgba(139,148,158,0.6)',
            lineWidth: 1, lineStyle: 3,
            priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: `${bt.side || ''} block ${bt.size?.toLocaleString() || 0}sh`,
            priceScaleId: 'right',
          });
          line.setData(candleData.map(c => ({ time: c.time, value: bt.price })));
          seriesRefs.current.blockTradeLines.push(line);
        });
      }
      prevRef.current.blockTradeCount = btCount;
    }

    // Auto-follow & first load
    if (isFirstLoadRef.current) {
      chart.timeScale().fitContent();
      isFirstLoadRef.current = false;
    } else if (isFollowingRef.current) {
      suppressRangeEventRef.current = true;
      try { chart.timeScale().scrollToRealTime(); } catch (e) {}
      requestAnimationFrame(() => { suppressRangeEventRef.current = false; });
    }
  }, [data, vwap, levels, blockTrades]);

  // Live tick overlay
  useEffect(() => {
    if (!livePrice?.price || !seriesRefs.current.candlestick || !lastBarRef.current) return;
    const bar = lastBarRef.current;
    const c = livePrice.price;
    seriesRefs.current.candlestick.update({
      time: bar.time, open: bar.open,
      high: Math.max(bar.high, c), low: Math.min(bar.low, c), close: c,
    });
    lastBarRef.current = { time: bar.time, open: bar.open, high: Math.max(bar.high, c), low: Math.min(bar.low, c), close: c };
  }, [livePrice]);

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div ref={chartContainerRef} style={{ width: '100%' }} />
      {/* Watermark */}
      {symbol && (
        <div style={{
          position: 'absolute', top: 8, left: 12,
          fontSize: 14, fontWeight: 700, fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
          color: 'rgba(255,255,255,0.12)', letterSpacing: 1,
          pointerEvents: 'none', userSelect: 'none',
        }}>
          {symbol}
        </div>
      )}
      {/* Crosshair tooltip */}
      {crosshair && (
        <div style={{
          position: 'absolute',
          left: Math.min(crosshair.x + 12, (chartContainerRef.current?.clientWidth || 400) - 150),
          top: Math.max(crosshair.y - 60, 4),
          background: '#161b22',
          border: '1px solid #30363d',
          borderRadius: 6,
          padding: '5px 8px',
          fontSize: 11,
          fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
          color: '#e6edf3',
          pointerEvents: 'none',
          zIndex: 10,
          lineHeight: '1.5',
        }}>
          <div>O {formatPrice(crosshair.open)}  H {formatPrice(crosshair.high)}</div>
          <div>L {formatPrice(crosshair.low)}  C <span style={{ color: crosshair.close >= crosshair.open ? '#26a69a' : '#ef5350' }}>{formatPrice(crosshair.close)}</span></div>
        </div>
      )}
    </div>
  );
}

export default memo(CandlestickChart);