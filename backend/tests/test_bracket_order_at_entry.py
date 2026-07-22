"""
Tests for the "real bracket order at time of buying" fix (2026-07).

User-reported root cause: two manually-placed trades (OTLY, SNTG) filled
during abnormally wide bid/ask spreads (9.5%, 28%) with ZERO real
stop-loss/take-profit order actually resting on the exchange - only a
software poll loop (with a 60s "settling" delay) watched the position.
User's explicit direction: "there should have been a stop loss put in
place at the time of buying, same with take profit."

Fix: both the manual buy-with-stop endpoint (server.py POST /api/orders)
and the autonomous auto-trader's execute_entry() now ALWAYS attempt a real
Alpaca bracket order (resting stop-loss + take-profit legs) immediately at
entry, regardless of stop_type - falling back to a plain market order only
if the bracket placement itself fails. The software position monitor /
auto-trader exit loop still layers dynamic trailing/partial-sell/breakeven
management on top; the existing "insufficient qty" force-cancel-retry
safety net (already proven for stale-order dedup) transparently cancels
the resting bracket leg before any software-triggered sell.

Covers:
1. auto_trader_service.execute_entry() calls place_bracket_order (not just
   place_market_order) with the structural stop/2:1 target as the bracket
   legs, and correctly falls back to place_market_order if the bracket
   placement raises.
2. auto_trader_service.sell_with_retry() force-cancels a resting order and
   retries once on an "insufficient qty" rejection (mirrors the proven
   position_monitor_service._sell_with_dedup pattern), and does NOT swallow
   unrelated exceptions across all retry attempts.
3. Manual buy endpoint (POST /api/orders) with stop_type="trailing" (the
   QuickTradePanel default) results in a real bracket order server-side,
   not just a plain market order - live smoke test against the running
   backend + cleans up the position afterward.
"""
import os
import sys
import pytest
import requests
from unittest.mock import AsyncMock, MagicMock, patch

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

sys.path.insert(0, '/app/backend')
from services.auto_trader_service import AutoTraderService


@pytest.fixture(scope="module")
def auth_token():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "daniel.r.millner@gmail.com",
        "password": "Black0rkid5!"
    })
    if resp.status_code != 200:
        pytest.skip(f"Login failed - skipping authenticated tests: {resp.status_code} {resp.text}")
    return resp.json().get("access_token")


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# 1. Auto-trader execute_entry() always attempts a real bracket order
# ---------------------------------------------------------------------------
class TestAutoTraderExecuteEntryPlacesBracketOrder:
    def setup_method(self):
        self.trader = AutoTraderService()

    @pytest.mark.asyncio
    async def test_execute_entry_uses_bracket_order_with_structural_stop_and_target(self):
        signal = {
            "symbol": "TEST",
            "entry_price": 5.00,
            "stop_loss_price": 4.85,   # structural pullback-low stop
            "target_price": 5.30,      # 2:1 reward:risk target
        }
        with patch('services.auto_trader_service.alpaca_service') as mock_alpaca:
            mock_alpaca.place_bracket_order = MagicMock(return_value={"order_id": "bracket-1", "order_class": "bracket"})
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "market-fallback"})

            result = await self.trader.execute_entry(signal, portfolio_value=10000.0)

            assert result is True
            mock_alpaca.place_bracket_order.assert_called_once()
            args = mock_alpaca.place_bracket_order.call_args[0]
            assert args[0] == "TEST"
            assert args[2] == 4.85  # stop leg == structural stop
            assert args[3] == 5.30  # target leg == 2:1 target
            mock_alpaca.place_market_order.assert_not_called()
            assert self.trader.open_positions["TEST"]["order_id"] == "bracket-1"

    @pytest.mark.asyncio
    async def test_execute_entry_falls_back_to_market_order_if_bracket_fails(self):
        signal = {
            "symbol": "TEST2",
            "entry_price": 5.00,
            "stop_loss_price": 4.85,
            "target_price": 5.30,
        }
        with patch('services.auto_trader_service.alpaca_service') as mock_alpaca:
            mock_alpaca.place_bracket_order = MagicMock(side_effect=Exception("bracket rejected"))
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "market-fallback-1"})

            result = await self.trader.execute_entry(signal, portfolio_value=10000.0)

            assert result is True
            mock_alpaca.place_bracket_order.assert_called_once()
            mock_alpaca.place_market_order.assert_called_once_with("TEST2", pytest.approx(200, rel=0.5), "buy")
            assert self.trader.open_positions["TEST2"]["order_id"] == "market-fallback-1"


# ---------------------------------------------------------------------------
# 2. sell_with_retry() force-cancel-and-retry on insufficient qty
# ---------------------------------------------------------------------------
class TestSellWithRetryForceCancel:
    def setup_method(self):
        self.trader = AutoTraderService()

    @pytest.mark.asyncio
    async def test_insufficient_qty_force_cancels_bracket_leg_and_retries(self):
        """First sell attempt hits 'insufficient qty' (blocked by the entry
        bracket's resting stop/target leg) - should cancel it and retry
        immediately within the same attempt, not just blindly retry."""
        with patch('services.auto_trader_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.return_value = [
                {"order_id": "bracket-stop-leg", "side": "sell", "status": "new"}
            ]
            mock_alpaca.cancel_order = MagicMock(return_value=True)
            mock_alpaca.place_market_order = MagicMock(
                side_effect=[Exception("insufficient qty available for order"), {"order_id": "sell-ok"}]
            )

            result = await self.trader.sell_with_retry("TEST3", 100, "STOP LOSS")

            assert result is True
            mock_alpaca.cancel_order.assert_called_once_with("bracket-stop-leg")
            assert mock_alpaca.place_market_order.call_count == 2

    @pytest.mark.asyncio
    async def test_unrelated_exception_does_not_force_cancel(self):
        """A non-'insufficient qty' failure (e.g. insufficient buying power on
        a same-symbol re-buy attempt, network blip) should just retry via the
        normal attempt loop, never trigger the force-cancel path."""
        with patch('services.auto_trader_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders = MagicMock()
            mock_alpaca.cancel_order = MagicMock()
            mock_alpaca.place_market_order = MagicMock(side_effect=Exception("some other error"))

            with patch('asyncio.sleep', new=AsyncMock()):
                result = await self.trader.sell_with_retry("TEST4", 100, "STOP LOSS", max_retries=2)

            assert result is False
            mock_alpaca.get_open_orders.assert_not_called()
            mock_alpaca.cancel_order.assert_not_called()
            assert mock_alpaca.place_market_order.call_count == 2


# ---------------------------------------------------------------------------
# 3. Live smoke test: manual buy endpoint places a real bracket order
# ---------------------------------------------------------------------------
class TestManualBuyEndpointPlacesRealBracketOrder:
    def test_trailing_stop_type_still_results_in_bracket_order_class(self, auth_headers):
        """QuickTradePanel's default stop_type is 'trailing' - before this
        fix, that path used a plain market order with ZERO resting
        protection. Now it should always come back with order_class
        'bracket' (unless Alpaca itself rejected the bracket, which is not
        expected for a liquid, regular-hours symbol like AAPL)."""
        resp = requests.post(f"{BASE_URL}/api/orders", headers=auth_headers, json={
            "symbol": "AAPL", "qty": 1, "side": "buy",
            "stop_loss_pct": 1, "take_profit_pct": 2, "stop_type": "trailing",
            "trailing_stop_pct": 1, "partial_sell_pct": 50,
            "partial_sell_trigger_pct": 2, "move_to_breakeven": True,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("order_class") == "bracket", f"Expected a real bracket order, got: {data}"
        assert data.get("monitored") is True  # software layer still active for dynamic trailing

        # Clean up - close the test position immediately
        requests.post(f"{BASE_URL}/api/orders", headers=auth_headers, json={
            "symbol": "AAPL", "qty": 1, "side": "sell"
        })
