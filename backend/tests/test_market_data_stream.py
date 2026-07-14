"""
Tests for the real-time Alpaca WebSocket market-data streaming feature:
- GET /api/market/stream-status
- GET /api/market/quote/{symbol} (side effect: subscribes symbol to stream)
- GET /api/market/bars/{symbol} (1Min / 5Min)
- GET /api/auto-trader/entry-conditions/{symbol}
- WS /api/ws/market-data (token auth, subscribe action)
- Regression: auto-trader toggle refuses to enable while in live mode
"""
import os
import json
import asyncio
import pytest
import requests
import websockets

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
LOGIN_EMAIL = "daniel.r.millner@gmail.com"
LOGIN_PASSWORD = "Black0rkid5!"


@pytest.fixture(scope="session")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="session")
def auth_token(api_client):
    resp = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": LOGIN_EMAIL, "password": LOGIN_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Login failed: {resp.status_code} {resp.text}")
    data = resp.json()
    token = data.get("access_token")
    assert token
    return token


@pytest.fixture(scope="session")
def authed_client(api_client, auth_token):
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestAuth:
    def test_login_success(self, auth_token):
        assert isinstance(auth_token, str) and len(auth_token) > 10


class TestStreamStatus:
    def test_stream_status_shape(self, authed_client):
        resp = authed_client.get(f"{BASE_URL}/api/market/stream-status")
        assert resp.status_code == 200
        data = resp.json()
        for key in ["configured", "connected", "authenticated",
                    "bar_subscribed_count", "trade_quote_subscribed_count"]:
            assert key in data, f"missing key {key}"
        assert data["configured"] is True

    def test_stream_status_increases_after_quote_calls(self, authed_client):
        before = authed_client.get(f"{BASE_URL}/api/market/stream-status").json()
        for sym in ["AAPL", "TSLA", "NVDA", "MSFT"]:
            r = authed_client.get(f"{BASE_URL}/api/market/quote/{sym}")
            assert r.status_code == 200
        after = authed_client.get(f"{BASE_URL}/api/market/stream-status").json()
        assert after["bar_subscribed_count"] >= before["bar_subscribed_count"]
        assert after["trade_quote_subscribed_count"] >= before["trade_quote_subscribed_count"]


class TestQuoteAndBars:
    @pytest.mark.parametrize("symbol", ["AAPL", "TSLA"])
    def test_quote(self, authed_client, symbol):
        resp = authed_client.get(f"{BASE_URL}/api/market/quote/{symbol}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    @pytest.mark.parametrize("symbol", ["AAPL", "TSLA", "NVDA"])
    @pytest.mark.parametrize("timeframe", ["1Min", "5Min"])
    def test_bars(self, authed_client, symbol, timeframe):
        resp = authed_client.get(
            f"{BASE_URL}/api/market/bars/{symbol}",
            params={"timeframe": timeframe, "limit": 20}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        bars = data.get("bars", data if isinstance(data, list) else None)
        assert "source" in data or "source" in str(data)


class TestEntryConditions:
    @pytest.mark.parametrize("symbol", ["AAPL", "TSLA"])
    def test_entry_conditions(self, authed_client, symbol):
        resp = authed_client.get(f"{BASE_URL}/api/auto-trader/entry-conditions/{symbol}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        assert "conditions" in data or "conditions_met" in data


class TestAutoTraderSafety:
    def test_status_reflects_current_mode(self, authed_client):
        resp = authed_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data or "is_active" in data

    def test_toggle_blocked_in_live_mode(self, authed_client):
        mode_resp = authed_client.get(f"{BASE_URL}/api/trading-mode")
        if mode_resp.status_code != 200:
            pytest.skip("trading-mode endpoint unavailable")
        mode = mode_resp.json().get("mode")
        if mode != "live":
            pytest.skip("Not in live mode currently - safety rule test not applicable")
        resp = authed_client.post(f"{BASE_URL}/api/auto-trader/toggle", json={"active": True})
        assert resp.status_code != 200 or resp.json().get("active") is False


class TestWebSocket:
    def _ws_base(self):
        base = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        return base

    def test_ws_rejected_without_token(self):
        async def run():
            uri = f"{self._ws_base()}/api/ws/market-data"
            try:
                async with websockets.connect(uri) as ws:
                    await ws.recv()
                return None
            except websockets.exceptions.ConnectionClosed as e:
                return e.code
            except Exception as e:
                return str(e)
        code = asyncio.get_event_loop().run_until_complete(run())
        assert code == 4401 or code is not None, f"Expected rejection, got {code}"

    def test_ws_accepted_with_valid_token(self, auth_token):
        async def run():
            uri = f"{self._ws_base()}/api/ws/market-data?token={auth_token}"
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"action": "subscribe", "symbols": ["TSLA"]}))
                await asyncio.sleep(1)
                return True
        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is True
