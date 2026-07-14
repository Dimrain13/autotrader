"""
Regression tests for chart data-fetching fix (Trading.js / alpaca_service.get_bars).
Covers:
- /api/market/bars/{symbol} returns <= requested limit, never more
- bar count scales sensibly with limit (calendar-day padding fix)
- timestamps are ascending / chronological
- /api/trading-mode still reports 'paper' (no regression from unrelated prior feature)
"""
import os
import pytest
import requests
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

ADMIN_EMAIL = "daniel.r.millner@gmail.com"
ADMIN_PASSWORD = "Black0rkid5!"


@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip("Login failed - skipping authenticated tests")
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


def _get_bars(headers, symbol, timeframe, limit, use_fallback=None):
    params = f"timeframe={timeframe}&limit={limit}"
    if use_fallback is not None:
        params += f"&use_fallback={str(use_fallback).lower()}"
    resp = requests.get(f"{BASE_URL}/api/market/bars/{symbol}?{params}", headers=headers)
    return resp


def _extract_bars(data):
    if isinstance(data, list):
        return data
    return data.get("bars", [])


class TestBarsLimitCorrectness:
    def test_1min_limit_780(self, auth_headers):
        resp = _get_bars(auth_headers, "AAPL", "1Min", 780)
        assert resp.status_code == 200
        bars = _extract_bars(resp.json())
        assert len(bars) <= 780
        assert len(bars) > 0

    def test_5min_limit_156(self, auth_headers):
        resp = _get_bars(auth_headers, "AAPL", "5Min", 156)
        assert resp.status_code == 200
        bars = _extract_bars(resp.json())
        assert len(bars) <= 156
        assert len(bars) > 0

    def test_bars_chronological_ascending(self, auth_headers):
        resp = _get_bars(auth_headers, "AAPL", "1Min", 780)
        bars = _extract_bars(resp.json())
        timestamps = [datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00")) for b in bars]
        assert timestamps == sorted(timestamps), "Bars must be in ascending chronological order"


class TestCalendarDayPaddingScaling:
    def test_limit_scales_with_request(self, auth_headers):
        """1 day (390) vs 2 days (780) vs 3 days (1170) - larger limit should
        return proportionally more bars (not capped at a fixed elapsed-minutes
        window regardless of limit, as the pre-fix bug caused)."""
        r390 = _extract_bars(_get_bars(auth_headers, "AAPL", "1Min", 390).json())
        r780 = _extract_bars(_get_bars(auth_headers, "AAPL", "1Min", 780).json())
        r1170 = _extract_bars(_get_bars(auth_headers, "AAPL", "1Min", 1170).json())

        assert len(r390) <= 390
        assert len(r780) <= 780
        assert len(r1170) <= 1170

        # Larger limits should generally return >= bars than smaller limits
        # (allowing equality only if genuinely insufficient real data exists)
        assert len(r780) >= len(r390), f"780-limit ({len(r780)}) should be >= 390-limit ({len(r390)})"
        assert len(r1170) >= len(r780), f"1170-limit ({len(r1170)}) should be >= 780-limit ({len(r780)})"


class TestTradingModeNoRegression:
    def test_trading_mode_still_paper(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/trading-mode", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("mode") == "paper", f"Expected mode='paper', got {data}"
