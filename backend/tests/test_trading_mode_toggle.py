"""
Backend tests for the PAPER <-> LIVE trading mode toggle feature.
Covers: GET/POST /api/trading-mode, GO LIVE confirmation gating,
auto-trader block in live mode, account switching (paper vs live account_number),
and restart persistence (via app_config._id='trading_mode' doc + supervisor restart).

IMPORTANT: This suite is read-only against Alpaca (GET account only), never
places orders, and ALWAYS ends by restoring PAPER mode (see teardown fixture).
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
ADMIN_EMAIL = "daniel.r.millner@gmail.com"
ADMIN_PASSWORD = "Black0rkid5!"


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip("Authentication failed - skipping trading-mode tests")
    token = resp.json().get("access_token")
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


@pytest.fixture(autouse=True, scope="module")
def ensure_paper_at_end(api_client):
    """Safety net: no matter what happens, always leave the app in PAPER mode."""
    yield
    try:
        api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})
    except Exception:
        pass


# All classes below share stateful, order-dependent trading-mode state on
# the same backend instance. pytest-xdist's --dist loadscope pins each
# *class* (not the whole module) to a worker, so without this group mark
# two classes here could run concurrently on gw0/gw1 and race each other's
# mode switches (observed: 4 spurious failures). Pinning the whole module
# to one xdist group keeps it sequential regardless of worker count.
pytestmark = pytest.mark.xdist_group(name="trading_mode_toggle")


class TestTradingModeInitialState:
    def test_get_trading_mode_initial(self, api_client):
        resp = api_client.get(f"{BASE_URL}/api/trading-mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "paper"
        assert data["paper_available"] is True
        assert data["live_available"] is True
        assert data["auto_trader_active"] is False


class TestGoLiveConfirmationGating:
    def test_switch_live_missing_confirm_rejected(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "live"})
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "GO LIVE" in detail

        # Verify mode remains paper
        follow = api_client.get(f"{BASE_URL}/api/trading-mode")
        assert follow.json()["mode"] == "paper"

    def test_switch_live_wrong_case_confirm_rejected(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "go live"
        })
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "GO LIVE" in detail

        follow = api_client.get(f"{BASE_URL}/api/trading-mode")
        assert follow.json()["mode"] == "paper"

    def test_switch_live_correct_confirm_succeeds(self, api_client):
        resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "GO LIVE"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "live"

        follow = api_client.get(f"{BASE_URL}/api/trading-mode")
        assert follow.json()["mode"] == "live"

        # Switch back to paper immediately for isolation from next test class
        back = api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})
        assert back.status_code == 200
        assert back.json()["mode"] == "paper"


class TestAutoTraderBlockedInLiveMode:
    def test_auto_trader_blocked_while_live(self, api_client):
        # Switch to live
        live_resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "GO LIVE"
        })
        assert live_resp.status_code == 200

        try:
            toggle_resp = api_client.post(f"{BASE_URL}/api/auto-trader/toggle?enabled=true")
            assert toggle_resp.status_code == 400
            detail = toggle_resp.json().get("detail", "")
            assert "live" in detail.lower()

            status_resp = api_client.get(f"{BASE_URL}/api/auto-trader/status")
            assert status_resp.status_code == 200
            assert status_resp.json()["active"] is False
        finally:
            # Always restore paper before continuing
            api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})


class TestAccountSwitchesBetweenPaperAndLive:
    def test_account_number_differs_between_modes(self, api_client):
        paper_account = api_client.get(f"{BASE_URL}/api/account")
        assert paper_account.status_code == 200
        paper_account_number = paper_account.json().get("account_number")
        assert paper_account_number

        live_switch = api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "GO LIVE"
        })
        assert live_switch.status_code == 200

        try:
            live_account = api_client.get(f"{BASE_URL}/api/account")
            assert live_account.status_code == 200
            live_account_number = live_account.json().get("account_number")
            assert live_account_number
            assert live_account_number != paper_account_number, \
                "Live account_number must differ from paper account_number - proves real account switch"
        finally:
            back = api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})
            assert back.status_code == 200

        # Confirm original paper account number returns
        paper_again = api_client.get(f"{BASE_URL}/api/account")
        assert paper_again.status_code == 200
        assert paper_again.json().get("account_number") == paper_account_number


class TestSwitchBackToPaperNoConfirmNeeded:
    def test_switch_to_paper_requires_no_confirm(self, api_client):
        # First go live
        api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "GO LIVE"
        })
        # Switch back with no confirm field at all
        resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"

        follow = api_client.get(f"{BASE_URL}/api/trading-mode")
        assert follow.json()["mode"] == "paper"


class TestRestartPersistence:
    @pytest.mark.skipif(
        os.environ.get("RUN_RESTART_TEST") != "1",
        reason="Restarts the shared backend via supervisor - disruptive to other "
               "tests running concurrently under the default -n 2 xdist workers. "
               "Run explicitly in isolation with RUN_RESTART_TEST=1 and -n 0."
    )
    def test_live_mode_persists_across_restart_and_autotrader_forced_off(self, api_client):
        # Switch to live
        live_resp = api_client.post(f"{BASE_URL}/api/trading-mode", json={
            "mode": "live", "confirm": "GO LIVE"
        })
        assert live_resp.status_code == 200

        # Inspect the persisted doc directly via API before restart is enough
        # to confirm write-through, but the task requires an actual restart.
        os.system("sudo supervisorctl restart backend")
        time.sleep(8)

        # Poll until backend responds again (post-restart)
        deadline = time.time() + 30
        last_exc = None
        data = None
        while time.time() < deadline:
            try:
                resp = api_client.get(f"{BASE_URL}/api/trading-mode", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    break
            except Exception as e:
                last_exc = e
            time.sleep(2)

        assert data is not None, f"Backend did not come back up after restart: {last_exc}"
        assert data["mode"] == "live", "Trading mode should be restored to LIVE from MongoDB after restart"
        assert data["auto_trader_active"] is False, \
            "Auto-trader must be forced OFF on startup when restored mode is LIVE"

        # Restore paper - mandatory per test scope
        back = api_client.post(f"{BASE_URL}/api/trading-mode", json={"mode": "paper"})
        assert back.status_code == 200
        assert back.json()["mode"] == "paper"
