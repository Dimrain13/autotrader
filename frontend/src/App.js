import { useState, useEffect, useRef } from "react";
import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { getToken, setToken, clearToken } from "./lib/axiosConfig";
import { useGlobalScanner } from "./hooks/useGlobalScanner";
import Dashboard from "./pages/Dashboard";
import Scanner from "./pages/Scanner";
import Trading from "./pages/Trading";
import History from "./pages/History";
import MissedOpportunities from "./pages/MissedOpportunities";
import Settings from "./pages/Settings";
import Demo from "./pages/Demo";
import { Toaster } from "./components/ui/sonner";
import { TrendingUp, Search, DollarSign, Settings as SettingsIcon, PlayCircle, BarChart3, EyeOff, LogOut } from "lucide-react";
import "@/App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function TokenGate({ onAuthenticated }) {
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!tokenInput.trim()) return;
    setChecking(true);
    setError("");
    setToken(tokenInput.trim());
    try {
      // Any authenticated endpoint works as a verification ping
      await axios.get(`${API}/settings`);
      onAuthenticated();
    } catch (err) {
      clearToken();
      setError("Invalid access token. Make sure you're using API_ACCESS_TOKEN from backend/.env - not your Alpaca API key/secret.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-4" data-testid="token-gate-screen">
      <div className="w-full max-w-md bg-[#0A0A0A] border border-white/10 rounded-sm p-8">
        <h1 className="text-2xl font-black mb-2" style={{ fontFamily: 'Unbounded, sans-serif' }}>
          <span className="text-[#00E599]">Momentum</span><span className="text-white">X</span>
        </h1>
        <p className="text-sm text-neutral-500 mb-6">
          Enter the <code className="text-[#00E599]">API_ACCESS_TOKEN</code> from your backend's
          <code className="text-neutral-300"> .env</code> file to continue.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4" data-testid="token-gate-form">
          <input
            type="password"
            data-testid="token-gate-input"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="API Access Token"
            className="w-full bg-[#121212] border border-white/10 rounded-sm px-4 py-3 text-white text-sm font-mono focus:outline-none focus:border-[#2E5CFF] transition-colors"
            autoFocus
          />
          {error && (
            <div className="text-[#FF1A40] text-xs" data-testid="token-gate-error">{error}</div>
          )}
          <button
            type="submit"
            data-testid="token-gate-submit-button"
            disabled={checking || !tokenInput.trim()}
            className="w-full bg-[#00E599] text-black font-bold py-3 rounded-sm hover:bg-[#00E599]/90 transition-colors disabled:opacity-50"
          >
            {checking ? "Verifying..." : "Unlock"}
          </button>
        </form>
        <p className="text-xs text-neutral-600 mt-4">
          Note: this is the app's own <code className="text-neutral-400">API_ACCESS_TOKEN</code>,
          not your Alpaca API key/secret. Find it in <code className="text-neutral-400">backend/.env</code>.
        </p>
      </div>
    </div>
  );
}

function NavBar({ account, onLogout }) {
  const location = useLocation();
  
  const isActive = (path) => location.pathname === path;
  
  return (
    <nav className="border-b border-white/5 bg-[#0A0A0A]">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-8">
            <h1 className="text-xl sm:text-2xl font-black whitespace-nowrap" style={{ fontFamily: 'Unbounded, sans-serif' }}>
              <span className="text-[#00E599]">Momentum</span><span className="text-white">X</span>
            </h1>
            <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-hide">
              <Link
                to="/"
                data-testid="nav-dashboard"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <TrendingUp className="inline mr-1 sm:mr-2" size={14} />
                <span className="hidden sm:inline">Dashboard</span>
                <span className="sm:hidden">Home</span>
              </Link>
              <Link
                to="/scanner"
                data-testid="nav-scanner"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/scanner') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Search className="inline mr-1 sm:mr-2" size={14} />
                Scan
              </Link>
              <Link
                to="/trading"
                data-testid="nav-trading"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/trading') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <DollarSign className="inline mr-1 sm:mr-2" size={14} />
                Trade
              </Link>
              <Link
                to="/history"
                data-testid="nav-history"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/history') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <BarChart3 className="inline mr-1 sm:mr-2" size={14} />
                History
              </Link>
              <Link
                to="/missed"
                data-testid="nav-missed"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/missed') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <EyeOff className="inline mr-1 sm:mr-2" size={14} />
                Missed
              </Link>
              <Link
                to="/settings"
                data-testid="nav-settings"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/settings') 
                    ? 'bg-[#2E5CFF]/10 border border-[#2E5CFF] text-[#2E5CFF]' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <SettingsIcon className="inline mr-1 sm:mr-2" size={14} />
                <span className="hidden sm:inline">Settings</span>
                <span className="sm:hidden">Set</span>
              </Link>
              <Link
                to="/demo"
                data-testid="nav-demo"
                className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded-sm transition-all whitespace-nowrap ${
                  isActive('/demo') 
                    ? 'bg-yellow-500/10 border border-yellow-500 text-yellow-500' 
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <PlayCircle className="inline mr-1 sm:mr-2" size={14} />
                Demo
              </Link>
            </div>
          </div>
          
          <div className="flex items-center gap-2 sm:gap-4" data-testid="account-info">
            {account && (
              <>
                <div className="text-right">
                  <div className="text-xs text-neutral-500">Portfolio</div>
                  <div className="text-sm sm:text-lg font-mono text-white">
                    ${account.portfolio_value?.toFixed(2) || '0.00'}
                  </div>
                </div>
                <div className="h-8 w-px bg-white/10" />
                <div className="text-right">
                  <div className="text-xs text-neutral-500">
                    Buying Power {account.pattern_day_trader ? '(4x)' : '(2x)'}
                  </div>
                  <div className="text-lg font-mono text-[#00E599]">
                    ${account.buying_power?.toFixed(2) || '0.00'}
                  </div>
                </div>
              </>
            )}
            <div className="bg-[#2E5CFF]/10 text-[#2E5CFF] border border-[#2E5CFF]/20 text-[10px] px-2 py-0.5 rounded-full uppercase tracking-widest font-bold animate-pulse">
              PAPER
            </div>
            <button
              onClick={onLogout}
              data-testid="logout-button"
              title="Lock / clear access token"
              className="text-neutral-500 hover:text-white transition-colors"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}

function App() {
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [recentOrders, setRecentOrders] = useState([]);
  const [loading, setLoading] = useState(false); // Start false for instant UI
  const [authenticated, setAuthenticated] = useState(!!getToken());
  const scanner = useGlobalScanner();

  useEffect(() => {
    const handleUnauthorized = () => setAuthenticated(false);
    window.addEventListener("momentumx-unauthorized", handleUnauthorized);
    return () => window.removeEventListener("momentumx-unauthorized", handleUnauthorized);
  }, []);

  // Global polling for account, positions and recent orders - lives at the
  // App root so this data stays fresh no matter which page is open, instead
  // of resetting/going stale every time the user navigates away from
  // Dashboard (which used to own this fetch itself).
  useEffect(() => {
    if (!authenticated) return;
    fetchAccount();
    fetchPositions();
    fetchRecentOrders();
    const interval = setInterval(() => {
      fetchAccount();
      fetchPositions();
      fetchRecentOrders();
    }, 30000);
    return () => clearInterval(interval);
  }, [authenticated]);

  // Kill-switch notification: poll risk status app-wide (regardless of which
  // page is open) and fire a toast exactly once when trading halts, so the
  // user doesn't have to be staring at the Scanner page to notice.
  const prevCanTradeRef = useRef(true);
  useEffect(() => {
    if (!authenticated) return;
    const checkRiskStatus = async () => {
      try {
        const response = await axios.get(`${API}/auto-trader/status`);
        const riskStatus = response.data?.risk_status;
        if (riskStatus) {
          if (!riskStatus.can_trade && prevCanTradeRef.current) {
            toast.error(`Auto-Trader Halted: ${riskStatus.reason}`, {
              description: "New BUY orders are blocked for the rest of the trading day.",
              duration: 15000,
            });
          }
          prevCanTradeRef.current = riskStatus.can_trade;
        }
      } catch (error) {
        console.error('Failed to fetch risk status:', error);
      }
    };
    checkRiskStatus();
    const riskInterval = setInterval(checkRiskStatus, 30000);
    return () => clearInterval(riskInterval);
  }, [authenticated]);

  const fetchAccount = async () => {
    try {
      const response = await axios.get(`${API}/account`);
      setAccount(response.data);
    } catch (error) {
      console.error('Failed to fetch account:', error);
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

  const handleLogout = () => {
    clearToken();
    setAuthenticated(false);
  };

  if (!authenticated) {
    return <TokenGate onAuthenticated={() => setAuthenticated(true)} />;
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#050505]">
        <NavBar account={account} onLogout={handleLogout} />
        <main className="container mx-auto p-4 md:p-6">
          {loading ? (
            <div className="flex justify-center items-center h-96">
              <div className="text-lg text-neutral-500">Loading...</div>
            </div>
          ) : (
            <Routes>
              <Route path="/" element={<Dashboard account={account} positions={positions} recentOrders={recentOrders} scanner={scanner} />} />
              <Route path="/scanner" element={<Scanner scanner={scanner} />} />
              <Route path="/trading" element={<Trading />} />
              <Route path="/history" element={<History />} />
              <Route path="/missed" element={<MissedOpportunities />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/demo" element={<Demo />} />
            </Routes>
          )}
        </main>
        <Toaster position="top-right" />
      </div>
    </BrowserRouter>
  );
}

export default App;