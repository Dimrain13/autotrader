"""
Tests for the stop-loss "insufficient qty" retry-loop fix (iteration_30 -> follow-up).

Covers:
1. GET /api/orders?status=open / status=new (or any string) regression - must
   return HTTP 200 w/ valid array, not 422/500 (alpaca_service.get_orders now
   uses QueryOrderStatus with a safe fallback instead of the wrong OrderStatus enum).
2. position_monitor_service._sell_with_dedup() unit tests (deterministic,
   mocked alpaca_service - avoids relying on live market timing):
   a) existing open sell order < stale_after_seconds old -> returns None,
      does NOT call place_market_order (prevents duplicate submission).
   b) existing open sell order >= stale_after_seconds old -> cancels it then
      calls place_market_order (recovers from a stuck/never-filled order).
   c) no existing open order -> calls place_market_order directly (normal path).
3. NEW (this session): reactive force-cancel-and-retry when place_market_order
   itself raises an "insufficient qty" rejection despite the pre-check missing
   a resting order (real incident: ATPC stop-loss blocked 17+ min) -
   a) rejection containing "insufficient qty" -> re-checks open orders,
      force-cancels any resting SELL order(s), retries place_market_order ONCE.
   b) unrelated exceptions (e.g. "insufficient buying power", network errors)
      must propagate unchanged, NOT be swallowed/retried.
   c) retry that also fails should raise (no infinite loop / silent swallow).
"""
import os
import pytest
import requests
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

sys.path.insert(0, '/app/backend')
from services.position_monitor_service import PositionMonitorService


# ---------------------------------------------------------------------------
# 1. GET /api/orders?status=<x> regression (previously 422/500 for non-'all')
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def auth_token():
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


class TestOrdersStatusRegression:
    @pytest.mark.parametrize("status", ["open", "new", "closed", "all", "bogus_status_xyz"])
    def test_get_orders_status_returns_200(self, auth_headers, status):
        resp = requests.get(f"{BASE_URL}/api/orders", params={"status": status}, headers=auth_headers)
        assert resp.status_code == 200, f"status={status} returned {resp.status_code}: {resp.text}"
        data = resp.json()
        assert isinstance(data, list), f"Expected list response for status={status}, got {type(data)}"

    def test_get_orders_default_no_status_param(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/orders", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# 2. _sell_with_dedup deterministic unit tests
# ---------------------------------------------------------------------------

class TestSellWithDedup:
    def setup_method(self):
        self.monitor = PositionMonitorService()

    @pytest.mark.asyncio
    async def test_resting_sell_order_force_cancelled_regardless_of_age(self):
        """Existing sell order (e.g. a bracket's own stop-loss/take-profit
        leg, or a genuine stale duplicate) is force-cancelled immediately
        and replaced with a fresh sell - no more waiting up to
        stale_after_seconds to see if it fills on its own (that used to
        block/delay every legitimate sell placed shortly after a bracket
        buy, since the bracket ALWAYS leaves its own resting sell leg -
        found by testing_agent_v4 immediately after the bracket-at-entry
        fix, iteration_40)."""
        recent_order = {
            "order_id": "bracket-leg-1",
            "symbol": "ATPC",
            "side": "sell",
            "status": "new",
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.return_value = [recent_order]
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "fresh-sell-1"})
            mock_alpaca.cancel_order = MagicMock(return_value=True)

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.cancel_order.assert_called_once_with("bracket-leg-1")
            mock_alpaca.place_market_order.assert_called_once_with("ATPC", 3020, "sell")
            assert result == {"order_id": "fresh-sell-1"}

    @pytest.mark.asyncio
    async def test_stale_pending_order_cancelled_and_replaced(self):
        """Existing sell order >= stale_after_seconds old -> cancel then place a fresh sell"""
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=15)
        stale_order = {
            "order_id": "stale-1",
            "symbol": "ATPC",
            "side": "sell",
            "status": "new",
            "created_at": stale_time.isoformat().replace('+00:00', 'Z')
        }
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.return_value = [stale_order]
            mock_alpaca.cancel_order = MagicMock(return_value=True)
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "fresh-1", "filled_avg_price": 1.23})

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.cancel_order.assert_called_once_with("stale-1")
            mock_alpaca.place_market_order.assert_called_once_with("ATPC", 3020, "sell")
            assert result == {"order_id": "fresh-1", "filled_avg_price": 1.23}

    @pytest.mark.asyncio
    async def test_no_open_orders_places_sell_directly(self):
        """No existing open order -> place_market_order called directly (normal path)"""
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.return_value = []
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "direct-1"})
            mock_alpaca.cancel_order = MagicMock()

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.cancel_order.assert_not_called()
            mock_alpaca.place_market_order.assert_called_once_with("ATPC", 3020, "sell")
            assert result == {"order_id": "direct-1"}

    @pytest.mark.asyncio
    async def test_pending_buy_order_resolves_then_sell_proceeds(self):
        """An open BUY order on the same symbol (parent buy not yet filled)
        should briefly poll rather than immediately raise or block forever -
        once the buy order is no longer open (filled), the sell proceeds
        normally. Guards the 'cannot open a short sell while a long buy
        order is open' raw Alpaca 500 found by testing_agent_v4, iteration_40,
        right after every buy started always placing a real bracket order."""
        buy_order = {
            "order_id": "buy-1",
            "symbol": "ATPC",
            "side": "buy",
            "status": "new",
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca, \
             patch('asyncio.sleep', new=AsyncMock()):
            # Pre-loop check sees the pending buy; first in-loop recheck
            # sees it resolved (filled) - sell should proceed normally.
            mock_alpaca.get_open_orders.side_effect = [[buy_order], []]
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "sell-after-buy-fills"})
            mock_alpaca.cancel_order = MagicMock()

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.place_market_order.assert_called_once_with("ATPC", 3020, "sell")
            assert result == {"order_id": "sell-after-buy-fills"}

    @pytest.mark.asyncio
    async def test_pending_buy_order_never_resolves_raises_clean_error(self):
        """If the buy order never fills within the brief polling window,
        raise a clear, user-facing error instead of letting Alpaca's raw
        same-symbol-conflict rejection surface as an opaque 500."""
        buy_order = {
            "order_id": "buy-2",
            "symbol": "ATPC",
            "side": "buy",
            "status": "new",
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca, \
             patch('asyncio.sleep', new=AsyncMock()):
            mock_alpaca.get_open_orders.return_value = [buy_order]  # never resolves
            mock_alpaca.place_market_order = MagicMock()

            with pytest.raises(Exception, match="hasn't filled yet"):
                await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.place_market_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_open_orders_exception_falls_back_to_place_order(self):
        """If get_open_orders itself raises, dedup should degrade gracefully and still attempt the sell"""
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.side_effect = Exception("network blip")
            mock_alpaca.place_market_order = MagicMock(return_value={"order_id": "fallback-1"})

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.place_market_order.assert_called_once_with("ATPC", 3020, "sell")
            assert result == {"order_id": "fallback-1"}


class TestReactiveForceCancelOnInsufficientQty:
    """NEW this session: _sell_with_dedup's try/except around the final
    place_market_order call - reacts immediately to Alpaca's own
    authoritative "insufficient qty" rejection instead of waiting for the
    next ~2s tick's pre-check."""

    def setup_method(self):
        self.monitor = PositionMonitorService()

    @pytest.mark.asyncio
    async def test_insufficient_qty_rejection_force_cancels_and_retries(self):
        """First place_market_order call raises 'insufficient qty available for
        order' (real Alpaca wording) despite pre-check seeing NO open orders
        (simulating the pre-check missing a resting order due to a race/lag).
        Should re-check open orders, force-cancel the resting SELL order,
        then retry place_market_order ONCE and return its result."""
        blocking_sell = {
            "order_id": "blocking-sell-1",
            "symbol": "ATPC",
            "side": "sell",
            "status": "new",
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            # Pre-check (first get_open_orders call) sees nothing; the
            # re-check after rejection (second call) finds the blocker.
            mock_alpaca.get_open_orders.side_effect = [[], [blocking_sell]]
            mock_alpaca.cancel_order = MagicMock(return_value=True)
            mock_alpaca.place_market_order = MagicMock(
                side_effect=[
                    Exception("insufficient qty available for order (requested: 3020, available: 0)"),
                    {"order_id": "retry-success-1", "filled_avg_price": 1.5}
                ]
            )

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            assert mock_alpaca.place_market_order.call_count == 2
            mock_alpaca.cancel_order.assert_called_once_with("blocking-sell-1")
            assert result == {"order_id": "retry-success-1", "filled_avg_price": 1.5}

    @pytest.mark.asyncio
    async def test_unrelated_exception_propagates_unchanged(self):
        """A rejection NOT containing 'insufficient qty' (e.g. insufficient
        buying power, or a generic network/API error) must be re-raised as-is,
        not caught/retried by the new fallback."""
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.return_value = []
            mock_alpaca.place_market_order = MagicMock(
                side_effect=Exception("insufficient buying power")
            )
            mock_alpaca.cancel_order = MagicMock()

            with pytest.raises(Exception, match="insufficient buying power"):
                await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.cancel_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_also_fails_raises_not_swallowed(self):
        """If the retry after force-cancel ALSO fails, the exception must
        propagate (no infinite loop, no silent swallow leaving the position
        unprotected without any error surfaced upstream)."""
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.side_effect = [[], []]
            mock_alpaca.cancel_order = MagicMock()
            mock_alpaca.place_market_order = MagicMock(
                side_effect=[
                    Exception("insufficient qty available for order"),
                    Exception("insufficient qty available for order")
                ]
            )

            with pytest.raises(Exception, match="insufficient qty"):
                await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            assert mock_alpaca.place_market_order.call_count == 2

    @pytest.mark.asyncio
    async def test_only_sell_side_orders_force_cancelled_not_buy(self):
        """The re-check after rejection must only force-cancel SELL orders on
        the symbol, never a resting BUY order (which is unrelated to the
        stuck-exit scenario and shouldn't be touched)."""
        buy_order = {"order_id": "buy-1", "symbol": "ATPC", "side": "buy", "status": "new",
                     "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}
        sell_order = {"order_id": "sell-1", "symbol": "ATPC", "side": "sell", "status": "new",
                      "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}
        with patch('services.position_monitor_service.alpaca_service') as mock_alpaca:
            mock_alpaca.get_open_orders.side_effect = [[], [buy_order, sell_order]]
            mock_alpaca.cancel_order = MagicMock(return_value=True)
            mock_alpaca.place_market_order = MagicMock(
                side_effect=[
                    Exception("insufficient qty available for order"),
                    {"order_id": "retry-2"}
                ]
            )

            result = await self.monitor._sell_with_dedup("ATPC", 3020, stale_after_seconds=10)

            mock_alpaca.cancel_order.assert_called_once_with("sell-1")
            assert result == {"order_id": "retry-2"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
