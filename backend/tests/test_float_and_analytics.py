"""
Tests for this session's changes:
- Real float data (SEC EDGAR) replacing fake random float in scanner
- Bounded analytics queries (trade-history, missed-opportunities)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
TOKEN = os.environ.get('API_ACCESS_TOKEN')


@pytest.fixture
def api_client():
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    })
    return session


class TestAnalyticsBounded:
    def test_trade_history_analytics_default(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/trade-history/analytics", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_trades" in data
        assert "win_rate" in data
        assert "total_pnl" in data
        assert isinstance(data["total_trades"], int)

    def test_trade_history_analytics_alltime(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/trade-history/analytics?days=0", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_trades" in data
        assert "win_rate" in data

    def test_missed_opportunities_analytics_default(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/missed-opportunities/analytics", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_missed" in data
        assert "by_criteria" in data
        assert "by_date" in data

    def test_missed_opportunities_analytics_alltime(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/missed-opportunities/analytics?days=0", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_missed" in data


class TestScannerRealFloat:
    def test_demo_scan_instant(self, api_client):
        """Sanity check demo scanner still works (untouched code path)"""
        resp = api_client.get(f"{BASE_URL}/api/scanner/demo", timeout=30)
        assert resp.status_code == 200

    def test_real_scan_float_data_consistent(self, api_client):
        """
        Run real scan twice a few seconds apart, verify float_data_source
        is never 'estimated' and shares_outstanding for same symbol doesn't
        randomly change between calls (cached/real, not random).
        """
        criteria = {
            "min_price": 2,
            "max_price": 20,
            "min_change": 10,
            "min_volume_ratio": 5,
            "max_float": 20000000
        }
        resp1 = api_client.post(f"{BASE_URL}/api/scanner/scan", json=criteria, timeout=90)
        assert resp1.status_code == 200
        results1 = resp1.json()
        results1 = results1.get("results", results1) if isinstance(results1, dict) else results1

        if not isinstance(results1, list) or len(results1) == 0:
            pytest.skip("No scanner results returned (market conditions) - cannot verify float consistency")

        time.sleep(3)

        resp2 = api_client.post(f"{BASE_URL}/api/scanner/scan", json=criteria, timeout=90)
        assert resp2.status_code == 200
        results2 = resp2.json()
        results2 = results2.get("results", results2) if isinstance(results2, dict) else results2

        map1 = {r["symbol"]: r for r in results1 if "symbol" in r}
        map2 = {r["symbol"]: r for r in results2 if "symbol" in r}

        for r in results1:
            assert r.get("float_data_source") in ("sec_edgar", "IB", "unknown", "pending", None), \
                f"Unexpected float_data_source: {r.get('float_data_source')}"
            assert r.get("float_data_source") != "estimated"

        common_symbols = set(map1.keys()) & set(map2.keys())
        for sym in common_symbols:
            so1 = map1[sym].get("shares_outstanding")
            so2 = map2[sym].get("shares_outstanding")
            if so1 is not None and so2 is not None:
                assert so1 == so2, f"{sym}: shares_outstanding changed between calls ({so1} vs {so2}) - looks random"
