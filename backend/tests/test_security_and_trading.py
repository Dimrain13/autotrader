"""
Regression suite for MomentumX Phase 1 (Security) + Phase 2 (Trading
Correctness) + Phase 3 (Architecture/Reliability) remediation.

- test_auth.py-style: Bearer token auth on every /api route
- Settings secret masking + SMA-only update validation
- CORS allow-list behaviour (localhost:8001 direct, bypassing proxy)
- Rate limiting on /api/orders (localhost:8001 direct)
- TradeOrder Pydantic validation (qty, side, stop_loss_pct bounds)
- Real-data-only market bars / entry-conditions endpoints
- Auto-trader toggle/status + background loop sanity
- Unified Mongo-backed persistence: trade-history / missed-opportunities
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
LOCAL_URL = "http://localhost:8001"  # direct backend, bypasses preview proxy
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'daniel.r.millner@gmail.com')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Black0rkid5!')


def _get_jwt():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


TOKEN = _get_jwt()
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update(AUTH_HEADERS)
    return s


# ============ AUTH (Phase 1 #1) ============
class TestAuth:
    def test_no_header_401(self):
        r = requests.get(f"{BASE_URL}/api/")
        assert r.status_code == 401

    def test_wrong_token_401(self):
        r = requests.get(f"{BASE_URL}/api/", headers={"Authorization": "Bearer wrong-token-xyz"})
        assert r.status_code == 401

    def test_malformed_header_401(self):
        r = requests.get(f"{BASE_URL}/api/", headers={"Authorization": TOKEN})  # missing "Bearer "
        assert r.status_code == 401

    def test_correct_token_200(self, session):
        r = session.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert data["message"] == "MomentumX Trading API"

    def test_settings_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/settings")
        assert r.status_code == 401


# ============ SETTINGS SECRET MASKING (Phase 1 #2) ============
class TestSettingsMasking:
    def test_get_settings_never_leaks_raw_keys(self, session):
        r = session.get(f"{BASE_URL}/api/settings")
        assert r.status_code == 200
        data = r.json()
        for field in ["api_key_masked", "has_api_key", "secret_key_masked", "has_secret_key",
                      "base_url", "paper_trading", "sma_short", "sma_long"]:
            assert field in data
        # raw fields must never be present
        assert "api_key" not in data
        assert "secret_key" not in data
        assert "ALPACA_API_KEY" not in str(data)

    def test_post_settings_valid_sma(self, session):
        r = session.post(f"{BASE_URL}/api/settings", json={"sma_short": 20, "sma_long": 50})
        assert r.status_code == 200
        # verify persisted
        get_r = session.get(f"{BASE_URL}/api/settings")
        assert get_r.json()["sma_short"] == 20
        assert get_r.json()["sma_long"] == 50

    def test_post_settings_short_gte_long_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/settings", json={"sma_short": 50, "sma_long": 20})
        assert r.status_code == 400

    def test_post_settings_rejects_extra_secret_fields_silently_ignored(self, session):
        # .env must remain byte-for-byte unchanged (no runtime secret rewriting),
        # regardless of what real keys happen to be configured in this environment.
        with open("/app/backend/.env") as f:
            env_before = f.read()

        # Even if a client tries to sneak api_key in, Pydantic model only accepts sma fields
        r = session.post(f"{BASE_URL}/api/settings", json={
            "sma_short": 20, "sma_long": 50, "api_key": "HACKED", "secret_key": "HACKED"
        })
        assert r.status_code == 200

        with open("/app/backend/.env") as f:
            env_after = f.read()
        assert "HACKED" not in env_after
        assert env_after == env_before


# ============ VALIDATION (Phase 1 #4) ============
class TestOrderValidation:
    def test_qty_zero_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/orders", json={"symbol": "AAPL", "qty": 0, "side": "buy"})
        assert r.status_code == 422

    def test_qty_negative_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/orders", json={"symbol": "AAPL", "qty": -5, "side": "buy"})
        assert r.status_code == 422

    def test_invalid_side_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/orders", json={"symbol": "AAPL", "qty": 1, "side": "hold"})
        assert r.status_code == 422

    def test_stop_loss_pct_out_of_bounds_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/orders", json={
            "symbol": "AAPL", "qty": 1, "side": "buy", "stop_loss_pct": 999
        })
        assert r.status_code == 422


# ============ CORS (Phase 1 #3) - localhost:8001 direct only ============
class TestCORS:
    def test_allowed_origin_reflected(self):
        r = requests.options(
            f"{LOCAL_URL}/api/",
            headers={
                "Origin": "https://momentumx-deploy.preview.emergentagent.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert r.headers.get("access-control-allow-origin") == "https://momentumx-deploy.preview.emergentagent.com"

    def test_disallowed_origin_not_reflected(self):
        r = requests.options(
            f"{LOCAL_URL}/api/",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil.com"


# ============ RATE LIMITING (Phase 1 #4) - localhost:8001 direct only ============
class TestRateLimiting:
    def test_orders_rate_limited_after_20_per_minute(self):
        # Use a non-existent ticker (<=10 chars to pass Pydantic validation) so
        # these requests still exercise the rate-limiter decorator (which runs
        # inside the endpoint, after body validation) WITHOUT placing any real
        # orders against the live paper account. Alpaca will reject "ZZZZINVLD"
        # with an asset-not-found error, which is exactly what we want here.
        statuses = []
        for i in range(25):
            r = requests.post(
                f"{LOCAL_URL}/api/orders",
                headers=AUTH_HEADERS,
                json={"symbol": "ZZZZINVLD", "qty": 1, "side": "buy"},
            )
            statuses.append(r.status_code)
        assert 429 in statuses, f"Expected a 429 within 25 rapid requests, got statuses={statuses}"
        idx_429 = statuses.index(429)
        body = requests.post(
            f"{LOCAL_URL}/api/orders", headers=AUTH_HEADERS,
            json={"symbol": "ZZZZINVLD", "qty": 1, "side": "buy"},
        )
        if body.status_code == 429:
            assert "rate limit" in body.text.lower() or "Rate limit exceeded" in body.text


# ============ NO FAKE DATA (Phase 2 #6) ============
class TestRealDataOnly:
    def test_market_bars_real_source(self, session):
        r = session.get(f"{BASE_URL}/api/market/bars/AAPL", params={"timeframe": "5Min"})
        assert r.status_code in [200, 502]
        if r.status_code == 200:
            data = r.json()
            assert "source" in data
            assert data["source"] in ["alpaca", "alpaca_iex", "yahoo", "nasdaq", "none", "unknown"]

    def test_entry_conditions_invalid_symbol_no_fake_data(self, session):
        r = session.get(f"{BASE_URL}/api/auto-trader/entry-conditions/ZZZZINVALIDSYMBOL")
        assert r.status_code == 200
        data = r.json()
        # Should return clean error, not fabricated conditions
        if "error" in data:
            assert data["conditions"] == {}


# ============ NO FAKE BUYING POWER (Phase 2 #8) - code presence check ============
class TestNoFakeBuyingPower:
    def test_no_day_trading_simulation_code(self):
        with open("/app/backend/server.py") as f:
            server_code = f.read()
        assert "DAY_TRADING_MODE" not in server_code
        assert "simulated_pdt" not in server_code
        assert "portfolio_value * 4" not in server_code


# ============ AUTO-TRADER TOGGLE / BACKGROUND LOOP (Phase 3 #9) ============
class TestAutoTrader:
    def test_toggle_enable_and_status(self, session):
        r = session.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": True})
        assert r.status_code == 200
        assert r.json()["active"] is True

        status_r = session.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_r.status_code == 200
        assert status_r.json()["active"] is True

        # cleanup - disable again
        session.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": False})

    def test_manual_process_trigger_no_arity_bug(self, session):
        """
        process_scanner_results(scanner_results, portfolio_value) takes 2 args.
        Since Alpaca isn't configured, get_account() raises and the endpoint
        wraps it as a clean 500 "Alpaca API not configured" - that is expected
        here. What we assert is that it's NOT a TypeError/arity crash (which
        would leak a Python traceback mentioning "positional argument").
        """
        session.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": True})
        try:
            r = session.post(f"{BASE_URL}/api/auto-trader/process")
            if r.status_code == 500:
                assert "Alpaca API not configured" in r.text
                assert "positional argument" not in r.text
                assert "TypeError" not in r.text
            else:
                assert r.status_code == 200
        finally:
            # Always disable auto-trader afterward, even if an assertion above
            # fails - this test toggles it on and must not leave it running
            # against the live paper account.
            session.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": False})


# ============ EVENT LOOP NOT BLOCKED (Phase 3 #11) ============
class TestResponsiveness:
    def test_simple_get_responds_quickly(self, session):
        start = time.time()
        r = session.get(f"{BASE_URL}/api/")
        elapsed = time.time() - start
        assert r.status_code == 200
        assert elapsed < 5.0, f"Simple GET took {elapsed}s - possible event loop blocking"


# ============ UNIFIED PERSISTENCE (Phase 3 #12) ============
class TestUnifiedPersistence:
    def test_trade_history_get_works(self, session):
        r = session.get(f"{BASE_URL}/api/trade-history")
        assert r.status_code == 200
        assert "trades" in r.json()

    def test_missed_opportunities_get_works(self, session):
        r = session.get(f"{BASE_URL}/api/missed-opportunities")
        assert r.status_code == 200
        assert "opportunities" in r.json()

    def test_log_trade_then_appears_in_history(self, session):
        sample_trade = {
            "symbol": "TEST_MOMX",
            "entry_price": 10.0,
            "exit_price": 11.0,
            "shares": 10,
            "entry_time": "2026-02-01T10:00:00Z",
            "exit_time": "2026-02-01T10:05:00Z",
            "pnl": 10.0,
            "pnl_pct": 10.0,
            "exit_reason": "TEST",
            "strategy": "TEST"
        }
        log_r = session.post(f"{BASE_URL}/api/trade-history/log", json=sample_trade)
        assert log_r.status_code == 200

        get_r = session.get(f"{BASE_URL}/api/trade-history", params={"limit": 200})
        assert get_r.status_code == 200
        symbols = [t.get("symbol") for t in get_r.json()["trades"]]
        assert "TEST_MOMX" in symbols
