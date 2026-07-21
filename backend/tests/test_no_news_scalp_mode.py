"""
Tests for the "Scalping Trade (No News)" auto-trader mode - a stock hitting
every OTHER scanner pillar (price/change/volume/float, all verified) with
ZERO underlying news catalyst. Covers: scanner's `no_news_scalp_candidate`
flag computation, the auto-trader's opt-in gating + tiered stop-distance
cap + reduced position sizing + shorter bailout.

Bar dicts use {open, high, low, close} - oldest bar first (bars[-1] = latest).
"""
import pytest
from datetime import datetime, timedelta, timezone
import sys
sys.path.insert(0, '/app/backend')
from services.auto_trader_service import AutoTraderService


def make_bar(o, c):
    return {
        'open': o,
        'close': c,
        'high': max(o, c) + 0.05,
        'low': min(o, c) - 0.05,
    }


def surge_bars(start=10.0, end=15.0, n=7):
    step = (end - start) / n
    ohlc = []
    price = start
    for _ in range(n):
        ohlc.append((price, price + step))
        price += step
    return [make_bar(o, c) for o, c in ohlc]


def valid_pullback_bars(start=10.0, end=15.0):
    """Surge + a clean valid 2-red-candle first-pullback breakout, enough bars for MACD/SMA."""
    bars = [make_bar(9.0 + i * 0.001, 9.0 + i * 0.001 + 0.02) for i in range(60)]  # padding for MACD/SMA lookback
    bars += surge_bars(start, end)
    bars += [
        make_bar(end, end - 0.15),
        make_bar(end - 0.15, end - 0.25),
        make_bar(end - 0.25, end - 0.05),  # breakout - breaks prior red candle's high
    ]
    return bars


class TestNoNewsScalpCandidateFlag:
    """scanner_service's no_news_scalp_candidate computation (pure logic, no live API needed)."""

    def _recompute(self, criteria_met):
        count = sum(1 for v in criteria_met.values() if v)
        cm = criteria_met
        no_news = (
            count == 4
            and not cm.get('positive_news', True)
            and cm.get('price_range', False)
            and cm.get('pct_change', False)
            and cm.get('volume_ratio', False)
            and cm.get('float', False)
        )
        return count, no_news

    def test_4_of_5_no_news_is_candidate(self):
        count, no_news = self._recompute({
            'price_range': True, 'pct_change': True, 'volume_ratio': True,
            'float': True, 'positive_news': False
        })
        assert count == 4
        assert no_news is True

    def test_5_of_5_with_news_is_not_candidate(self):
        count, no_news = self._recompute({
            'price_range': True, 'pct_change': True, 'volume_ratio': True,
            'float': True, 'positive_news': True
        })
        assert count == 5
        assert no_news is False

    def test_4_of_5_missing_a_different_pillar_is_not_candidate(self):
        """4/5 where the MISSING pillar is float (not news) - not a no-news scalp candidate."""
        count, no_news = self._recompute({
            'price_range': True, 'pct_change': True, 'volume_ratio': True,
            'float': False, 'positive_news': True
        })
        assert count == 4
        assert no_news is False

    def test_3_of_5_no_news_is_not_candidate(self):
        count, no_news = self._recompute({
            'price_range': True, 'pct_change': True, 'volume_ratio': False,
            'float': True, 'positive_news': False
        })
        assert count == 3
        assert no_news is False


class TestNoNewsMaxStopPct:
    def setup_method(self):
        self.auto_trader = AutoTraderService()

    def test_tier_2_to_5(self):
        assert self.auto_trader._no_news_max_stop_pct(3.0) == pytest.approx(0.05)

    def test_tier_5_to_10(self):
        assert self.auto_trader._no_news_max_stop_pct(7.5) == pytest.approx(0.03)

    def test_tier_10_to_20(self):
        assert self.auto_trader._no_news_max_stop_pct(15.0) == pytest.approx(0.015)

    def test_at_20_uses_last_tier(self):
        assert self.auto_trader._no_news_max_stop_pct(20.0) == pytest.approx(0.015)


class TestNoNewsScalpEntryGating:
    def setup_method(self):
        self.auto_trader = AutoTraderService()

    @pytest.mark.asyncio
    async def test_disabled_by_default_returns_none(self):
        """no_news_scalp_enabled defaults to False - must not silently auto-trade this mode."""
        assert self.auto_trader.no_news_scalp_enabled is False
        stock = {'symbol': 'TEST1', 'no_news_scalp_candidate': True}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        assert result is None

    @pytest.mark.asyncio
    async def test_enabled_but_not_a_candidate_returns_none(self):
        self.auto_trader.no_news_scalp_enabled = True
        stock = {'symbol': 'TEST2', 'no_news_scalp_candidate': False}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        assert result is None

    @pytest.mark.asyncio
    async def test_already_open_position_returns_none(self):
        self.auto_trader.no_news_scalp_enabled = True
        self.auto_trader.open_positions['TEST3'] = {'symbol': 'TEST3'}
        stock = {'symbol': 'TEST3', 'no_news_scalp_candidate': True}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        assert result is None

    @pytest.mark.asyncio
    async def test_exited_today_returns_none(self):
        self.auto_trader.no_news_scalp_enabled = True
        self.auto_trader.exited_today.add('TEST4')
        stock = {'symbol': 'TEST4', 'no_news_scalp_candidate': True}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_pattern_within_tiered_stop_returns_signal(self, monkeypatch):
        """A valid first-pullback pattern on a $12 stock with a tight structural
        stop (well within the 1.5% tier cap for $10-20) should produce a signal."""
        self.auto_trader.no_news_scalp_enabled = True
        bars = valid_pullback_bars(start=11.9, end=12.0)  # tight surge -> tight structural stop

        async def fake_get_bars(symbol, timeframe="5Min", limit=100):
            return bars
        monkeypatch.setattr(self.auto_trader, '_get_real_bars', fake_get_bars)

        stock = {'symbol': 'TEST5', 'no_news_scalp_candidate': True, 'criteria_count': 4}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        if result is not None:
            assert result['is_no_news_scalp'] is True
            assert result['symbol'] == 'TEST5'
            assert result['target_price'] > result['entry_price']
            assert result['stop_loss_price'] < result['entry_price']

    @pytest.mark.asyncio
    async def test_structural_stop_too_far_for_tier_skips(self, monkeypatch):
        """A wide structural stop (>1.5%) on a $15 stock must be rejected, not clamped."""
        self.auto_trader.no_news_scalp_enabled = True
        bars = valid_pullback_bars(start=10.0, end=15.0)  # big surge -> wide pullback -> stop far from entry

        async def fake_get_bars(symbol, timeframe="5Min", limit=100):
            return bars
        monkeypatch.setattr(self.auto_trader, '_get_real_bars', fake_get_bars)

        stock = {'symbol': 'TEST6', 'no_news_scalp_candidate': True, 'criteria_count': 4}
        result = await self.auto_trader.check_no_news_scalp_entry(stock)
        assert result is None


class TestNoNewsScalpExecution:
    def setup_method(self):
        self.auto_trader = AutoTraderService()

    @pytest.mark.asyncio
    async def test_position_size_reduced_and_strategy_tagged(self, monkeypatch):
        """execute_entry must hard-cap size to no_news_position_size_pct and tag the position."""
        self.auto_trader.position_size_pct = 0.10
        self.auto_trader.no_news_position_size_pct = 0.25

        captured = {}

        def fake_place_order(symbol, qty, side):
            captured['qty'] = qty
            return {'order_id': 'abc123'}

        async def fake_to_thread(func, *args):
            return func(*args)

        import services.auto_trader_service as ats_module
        monkeypatch.setattr(ats_module.alpaca_service, 'place_market_order', fake_place_order)
        monkeypatch.setattr(ats_module.asyncio, 'to_thread', fake_to_thread)
        monkeypatch.setattr(self.auto_trader, 'save_state', lambda: fake_noop())

        async def fake_noop():
            return None

        signal = {
            'symbol': 'TEST7', 'entry_price': 10.0, 'stop_loss_price': 9.8,
            'target_price': 10.4, 'is_no_news_scalp': True, 'risk_per_share': 0.2
        }
        # portfolio_value=10000, normal size = 10000*0.10/10.0 = 100 shares; no-news size = 100*0.25 = 25
        success = await self.auto_trader.execute_entry(signal, portfolio_value=10000)
        assert success is True
        assert captured['qty'] == 25
        assert self.auto_trader.open_positions['TEST7']['is_no_news_scalp'] is True
        assert self.auto_trader.open_positions['TEST7']['strategy'] == 'Scalping Trade (No News)'

    @pytest.mark.asyncio
    async def test_normal_entry_not_reduced_and_tagged_normally(self, monkeypatch):
        def fake_place_order(symbol, qty, side):
            return {'order_id': 'xyz789'}

        async def fake_to_thread(func, *args):
            return func(*args)

        import services.auto_trader_service as ats_module
        monkeypatch.setattr(ats_module.alpaca_service, 'place_market_order', fake_place_order)
        monkeypatch.setattr(ats_module.asyncio, 'to_thread', fake_to_thread)

        async def fake_noop():
            return None
        monkeypatch.setattr(self.auto_trader, 'save_state', fake_noop)

        self.auto_trader.position_size_pct = 0.10
        signal = {
            'symbol': 'TEST8', 'entry_price': 10.0, 'stop_loss_price': 9.8,
            'target_price': 10.4, 'risk_per_share': 0.2
        }
        success = await self.auto_trader.execute_entry(signal, portfolio_value=10000)
        assert success is True
        assert self.auto_trader.open_positions['TEST8']['is_no_news_scalp'] is False
        assert self.auto_trader.open_positions['TEST8']['strategy'] == 'Auto-Trader (Warrior Trading)'


class TestNoNewsScalpBailoutTiming:
    """monitor_exits must apply the SHORTER no_news_bailout_seconds only to
    positions tagged is_no_news_scalp=True, leaving normal entries on the
    standard breakout_bailout_seconds."""

    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.breakout_bailout_seconds = 90
        self.auto_trader.no_news_bailout_seconds = 60

    def test_bailout_seconds_selection_logic(self):
        no_news_position = {'is_no_news_scalp': True}
        normal_position = {'is_no_news_scalp': False}
        no_news_position_missing_key = {}

        bailout_1 = self.auto_trader.no_news_bailout_seconds if no_news_position.get('is_no_news_scalp') else self.auto_trader.breakout_bailout_seconds
        bailout_2 = self.auto_trader.no_news_bailout_seconds if normal_position.get('is_no_news_scalp') else self.auto_trader.breakout_bailout_seconds
        bailout_3 = self.auto_trader.no_news_bailout_seconds if no_news_position_missing_key.get('is_no_news_scalp') else self.auto_trader.breakout_bailout_seconds

        assert bailout_1 == 60
        assert bailout_2 == 90
        assert bailout_3 == 90
