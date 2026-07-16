"""
Tests for:
 1) GET /api/account - margin_buying_power field correctness
 2) GET /api/market/stream-status - priority symbol tracking + eviction bookkeeping
 3) GET /api/market/bars/{symbol}?timeframe=10Sec - subscribes with priority=True
 4) Regression: auto-trader status/process endpoints don't crash with margin sizing change
"""
import os
import re
import time
import pytest
import requests


def _load_backend_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if url:
        return url.rstrip('/')
    env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', '.env')
    try:
        with open(env_path) as f:
            for line in f:
                m = re.match(r'REACT_APP_BACKEND_URL=(.+)', line.strip())
                if m:
                    return m.group(1).strip().rstrip('/')
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not found in env or frontend/.env")


BASE_URL = _load_backend_url()
LOGIN_EMAIL = "daniel.r.millner@gmail.com"
LOGIN_PASSWORD = "Black0rkid5!"


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD})
    if resp.status_code != 200:
        pytest.skip(f"Login failed: {resp.status_code} {resp.text}")
    token = resp.json().get("access_token")
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


class TestAccountMarginBuyingPower:
    def test_account_has_margin_buying_power_field(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/account")
        assert resp.status_code == 200
        data = resp.json()
        assert "margin_buying_power" in data
        assert "buying_power" in data
        assert "day_trading_buying_power" in data
        assert "portfolio_value" in data
        assert isinstance(data["margin_buying_power"], (int, float))

    def test_margin_buying_power_is_max_of_the_two(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/account")
        data = resp.json()
        expected = max(data["buying_power"], data["day_trading_buying_power"])
        assert data["margin_buying_power"] == expected

    def test_margin_buying_power_never_negative(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/account")
        data = resp.json()
        assert data["margin_buying_power"] >= 0


class TestAutoTraderStatusAndProcessUseMargin:
    def test_auto_trader_status_no_crash(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data or "is_running" in data or isinstance(data, dict)

    def test_auto_trader_process_no_crash(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/process")
        # Should not 500 - either processes fine or returns a controlled response
        assert resp.status_code in (200, 400)


class TestMarketStreamStatusAndPriority:
    def test_stream_status_endpoint_shape(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/market/stream-status")
        assert resp.status_code == 200
        data = resp.json()
        for key in ["configured", "connected", "trade_quote_subscribed_count",
                    "trade_quote_limit", "trade_quote_priority_symbols"]:
            assert key in data, f"missing key {key}"
        assert data["trade_quote_limit"] == 25
        assert isinstance(data["trade_quote_priority_symbols"], list)

    def test_10sec_bars_marks_symbol_priority(self, api_client):
        symbol = "AAPL"
        resp = api_client.get(f"{BASE_URL}/api/market/bars/{symbol}", params={"timeframe": "10Sec"})
        assert resp.status_code == 200
        # Give the background asyncio.create_task(subscribe(...)) a moment to run
        time.sleep(1.5)
        status_resp = api_client.get(f"{BASE_URL}/api/market/stream-status")
        assert status_resp.status_code == 200
        priority_symbols = status_resp.json().get("trade_quote_priority_symbols", [])
        assert symbol in priority_symbols, (
            f"{symbol} not found in trade_quote_priority_symbols after 10Sec bars request: {priority_symbols}"
        )

    def test_1min_bars_also_marks_priority(self, api_client):
        symbol = "MSFT"
        resp = api_client.get(f"{BASE_URL}/api/market/bars/{symbol}", params={"timeframe": "1Min"})
        assert resp.status_code == 200
        time.sleep(1.5)
        status_resp = api_client.get(f"{BASE_URL}/api/market/stream-status")
        priority_symbols = status_resp.json().get("trade_quote_priority_symbols", [])
        assert symbol in priority_symbols

    def test_bulk_eviction_does_not_crash_and_stays_under_cap(self, api_client):
        # Simulate many non-priority scanner symbols via repeated bar 5Min/1Day
        # calls (those don't set priority=True per files_of_reference) then
        # request a NEW priority symbol and confirm cap is respected.
        scanner_symbols = [f"SIM{i}" for i in range(30)]
        for s in scanner_symbols:
            try:
                api_client.get(f"{BASE_URL}/api/market/bars/{s}", params={"timeframe": "1Day"})
            except Exception:
                pass
        new_priority_symbol = "TSLA"
        resp = api_client.get(f"{BASE_URL}/api/market/bars/{new_priority_symbol}", params={"timeframe": "10Sec"})
        assert resp.status_code == 200
        time.sleep(1.5)
        status_resp = api_client.get(f"{BASE_URL}/api/market/stream-status")
        data = status_resp.json()
        assert data["trade_quote_subscribed_count"] <= data["trade_quote_limit"]
        assert new_priority_symbol in data["trade_quote_priority_symbols"]


class TestRegression:
    def test_scanner_momentum_endpoint(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/scanner/momentum")
        assert resp.status_code == 200

    def test_positions_endpoint(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/positions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_market_status_endpoint(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/market/status")
        assert resp.status_code == 200
