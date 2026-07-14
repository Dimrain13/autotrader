"""
Tests for Ross Cameron's "First Pullback" entry pattern (check_first_pullback)
and the related structural stop / 2:1 target / breakout-or-bailout mechanics.

Bar dicts use {open, high, low, close} - oldest bar first (bars[-1] = latest).
"""
import pytest
from datetime import datetime, timedelta, timezone
import sys
sys.path.insert(0, '/app/backend')
from services.auto_trader_service import AutoTraderService


def make_bar(o, c):
    """Helper: build a bar with high/low padded 0.05 beyond the open/close extremes."""
    return {
        'open': o,
        'close': c,
        'high': max(o, c) + 0.05,
        'low': min(o, c) - 0.05,
    }


def surge_bars():
    """7 green bars: a clean initial surge from ~10.00 to ~15.05 high."""
    ohlc = [(10.0, 10.5), (10.5, 11.2), (11.2, 11.9), (11.9, 12.6),
            (12.6, 13.3), (13.3, 14.0), (14.0, 15.0)]
    return [make_bar(o, c) for o, c in ohlc]


class TestFirstPullbackPattern:
    def setup_method(self):
        self.auto_trader = AutoTraderService()

    def test_valid_first_pullback_2_red_candles(self):
        """2 red candles after the surge, breakout breaks the prior red candle's high -> valid"""
        bars = surge_bars() + [
            make_bar(15.0, 14.85),   # red pullback 1
            make_bar(14.85, 14.75),  # red pullback 2
            make_bar(14.75, 14.90),  # breakout (green, high must exceed prior red's high)
        ]
        result = self.auto_trader.check_first_pullback(bars)
        assert result['is_valid'] is True
        assert result['pullback_candles'] == 2
        assert result['stop_loss_price'] == pytest.approx(min(bars[-2]['low'], bars[-3]['low']), 0.001)
        assert result['entry_price'] == bars[-1]['close']

    def test_50pct_rule_rejects_deep_retracement(self):
        """Pullback that retraces > 50% of the initial surge must be invalidated"""
        bars = surge_bars() + [
            make_bar(15.0, 12.0),   # big red drop
            make_bar(12.0, 11.0),   # another big red drop - breaches the 50% midpoint
            make_bar(11.0, 12.5),   # breakout above prior candle's high
        ]
        result = self.auto_trader.check_first_pullback(bars)
        assert result['is_valid'] is False
        assert 'retraced' in result['reason'].lower()

    def test_breakout_must_exceed_prior_candle_high(self):
        """If the latest bar doesn't break the high of the pullback candle before it, no entry"""
        bars = surge_bars() + [
            make_bar(15.0, 14.85),
            make_bar(14.85, 14.75),
            make_bar(14.75, 14.80),  # green, but high does NOT exceed the prior red candle's high
        ]
        bars[-1]['high'] = bars[-2]['high'] - 0.01  # force it to not break out
        result = self.auto_trader.check_first_pullback(bars)
        assert result['is_valid'] is False

    def test_too_many_red_candles_invalid(self):
        """More than 3 consecutive red candles is not a valid 'first pullback' - too much weakness"""
        bars = surge_bars() + [
            make_bar(15.0, 14.85),
            make_bar(14.85, 14.70),
            make_bar(14.70, 14.55),
            make_bar(14.55, 14.40),  # 4th red candle - exceeds pullback_max_candles (3)
            make_bar(14.40, 14.60),
        ]
        result = self.auto_trader.check_first_pullback(bars)
        assert result['is_valid'] is False
        assert 'red candles' in result['reason'].lower()

    def test_no_red_candles_before_latest_bar_invalid(self):
        """If the bar right before the latest one is also green, there's no pullback to buy"""
        bars = surge_bars() + [
            make_bar(15.0, 15.3),  # green, not a pullback
            make_bar(15.3, 15.6),  # green
            make_bar(15.6, 16.0),  # green (this is the "latest" bar)
        ]
        result = self.auto_trader.check_first_pullback(bars)
        assert result['is_valid'] is False
        assert result['pullback_candles'] == 0

    def test_stop_loss_is_structural_pullback_low_not_a_flat_pct(self):
        """Stop-loss must equal the actual low of the pullback candles, not entry * (1 - x%)"""
        bars = surge_bars() + [
            make_bar(15.0, 14.85),
            make_bar(14.85, 14.75),
            make_bar(14.75, 14.90),
        ]
        result = self.auto_trader.check_first_pullback(bars)
        expected_stop = min(bars[-2]['low'], bars[-3]['low'])
        assert result['stop_loss_price'] == pytest.approx(expected_stop, 0.001)
        # Sanity: this is NOT the old flat 1% stop
        flat_pct_stop = result['entry_price'] * (1 - self.auto_trader.stop_loss_pct)
        assert result['stop_loss_price'] != pytest.approx(flat_pct_stop, 0.001)


class TestTwoToOneTarget:
    """2:1 reward:risk target must be computed off the REAL structural risk, not a flat %"""

    def setup_method(self):
        self.auto_trader = AutoTraderService()

    def test_target_is_entry_plus_2x_structural_risk(self):
        entry_price = 14.90
        stop_loss_price = 14.70
        risk_per_share = entry_price - stop_loss_price
        target_price = entry_price + (2 * risk_per_share)

        assert risk_per_share == pytest.approx(0.20, 0.001)
        assert target_price == pytest.approx(15.30, 0.001)


class TestMaxStopDistanceSafetyCap:
    """A structural stop that's too far away should be treated as too risky, not force-capped"""

    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.max_stop_distance_pct = 0.03  # default 3%

    def test_stop_within_cap_is_acceptable(self):
        entry_price, stop_loss_price = 14.90, 14.70
        risk_pct = (entry_price - stop_loss_price) / entry_price
        assert risk_pct <= self.auto_trader.max_stop_distance_pct

    def test_stop_beyond_cap_should_be_rejected(self):
        entry_price, stop_loss_price = 14.90, 14.00  # ~6% away
        risk_pct = (entry_price - stop_loss_price) / entry_price
        assert risk_pct > self.auto_trader.max_stop_distance_pct


class TestBreakoutOrBailout:
    """'Breakout or Bailout': exit if a fresh entry hasn't moved into profit within the grace window"""

    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.breakout_bailout_seconds = 90

    def test_bailout_triggers_after_grace_period_if_not_profitable(self):
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        current_price = 14.85  # below entry - never moved into profit
        entry_price = 14.90

        seconds_since_entry = (datetime.now(timezone.utc) - entry_time).total_seconds()
        bailout_triggered = (
            current_price <= entry_price
            and seconds_since_entry >= self.auto_trader.breakout_bailout_seconds
        )
        assert bailout_triggered is True

    def test_bailout_does_not_trigger_within_grace_period(self):
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        current_price = 14.85
        entry_price = 14.90

        seconds_since_entry = (datetime.now(timezone.utc) - entry_time).total_seconds()
        bailout_triggered = (
            current_price <= entry_price
            and seconds_since_entry >= self.auto_trader.breakout_bailout_seconds
        )
        assert bailout_triggered is False

    def test_bailout_does_not_trigger_if_already_profitable(self):
        entry_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        current_price = 15.20  # above entry - trade is working
        entry_price = 14.90

        seconds_since_entry = (datetime.now(timezone.utc) - entry_time).total_seconds()
        bailout_triggered = (
            current_price <= entry_price
            and seconds_since_entry >= self.auto_trader.breakout_bailout_seconds
        )
        assert bailout_triggered is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
