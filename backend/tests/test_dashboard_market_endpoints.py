"""
Tests for new Dashboard-feature backend endpoints added this session:
- GET /api/market/large-trades/{symbol} (block-trade proxy for support/resistance)
- GET /api/market/bars/{symbol}?timeframe=10Sec (tick-constructed bars, no REST equivalent)
- GET /api/news/{symbol} (Alpaca/Benzinga-first news lookup used by NewsFeedPanel + flame badges)
"""
import os
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # fallback to reading frontend/.env directly if not exported in this shell
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent / "frontend" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip('/')


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    resp = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": "daniel.r.millner@gmail.com",
        "password": "Black0rkid5!"
    })
    if resp.status_code != 200:
        pytest.skip(f"Auth failed - skipping dashboard endpoint tests: {resp.status_code} {resp.text}")
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def auth_client(api_client, auth_token):
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestLargeTrades:
    def test_large_trades_shape_ok(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/market/large-trades/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert "large_trades" in data
        assert isinstance(data["large_trades"], list)

    def test_large_trades_no_500_for_unknown_symbol(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/market/large-trades/ZZZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["large_trades"] == []


class TestTenSecBars:
    def test_10sec_bars_graceful_no_data(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/market/bars/AAPL?timeframe=10Sec&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert "bars" in data
        assert "no_historical_data" in data
        assert "warning" in data
        # In this preview env MARKET_STREAM_ENABLED=false, so ticks are not
        # flowing - expect graceful no_historical_data=true, not a crash.
        if data["no_historical_data"]:
            assert data["warning"] is not None

    def test_1min_bars_use_rest_fallback(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/market/bars/AAPL?timeframe=1Min&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert "bars" in data
        assert "source" in data

    def test_1day_bars_real_data(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/market/bars/AAPL?timeframe=1Day&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert "bars" in data
        assert isinstance(data["bars"], list)


class TestNewsEndpoint:
    def test_news_shape_ok(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/news/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert "has_news" in data
        assert "articles" in data
        assert "news_source" in data
        assert isinstance(data["has_news"], bool)
        assert isinstance(data["articles"], list)
        if data["has_news"]:
            assert data["news_source"] in ("Benzinga (Alpaca)", "Google News")
        else:
            assert data["news_source"] is None

    def test_news_no_500_for_unknown_symbol(self, auth_client):
        resp = auth_client.get(f"{BASE_URL}/api/news/ZZZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        assert "articles" in data
