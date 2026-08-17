import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle, Lightbulb } from "lucide-react";
import { createChart } from 'lightweight-charts';

// Palette synced with CandlestickChart.js / Trading.js (see skill: Demo chart palette sync)
const UP = '#26a69a';
const DOWN = '#ef5350';
const BG = '#0D1117';
const TEXT = '#6e7681';
const GRID = '#21262d';
const BORDER = '#30363d';
const SMA20_C = '#58a6ff';
const SMA50_C = '#d2a8ff';
const VWAP_C = '#f0b90b';
const WHITE = '#FFFFFF';
const VOL_UP = 'rgba(38,166,154,0.45)';
const VOL_DOWN = 'rgba(239,83,80,0.45)';

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function bar(time, open, close, r, wick) {
  return {
    time,
    open,
    high: Math.max(open, close) + r() * wick,
    low: Math.min(open, close) - r() * wick,
    close,
  };
}

function vol(time, open, close, value) {
  return { time, value, color: close >= open ? VOL_UP : VOL_DOWN };
}

function levelLine(candles, from, value) {
  return candles.slice(from).map(c => ({ time: c.time, value }));
}

// Build the candle sequence + overlays + markers + meta for a given pattern id.
function buildData(pattern) {
  const T0 = Math.floor(Date.now() / 1000) - 50 * 300;
  const candles = [];
  const volume = [];
  const lines = [];
  const markers = [];
  const r = mulberry32((pattern.length * 7919) ^ 0x2F6E2B1);
  let t = T0;

  const push = (open, close, wick, v) => {
    candles.push(bar(t, open, close, r, wick));
    volume.push(vol(t, open, close, v));
    t += 300;
  };
  const addLine = (title, color, style, points) => lines.push({ title, color, lineStyle: style, points });
  const mark = (idx, text, opts = {}) => {
    markers.push({
      time: candles[idx].time,
      position: opts.position || 'belowBar',
      color: opts.color || WHITE,
      shape: opts.shape || 'arrowUp',
      text,
    });
  };

  const meta = { entry: 0, stop: 0, target: 0 };

  switch (pattern) {
    case 'first_pullback': {
      // Surge up, 2-3 red pullback candles holding >=50% of the move, break of prior high.
      let px = 10.00;
      for (let i = 0; i < 8; i++) push(px, px + 0.05, 0.03, 40000), px += 0.05;
      for (let i = 0; i < 8; i++) push(px, px + 0.16, 0.06, 120000), px += 0.16; // surge
      const surgeTop = px;
      // pullback (red, 3 candles, holds ~50%)
      const pullbackLows = [];
      for (let i = 0; i < 3; i++) {
        const c = px - (0.12 + r() * 0.05);
        push(px, c, 0.04, 60000);
        pullbackLows.push(c);
        px = c;
      }
      const pullLow = Math.min(...pullbackLows);
      const priorHigh = surgeTop;
      // break of prior high = entry
      for (let i = 0; i < 2; i++) push(px, px + 0.02, 0.04, 50000), px += 0.02;
      push(px, priorHigh + 0.04, 0.05, 140000); // breakout
      const entry = priorHigh + 0.04;
      px = entry;
      for (let i = 0; i < 8; i++) push(px, px + 0.08, 0.06, 90000), px += 0.08;

      meta.entry = entry; meta.stop = pullLow; meta.target = entry + 2 * (entry - pullLow);
      addLine('ENTRY', WHITE, 0, levelLine(candles, candles.length - 10, entry));
      addLine('STOP (pullback low)', DOWN, 2, levelLine(candles, candles.length - 10, pullLow));
      addLine('TARGET 2:1', UP, 2, levelLine(candles, candles.length - 10, meta.target));
      mark(8, 'Surge');
      mark(19, 'Pullback (holds 50%)', { color: DOWN, shape: 'arrowDown' });
      mark(21, 'BUY on break of high', { color: UP });
      break;
    }

    case 'bull_flag': {
      let px = 8.50;
      for (let i = 0; i < 10; i++) push(px, px + (r() - 0.5) * 0.1, 0.05, 50000), px = candles[candles.length - 1].close;
      for (let i = 0; i < 10; i++) push(px, px + 0.15, 0.08, 150000), px += 0.15; // pole
      const poleTop = px;
      const flagLow = poleTop - 0.30;
      for (let i = 0; i < 15; i++) { // consolidation
        const c = Math.max(flagLow, Math.min(poleTop, px - 0.02 + (r() - 0.5) * 0.06));
        push(px, c, 0.03, 35000);
        px = c;
      }
      const entry = poleTop + 0.02;
      for (let i = 0; i < 10; i++) push(px, px + 0.12, 0.05, 180000), px += 0.12; // breakout
      meta.entry = entry; meta.stop = flagLow; meta.target = entry + 2 * (entry - flagLow);
      addLine('ENTRY', WHITE, 0, levelLine(candles, 35, entry));
      addLine('STOP (flag low)', DOWN, 2, levelLine(candles, 35, flagLow));
      addLine('TARGET 2:1', UP, 2, levelLine(candles, 35, meta.target));
      mark(10, 'Pole surge', { color: SMA20_C });
      mark(25, 'Flag (tight range)', { color: SMA50_C, shape: 'circle' });
      mark(35, 'BREAKOUT - BUY', { color: UP });
      break;
    }

    case 'front_side': {
      // whole-dollar breakout: sub-$1 climbs to $1.00 then breaks $1.10 on volume
      let px = 0.72;
      for (let i = 0; i < 8; i++) push(px, px + 0.02, 0.015, 30000), px += 0.02;
      for (let i = 0; i < 10; i++) push(px, px + 0.03, 0.02, 80000), px += 0.03;
      for (let i = 0; i < 6; i++) push(px, Math.min(1.02, px + (r() - 0.5) * 0.04), 0.02, 50000), px = candles[candles.length - 1].close;
      push(px, 1.12, 0.03, 220000); // whole-dollar breakout
      const entry = 1.12;
      px = entry;
      for (let i = 0; i < 8; i++) push(px, px + 0.05, 0.04, 130000), px += 0.05;
      meta.entry = entry; meta.stop = 1.02; meta.target = entry + 2 * (entry - 1.02);
      addLine('$1.00 level', SMA20_C, 2, levelLine(candles, 0, 1.00));
      addLine('ENTRY', WHITE, 0, levelLine(candles, candles.length - 9, entry));
      addLine('STOP', DOWN, 2, levelLine(candles, candles.length - 9, 1.02));
      mark(24, '$1.00 squeeze', { color: SMA20_C, shape: 'circle' });
      mark(25, 'BUY on $1.10 break', { color: UP });
      break;
    }

    case 'vwap_bounce': {
      let px = 9.50;
      const vwapVals = [];
      for (let i = 0; i < 12; i++) { push(px, px + 0.10, 0.05, 90000); px += 0.10; vwapVals.push(px); }
      // pull back to VWAP
      for (let i = 0; i < 6; i++) { push(px, px - 0.08, 0.05, 60000); px -= 0.08; vwapVals.push(vwapVals[vwapVals.length - 1] - 0.02); }
      const vwapAtTouch = px;
      // bounce
      push(px, px + 0.09, 0.05, 130000);
      const entry = px + 0.09;
      px = entry;
      for (let i = 0; i < 9; i++) { push(px, px + 0.09, 0.06, 110000); px += 0.09; vwapVals.push(vwapVals[vwapVals.length - 1] + 0.04); }
      meta.entry = entry; meta.stop = vwapAtTouch - 0.05; meta.target = entry + 2 * (entry - meta.stop);
      // VWAP line (rising)
      const vwapPoints = candles.map((c, i) => ({ time: c.time, value: vwapVals[Math.min(i, vwapVals.length - 1)] }));
      addLine('VWAP', VWAP_C, 0, vwapPoints);
      addLine('ENTRY', WHITE, 0, levelLine(candles, 19, entry));
      addLine('STOP', DOWN, 2, levelLine(candles, 19, meta.stop));
      mark(18, 'Touch VWAP', { color: VWAP_C, shape: 'circle' });
      mark(19, 'Green bounce - BUY', { color: UP });
      break;
    }

    case 'orb': {
      let px = 10.00;
      const rangeHigh = 10.40, rangeLow = 9.90;
      for (let i = 0; i < 20; i++) { push(px, px + (r() - 0.5) * 0.30, 0.10, 50000); px = candles[candles.length - 1].close; }
      // breakout above range high
      for (let i = 0; i < 3; i++) push(px, px + 0.03, 0.04, 70000), px += 0.03;
      push(px, rangeHigh + 0.06, 0.05, 160000);
      const entry = rangeHigh + 0.06;
      px = entry;
      for (let i = 0; i < 9; i++) push(px, px + 0.10, 0.06, 100000), px += 0.10;
      meta.entry = entry; meta.stop = rangeLow;
      // Code: target = max(measured_move, entry + 2*risk) — show the 2:1 R:R floor.
      meta.target = Math.max(entry + (rangeHigh - rangeLow), entry + 2 * (entry - rangeLow));
      addLine('Range High', WHITE, 0, levelLine(candles, 0, rangeHigh));
      addLine('Range Low', DOWN, 2, levelLine(candles, 0, rangeLow));
      addLine('ENTRY', WHITE, 0, levelLine(candles, 23, entry));
      addLine('TARGET 2:1', UP, 2, levelLine(candles, 23, meta.target));
      mark(0, '30-min range', { color: TEXT, shape: 'circle' });
      mark(23, 'Breakout - BUY', { color: UP });
      break;
    }

    case 'flat_top': {
      let px = 11.00;
      const resist = 11.60;
      for (let i = 0; i < 8; i++) push(px, px + 0.08, 0.05, 80000), px += 0.08;
      // tests of resistance (flat top)
      for (let i = 0; i < 16; i++) {
        if (i % 5 === 0 || i % 5 === 1) {
          push(px, resist - 0.01, 0.03, 100000); px = resist - 0.01;
        } else {
          push(px, resist - 0.18, 0.05, 45000); px = resist - 0.18;
        }
      }
      push(px, resist + 0.05, 0.04, 170000); // breakout
      const entry = resist + 0.05;
      px = entry;
      for (let i = 0; i < 9; i++) push(px, px + 0.09, 0.06, 95000), px += 0.09;
      meta.entry = entry; meta.stop = resist - 0.20; meta.target = entry + 2 * (entry - meta.stop);
      addLine('Resistance', WHITE, 0, levelLine(candles, 0, resist));
      addLine('ENTRY', WHITE, 0, levelLine(candles, 24, entry));
      addLine('STOP', DOWN, 2, levelLine(candles, 24, meta.stop));
      mark(8, 'Test 1', { color: TEXT, shape: 'circle' });
      mark(13, 'Test 2', { color: TEXT, shape: 'circle' });
      mark(18, 'Test 3', { color: TEXT, shape: 'circle' });
      mark(24, 'Breakout - BUY', { color: UP });
      break;
    }

    case 'ema9_dip': {
      let px = 12.00;
      const emaVals = [];
      let ema = 12.00;
      for (let i = 0; i < 12; i++) { push(px, px + 0.12, 0.05, 90000); px += 0.12; ema = ema + (px - ema) * 0.2; emaVals.push(ema); }
      // dip to EMA
      for (let i = 0; i < 5; i++) { push(px, px - 0.10, 0.05, 55000); px -= 0.10; ema = ema + (px - ema) * 0.2; emaVals.push(ema); }
      const dipLow = px;
      push(px, px + 0.11, 0.05, 120000); // bounce
      const entry = px + 0.11;
      px = entry;
      for (let i = 0; i < 9; i++) { push(px, px + 0.10, 0.06, 100000); px += 0.10; ema = ema + (px - ema) * 0.2; emaVals.push(ema); }
      meta.entry = entry; meta.stop = dipLow - 0.06; meta.target = entry + 2 * (entry - meta.stop);
      const emaPoints = candles.map((c, i) => ({ time: c.time, value: emaVals[Math.min(i, emaVals.length - 1)] }));
      addLine('9 EMA', SMA20_C, 0, emaPoints);
      addLine('ENTRY', WHITE, 0, levelLine(candles, 17, entry));
      addLine('STOP', DOWN, 2, levelLine(candles, 17, meta.stop));
      mark(17, 'Dip to 9 EMA', { color: SMA20_C, shape: 'circle' });
      mark(18, 'Green bounce - BUY', { color: UP });
      break;
    }

    case 'red_candle_exit': {
      // in profit, first red candle close triggers exit
      let px = 10.00;
      for (let i = 0; i < 10; i++) push(px, px + 0.10, 0.05, 90000), px += 0.10;
      const entry = 10.60;
      for (let i = 0; i < 8; i++) push(px, px + 0.12, 0.06, 100000), px += 0.12;
      // red candle close (exit signal)
      push(px, px - 0.14, 0.06, 85000);
      const exitIdx = candles.length - 1;
      px = candles[candles.length - 1].close;
      for (let i = 0; i < 5; i++) push(px, px - 0.05, 0.05, 50000), px -= 0.05;
      meta.entry = entry; meta.stop = entry * 0.99; meta.target = entry * 1.02;
      addLine('ENTRY', WHITE, 0, levelLine(candles, 10, entry));
      mark(18, 'In profit', { color: UP, shape: 'circle' });
      mark(exitIdx, 'First red close = EXIT', { color: DOWN, shape: 'arrowDown' });
      break;
    }

    case 'extension_spike': {
      // in profit, a candle with range >3x average = sell into the spike
      let px = 10.00;
      for (let i = 0; i < 10; i++) push(px, px + 0.08, 0.04, 80000), px += 0.08;
      const entry = 10.50;
      for (let i = 0; i < 8; i++) push(px, px + 0.09, 0.05, 90000), px += 0.09;
      // extension spike candle (large range)
      const spikeOpen = px;
      const spikeClose = px + 0.45;
      candles.push({ time: t, open: spikeOpen, high: spikeClose + 0.10, low: spikeOpen - 0.05, close: spikeClose });
      volume.push({ time: t, value: 260000, color: VOL_UP });
      const spikeIdx = candles.length - 1;
      t += 300;
      px = spikeClose;
      for (let i = 0; i < 5; i++) push(px, px - 0.08, 0.05, 60000), px -= 0.08;
      meta.entry = entry; meta.stop = entry * 0.99; meta.target = entry * 1.02;
      addLine('ENTRY', WHITE, 0, levelLine(candles, 10, entry));
      mark(spikeIdx, 'Spike (3x range) - SELL', { color: UP, shape: 'arrowDown', position: 'aboveBar' });
      break;
    }

    default:
      break;
  }

  return { candles, volume, lines, markers, meta };
}

function DemoChart({ pattern, height = 300 }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    const data = buildData(pattern);
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height,
      layout: { backgroundColor: BG, textColor: TEXT },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
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
        borderColor: BORDER, barSpacing: 10, minBarSpacing: 4,
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
      },
      rightPriceScale: { borderColor: BORDER },
    });
    chartRef.current = chart;

    const candlesSeries = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN, borderVisible: true, wickUpColor: UP, wickDownColor: DOWN,
    });
    candlesSeries.setData(data.candles);

    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: '', scaleMargins: { top: 0.85, bottom: 0 },
    });
    volSeries.setData(data.volume);

    data.lines.forEach((l) => {
      const s = chart.addLineSeries({
        color: l.color, lineWidth: 2, lineStyle: l.lineStyle, title: l.title, lastValueVisible: false, priceLineVisible: false,
      });
      s.setData(l.points);
    });

    candlesSeries.setMarkers(data.markers);

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);
    chart.timeScale().fitContent();

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    };
  }, [pattern, height]);

  return <div ref={chartContainerRef} style={{ position: 'relative', width: '100%' }} />;
}

const STRATEGIES = [
  {
    id: 'first_pullback',
    title: 'First Pullback',
    rr: '2:1',
    desc: 'The core Warrior Trading entry. A stock surges on a catalyst, pulls back 1-3 red candles that HOLD at least 50% of the move, then breaks the prior high — buy the breakout, stop at the pullback low, target 2x that risk.',
  },
  {
    id: 'bull_flag',
    title: 'Bull Flag Breakout',
    rr: '2:1',
    desc: 'A sharp "pole" surge, then a tight consolidation "flag" on falling volume. Enter on the breakout above the flag with volume expansion; stop at the flag low, target 2x the risk.',
  },
  {
    id: 'front_side',
    title: 'Front-Side / Squeeze Breakout (Strategy 8)',
    rr: '2:1',
    desc: 'No pullback — enter on breakout STRENGTH. Three variants: whole-dollar ($1.00) squeeze, blue-sky ATH breakout, and MA-wall (SMA200/50) breakout. Stop below the breakout level, target 2x the risk. Smaller 25% size.',
  },
  {
    id: 'vwap_bounce',
    title: 'VWAP Bounce',
    rr: '2:1',
    desc: 'Uptrend pulls back to VWAP, holds, and bounces green. Enter on the bounce with the stop just below VWAP and a 2:1 target.',
  },
  {
    id: 'orb',
    title: 'Opening Range Breakout',
    rr: '2:1 min',
    desc: 'The first 30 minutes establish a range. Enter when price breaks above the range high on volume. Target is the measured move or 2x the risk (stop at range low) — whichever is larger.',
  },
  {
    id: 'flat_top',
    title: 'Flat Top Breakout',
    rr: '2:1',
    desc: 'A clear resistance level gets tested 2+ times (a "flat top" from a big seller). Enter on the breakout above resistance with 1.5x volume; stop below resistance, target 2x the risk.',
  },
  {
    id: 'ema9_dip',
    title: '9 EMA Dip Buy',
    rr: '2:1',
    desc: 'An uptrend dips to the 9 EMA and bounces green with volume expansion. Enter on the bounce, stop below the dip low, target 2x the risk.',
  },
  {
    id: 'red_candle_exit',
    title: 'Exit: First Red Candle Close',
    rr: null,
    desc: "Ross's rule: if you haven't already sold half, the first candle to close RED while you're in profit is an exit signal.",
  },
  {
    id: 'extension_spike',
    title: 'Exit: Extension Bar Spike',
    rr: null,
    desc: 'A single candle whose range is 3x+ the recent average is an extension spike — sell into the strength.',
  },
];

export default function Demo() {
  return (
    <div className="space-y-4 px-2 sm:px-0">
      <Card className="bg-[#0D1117] border-yellow-500/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold text-white flex items-center gap-2" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            <AlertCircle className="text-yellow-500" size={20} />
            Strategy Examples
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs sm:text-sm text-yellow-500">
            An example chart for each strategy the bot is currently running, showing the pattern it looks for and where it enters / stops / exits.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {STRATEGIES.map((s) => (
          <Card key={s.id} className="bg-[#0D1117] border-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-white flex items-center gap-2" style={{ fontFamily: 'Unbounded, sans-serif' }}>
                <Lightbulb className="text-[#58a6ff]" size={16} />
                <span>{s.title}</span>
                {s.rr && (
                  <span className="ml-auto text-xs font-mono font-bold text-[#26a69a] bg-[#26a69a]/10 border border-[#26a69a]/30 rounded px-2 py-0.5 whitespace-nowrap">
                    R:R {s.rr}
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-neutral-400 leading-relaxed">{s.desc}</p>
              <div className="border border-white/5 rounded">
                <DemoChart pattern={s.id} height={280} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
