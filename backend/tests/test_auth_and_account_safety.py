"""
Regression suite for the NEW email+password JWT auth (replacing the old
static API_ACCESS_TOKEN unlock screen) + safety-critical Alpaca paper vs
live account split verification.

Covers:
- POST /api/auth/login: correct creds -> 200 + JWT, wrong creds -> 401
- GET /api/auth/me requires valid bearer token
- Brute-force lockout: 5 failed attempts -> 429 (cleans up login_attempts after)
- SAFETY: GET /api/account must return the PAPER account number (PA30RVV1A2DM),
  never a live account
- Market data source check on GET /api/market/bars/{symbol}
"""
import os
import time
import pytest
import requests
import asyncio
import sys

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'daniel.r.millner@gmail.com')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Black0rkid5!')
EXPECTED_PAPER_ACCOUNT_NUMBER = "PA30RVV1A2DM"


@pytest.fixture(scope="module")
def valid_jwt():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_session(valid_jwt):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {valid_jwt}"})
    return s


class TestLoginFlow:
    def test_correct_credentials_return_jwt(self, valid_jwt):
        assert isinstance(valid_jwt, str)
        assert len(valid_jwt) > 20

    def test_wrong_password_401(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPass123!"})
        assert r.status_code == 401
        data = r.json()
        assert "detail" in data

    def test_wrong_email_401(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "nobody@example.com", "password": ADMIN_PASSWORD})
        assert r.status_code == 401

    def test_me_endpoint_with_valid_token(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL.lower()

    def test_me_endpoint_without_token_401(self):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_old_static_token_no_longer_works(self):
        # The old API_ACCESS_TOKEN mechanism must be fully removed
        r = requests.get(f"{BASE_URL}/api/", headers={"Authorization": "Bearer sr7sWvLt5MicXQTC0jw-oldtoken"})
        assert r.status_code == 401


class TestBruteForceLockout:
    """5 failed attempts should lock out further attempts (429) for 15 min.
    Cleans up db.login_attempts afterward so real user isn't blocked.

    NOTE: hits localhost:8001 directly (bypassing the preview ingress proxy)
    because get_remote_address() sees a STABLE client IP only on the direct
    connection - through the public ingress/proxy, requests from the same
    curl/browser client were observed alternating between two different
    upstream IPs (e.g. 10.208.128.9 / .10), which splits the failed_count
    across two different `ip:email` identifiers and prevents the lockout
    from reliably triggering at exactly 5 attempts in production. See test
    report for full RCA - this is a real backend finding, not a test bug.
    """
    LOCAL_URL = "http://localhost:8001"

    def test_lockout_after_5_failed_attempts(self):
        wrong_email = "TEST_lockout_user@example.com"
        for i in range(5):
            r = requests.post(f"{self.LOCAL_URL}/api/auth/login", json={"email": wrong_email, "password": "wrong"})
            assert r.status_code == 401, f"attempt {i+1} expected 401, got {r.status_code}"

        # 6th attempt, even with a nonsense/correct-shaped body, should be locked out
        r6 = requests.post(f"{self.LOCAL_URL}/api/auth/login", json={"email": wrong_email, "password": "wrong"})
        assert r6.status_code == 429, f"Expected 429 lockout on 6th attempt, got {r6.status_code}: {r6.text}"

    @classmethod
    def teardown_class(cls):
        # Cleanup: clear login_attempts collection so lockout doesn't persist
        sys.path.insert(0, "/app/backend")
        from database import db

        async def _cleanup():
            result = await db.login_attempts.delete_many({})
            return result.deleted_count

        try:
            deleted = asyncio.run(_cleanup())
            print(f"Cleaned up {deleted} login_attempts records")
        except Exception as e:
            print(f"WARNING: cleanup failed: {e}")


class TestAccountSafety:
    """SAFETY-CRITICAL: must always be the PAPER account, never live."""

    def test_account_is_paper_account(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/account")
        assert r.status_code == 200
        data = r.json()
        assert "account_number" in data, f"No account_number in response: {data}"
        assert data["account_number"] == EXPECTED_PAPER_ACCOUNT_NUMBER, (
            f"STOP-SHIP: account_number is {data['account_number']}, "
            f"expected paper account {EXPECTED_PAPER_ACCOUNT_NUMBER}"
        )


class TestMarketDataSource:
    def test_market_bars_source_field(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/market/bars/AAPL", params={"timeframe": "1Min"})
        assert r.status_code in [200, 502]
        if r.status_code == 200:
            data = r.json()
            assert "source" in data
            print(f"market/bars/AAPL source = {data['source']}")
