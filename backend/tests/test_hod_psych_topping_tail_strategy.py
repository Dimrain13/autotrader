"""
Tests for the HOD-retest / psych-level / topping-tail auto-trader strategy overhaul.

Covers:
1. GET /api/auto-trader/status exposes reward_risk_ratio, enable_partial_profit,
   breakeven_buffer_pct, topping_tail_wick_ratio with correct defaults.
2. POST /api/auto-trader/settings round-trips enable_partial_profit,
   breakeven_buffer_pct, topping_tail_wick_ratio (verified via subsequent GET status).
3. Smoke test: GET /api/auto-trader/entry-conditions/{symbol} for several scanner
   symbols returns 200 with no crashes.
4. Toggle auto-trader on, wait, confirm background loop doesn't crash, toggle off.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    email = os.environ.get("TEST_ADMIN_EMAIL", "daniel.r.millner@gmail.com")
    password = os.environ.get("TEST_ADMIN_PASSWORD", "Black0rkid5!")
    login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if login_resp.status_code == 200:
        token = login_resp.json().get("access_token")
        if token:
            session.headers.update({"Authorization": f"Bearer {token}"})
    return session


class TestAutoTraderStatusDefaults:
    def test_status_returns_new_strategy_fields(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
        strategy = data["strategy"]

        assert strategy["reward_risk_ratio"] == pytest.approx(2.0)
        assert strategy["enable_partial_profit"] is True
        assert strategy["breakeven_buffer_pct"] == pytest.approx(0.2)
        assert strategy["topping_tail_wick_ratio"] == pytest.approx(0.5)


class TestAutoTraderSettingsRoundTrip:
    def test_enable_partial_profit_roundtrip(self, api_client):
        # Turn OFF
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"enable_partial_profit": False})
        assert resp.status_code == 200
        assert resp.json()["current_settings"]["enable_partial_profit"] is False

        status_resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["strategy"]["enable_partial_profit"] is False

        # Restore ON
        resp2 = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"enable_partial_profit": True})
        assert resp2.status_code == 200
        assert resp2.json()["current_settings"]["enable_partial_profit"] is True

        status_resp2 = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp2.json()["strategy"]["enable_partial_profit"] is True

    def test_breakeven_buffer_pct_roundtrip(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"breakeven_buffer_pct": 0.3})
        assert resp.status_code == 200
        assert resp.json()["current_settings"]["breakeven_buffer_pct"] == pytest.approx(0.3)

        status_resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp.json()["strategy"]["breakeven_buffer_pct"] == pytest.approx(0.3)

        # Restore
        resp2 = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"breakeven_buffer_pct": 0.2})
        assert resp2.status_code == 200
        assert resp2.json()["current_settings"]["breakeven_buffer_pct"] == pytest.approx(0.2)
        status_resp2 = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp2.json()["strategy"]["breakeven_buffer_pct"] == pytest.approx(0.2)

    def test_topping_tail_wick_ratio_roundtrip(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"topping_tail_wick_ratio": 0.6})
        assert resp.status_code == 200
        assert resp.json()["current_settings"]["topping_tail_wick_ratio"] == pytest.approx(0.6)

        status_resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp.json()["strategy"]["topping_tail_wick_ratio"] == pytest.approx(0.6)

        # Restore
        resp2 = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"topping_tail_wick_ratio": 0.5})
        assert resp2.status_code == 200
        assert resp2.json()["current_settings"]["topping_tail_wick_ratio"] == pytest.approx(0.5)
        status_resp2 = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert status_resp2.json()["strategy"]["topping_tail_wick_ratio"] == pytest.approx(0.5)


class TestEntryConditionsSmoke:
    def test_scanner_symbols_entry_conditions_no_crash(self, api_client):
        symbols = []
        try:
            scan_resp = api_client.post(f"{BASE_URL}/api/scanner/scan", json={}, timeout=90)
            if scan_resp.status_code == 200:
                scan_data = scan_resp.json()
                stocks = scan_data if isinstance(scan_data, list) else scan_data.get("stocks", [])
                symbols = [s.get("symbol") for s in stocks if s.get("symbol")][:4]
        except requests.exceptions.RequestException:
            pass  # scanner can be slow/rate-limited (pre-existing infra behavior) - fall back below

        if not symbols:
            # No scanner results available (e.g. market closed, slow scan/gateway
            # timeout) - fall back to well-known symbols just to smoke-test the
            # entry-conditions endpoint itself (the actual scope of this check).
            symbols = ["AAPL", "TSLA"]

        for symbol in symbols:
            resp = api_client.get(f"{BASE_URL}/api/auto-trader/entry-conditions/{symbol}")
            assert resp.status_code == 200, f"{symbol}: entry-conditions returned {resp.status_code}"
            data = resp.json()
            assert "symbol" in data
            # Either 'conditions' dict present, or a graceful 'error' (no real data) - never a crash
            assert "conditions" in data or "error" in data


class TestAutoTraderToggleSmoke:
    def test_toggle_on_then_off(self, api_client):
        resp_on = api_client.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": True})
        assert resp_on.status_code in (200, 400)  # 400 if in live mode
        if resp_on.status_code == 200:
            assert resp_on.json()["active"] is True

            time.sleep(20)  # let background loop run at least once (short sleep to respect test timeout)

            status_resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
            assert status_resp.status_code == 200

            resp_off = api_client.post(f"{BASE_URL}/api/auto-trader/toggle", params={"enabled": False})
            assert resp_off.status_code == 200
            assert resp_off.json()["active"] is False
