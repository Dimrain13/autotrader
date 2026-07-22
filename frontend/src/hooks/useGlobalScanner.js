import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { scannerCache } from "../utils/scannerCache";
import { playTradeSound } from "../utils/sound";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

/**
 * Global scanner polling hook - intended to be called ONCE at the App root
 * (not inside a route-specific page component). This keeps the scanner
 * scanning, alerting, and auto-trader triggering running continuously for
 * the whole session, regardless of which page the user is currently
 * viewing - matching how the real backend auto-trader loop already runs
 * independent of the frontend.
 */
export function useGlobalScanner() {
  const [scanning, setScanning] = useState(false);
  const [autoScan, setAutoScanState] = useState(() => localStorage.getItem('autoScan') === 'true');
  const [demoMode, setDemoModeState] = useState(() => localStorage.getItem('demoMode') === 'true');
  const [autoTrade, setAutoTradeState] = useState(() => localStorage.getItem('autoTrade') === 'true');
  const [results, setResults] = useState([]);
  const [traderStatus, setTraderStatus] = useState({ active: false, open_positions: 0, positions: [] });
  const [lastScanTime, setLastScanTime] = useState(null);
  const [scanCount, setScanCount] = useState(0);
  const [nextScanCountdown, setNextScanCountdown] = useState(60);
  const [criteria, setCriteria] = useState(() => {
    const saved = localStorage.getItem('scannerCriteria');
    if (saved) return JSON.parse(saved);
    return { min_price: 2, max_price: 20, min_change: 10, min_volume_ratio: 5, max_float: 45000000 };
  });

  const intervalRef = useRef(null);
  const countdownRef = useRef(null);
  const resultsRef = useRef(results);
  resultsRef.current = results;
  const traderStatusRef = useRef(traderStatus);
  traderStatusRef.current = traderStatus;

  const fetchTraderStatus = async () => {
    try {
      const response = await axios.get(`${API}/auto-trader/status`);
      setTraderStatus(response.data);
      return response.data;
    } catch (error) {
      console.error('Failed to fetch trader status:', error);
      return null;
    }
  };

  // Load cached results immediately on hook init, and fetch trader status once
  useEffect(() => {
    const cached = scannerCache.get();
    if (cached && cached.data) {
      setResults(cached.data);
    }
    if (autoTrade) {
      fetchTraderStatus();
    }
  }, []);

  const runScan = async () => {
    setScanning(true);
    const existingResults = resultsRef.current;

    try {
      let scanResults;
      if (demoMode) {
        const response = await axios.get(`${API}/scanner/demo`, { params: criteria });
        scanResults = response.data.results;
      } else {
        const response = await axios.post(`${API}/scanner/scan`, criteria);
        scanResults = response.data;
      }

      scannerCache.set(scanResults);

      if (autoTrade && !demoMode) {
        try {
          const positionsBefore = new Set((traderStatusRef.current?.positions || []).map(p => p.symbol));
          await axios.post(`${API}/auto-trader/process`);
          const status = await fetchTraderStatus();
          // Sound alert ONLY for an actual auto-trader entry/exit (a position
          // symbol appeared or disappeared) - not for scanner candidates
          // merely appearing/disappearing from the results list.
          const positionsAfter = new Set((status?.positions || []).map(p => p.symbol));
          const tradeHappened =
            positionsBefore.size !== positionsAfter.size ||
            [...positionsBefore].some((s) => !positionsAfter.has(s)) ||
            [...positionsAfter].some((s) => !positionsBefore.has(s));
          if (tradeHappened) playTradeSound();
        } catch (error) {
          console.error('Auto-trader processing error:', error);
        }
      }

      const updatedResults = [...existingResults];
      const existingSymbols = new Set(updatedResults.map(r => r.symbol));
      const currentSymbols = new Set(scanResults.map(s => s.symbol));

      scanResults.forEach(newStock => {
        const existingIndex = updatedResults.findIndex(r => r.symbol === newStock.symbol);
        if (existingIndex >= 0) {
          updatedResults[existingIndex] = {
            ...newStock,
            first_detected: updatedResults[existingIndex].first_detected || new Date().toISOString()
          };
        } else {
          updatedResults.push({ ...newStock, first_detected: new Date().toISOString() });
        }
      });

      const finalResults = updatedResults
        .filter(stock => currentSymbols.has(stock.symbol))
        .sort((a, b) => {
          const criteriaCompare = (b.criteria_count || 0) - (a.criteria_count || 0);
          if (criteriaCompare !== 0) return criteriaCompare;
          return (b.volume_ratio || 0) - (a.volume_ratio || 0);
        });

      setResults(finalResults);
      setLastScanTime(new Date());
      setScanCount(prev => prev + 1);
    } catch (error) {
      console.error('Scan error:', error);
    } finally {
      setScanning(false);
    }
  };

  // Auto-scan interval - lives at the App root, so it keeps running no
  // matter which page is currently rendered.
  useEffect(() => {
    if (autoScan) {
      runScan();
      setNextScanCountdown(60);

      countdownRef.current = setInterval(() => {
        setNextScanCountdown(prev => (prev <= 1 ? 60 : prev - 1));
      }, 1000);

      intervalRef.current = setInterval(() => {
        runScan();
        setNextScanCountdown(60);
      }, 60000);
    } else {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
      if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [autoScan]);

  // Re-run scan when criteria changes, but only if auto-scan is active
  useEffect(() => {
    if (autoScan && !scanning) {
      runScan();
    }
  }, [criteria]);

  const updateCriteria = (newCriteria) => {
    setCriteria(newCriteria);
    localStorage.setItem('scannerCriteria', JSON.stringify(newCriteria));
  };

  const setAutoScan = (value) => {
    setAutoScanState(value);
    localStorage.setItem('autoScan', value.toString());
  };

  const setDemoMode = (value) => {
    setDemoModeState(value);
    localStorage.setItem('demoMode', value.toString());
  };

  const toggleAutoTrade = async () => {
    const newState = !autoTrade;
    try {
      await axios.post(`${API}/auto-trader/toggle?enabled=${newState}`);
      setAutoTradeState(newState);
      localStorage.setItem('autoTrade', newState.toString());
      return newState;
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to toggle auto-trader');
      return autoTrade;
    }
  };

  return {
    scanning, results, setResults,
    autoScan, setAutoScan,
    demoMode, setDemoMode,
    autoTrade, toggleAutoTrade,
    traderStatus, fetchTraderStatus,
    lastScanTime, scanCount, nextScanCountdown,
    criteria, updateCriteria,
    runScan
  };
}
