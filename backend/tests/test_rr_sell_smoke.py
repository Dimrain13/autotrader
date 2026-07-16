"""
Backend tests for this session's features:
- Risk:Reward ratio settings sync (/api/auto-trader/settings, /api/auto-trader/status)
- Open positions / sell order flow (/api/positions, /api/orders)
- Regression smoke test: /api/auto-trader/process, /api/scanner/scan (scan_market cached path)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
LOGIN_EMAIL = "daniel.r.millner@gmail.com"
LOGIN_PASSWORD = "Black0rkid5!"


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": LOGIN_EMAIL, "password": LOGIN_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Login failed - skipping authenticated tests ({resp.status_code}: {resp.text})")
    token = resp.json().get("access_token")
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


class TestRiskRewardRatioSettings:
    def test_update_reward_risk_ratio(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"reward_risk_ratio": 3.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_status_reflects_updated_ratio(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
        assert data["strategy"]["reward_risk_ratio"] == 3.0

    def test_update_ratio_again_and_verify(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/settings", json={"reward_risk_ratio": 2.0})
        assert resp.status_code == 200
        resp2 = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp2.json()["strategy"]["reward_risk_ratio"] == 2.0


class TestPositionsAndOrders:
    def test_get_positions(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for pos in data:
            assert "symbol" in pos
            assert "qty" in pos

    def test_get_orders(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/orders")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestRegressionSmoke:
    def test_auto_trader_process(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/auto-trader/process")
        assert resp.status_code == 200

    def test_scanner_scan(self, api_client):
        criteria = {
            "min_price": 2,
            "max_price": 20,
            "min_change": 10,
            "min_volume_ratio": 5,
            "max_float": 20000000
        }
        resp = api_client.post(f"{BASE_URL}/api/scanner/scan", json=criteria, timeout=30)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_auto_trader_status_smoke(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "strategy" in data
