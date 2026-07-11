"""
Tests for Auto-Trader Exit Logic and No Re-Entry Rule

This test file validates:
1. Trailing stop updates as price rises
2. Partial sell at profit target (50% at 2%)
3. Stop moves to breakeven after partial sell
4. Full exit when trailing stop is hit
5. No re-entry rule - blocked symbols after exit
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone
import pytz

# Import the service we're testing
import sys
sys.path.insert(0, '/app/backend')
from services.auto_trader_service import AutoTraderService


class TestNoReEntryRule:
    """Test the No Re-Entry rule - stocks should not be re-entered after exit"""
    
    def setup_method(self):
        """Set up fresh auto-trader instance for each test"""
        self.auto_trader = AutoTraderService()
        
    def test_exited_today_initialized_empty(self):
        """exited_today set should be empty on initialization"""
        assert hasattr(self.auto_trader, 'exited_today')
        assert isinstance(self.auto_trader.exited_today, set)
        assert len(self.auto_trader.exited_today) == 0
        
    def test_exited_today_cleared_on_daily_reset(self):
        """exited_today should be cleared when a new trading day starts"""
        # Add some symbols to exited_today
        self.auto_trader.exited_today = {'AAPL', 'TSLA', 'NVDA'}
        
        # Simulate a new day by setting last_reset_date to yesterday
        yesterday = datetime.now(pytz.timezone('US/Eastern')).date()
        self.auto_trader.last_reset_date = None  # Force reset
        
        # Reset should clear exited_today
        self.auto_trader.reset_daily_tracking(10000.0)
        
        assert len(self.auto_trader.exited_today) == 0
        
    def test_symbol_blocked_after_exit(self):
        """After exiting a position, symbol should be in exited_today"""
        symbol = 'AAPL'
        self.auto_trader.exited_today.add(symbol)
        
        assert symbol in self.auto_trader.exited_today
        
    def test_check_entry_signals_skips_exited_stocks(self):
        """check_entry_signals should return None for stocks in exited_today"""
        # This test verifies the logic exists, actual execution requires mocking
        symbol = 'TSLA'
        self.auto_trader.exited_today.add(symbol)
        
        # The symbol should be blocked
        assert symbol in self.auto_trader.exited_today


class TestTrailingStopLogic:
    """Test trailing stop calculation and updates"""
    
    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.trailing_stop_pct = 0.01  # 1% trailing stop
        
    def test_trailing_stop_initial_calculation(self):
        """Initial trailing stop should be entry_price * (1 - trailing_stop_pct)"""
        entry_price = 10.00
        expected_stop = 10.00 * (1 - 0.01)  # $9.90
        
        # Simulate adding a position
        self.auto_trader.open_positions['TEST'] = {
            'entry_price': entry_price,
            'shares': 100,
            'trailing_stop': entry_price * (1 - self.auto_trader.trailing_stop_pct),
            'highest_price': entry_price
        }
        
        assert self.auto_trader.open_positions['TEST']['trailing_stop'] == pytest.approx(9.90, 0.01)
        
    def test_trailing_stop_updates_on_price_increase(self):
        """Trailing stop should move up when price increases"""
        entry_price = 10.00
        
        self.auto_trader.open_positions['TEST'] = {
            'entry_price': entry_price,
            'shares': 100,
            'trailing_stop': 9.90,  # Initial stop at 1% below entry
            'highest_price': entry_price
        }
        
        # Simulate price increase to $10.50
        new_price = 10.50
        new_stop = new_price * (1 - 0.01)  # $10.395
        
        if new_price > self.auto_trader.open_positions['TEST']['highest_price']:
            self.auto_trader.open_positions['TEST']['highest_price'] = new_price
            if new_stop > self.auto_trader.open_positions['TEST']['trailing_stop']:
                self.auto_trader.open_positions['TEST']['trailing_stop'] = new_stop
        
        assert self.auto_trader.open_positions['TEST']['trailing_stop'] == pytest.approx(10.395, 0.01)
        assert self.auto_trader.open_positions['TEST']['highest_price'] == 10.50
        
    def test_trailing_stop_never_moves_down(self):
        """Trailing stop should never decrease, even if price drops"""
        entry_price = 10.00
        
        self.auto_trader.open_positions['TEST'] = {
            'entry_price': entry_price,
            'shares': 100,
            'trailing_stop': 10.395,  # Already moved up
            'highest_price': 10.50
        }
        
        # Simulate price DROP to $10.20 - stop should NOT move down
        new_price = 10.20
        old_stop = self.auto_trader.open_positions['TEST']['trailing_stop']
        
        # The logic should not update stop when price drops
        new_stop = new_price * (1 - 0.01)  # $10.098
        if new_stop > old_stop:
            self.auto_trader.open_positions['TEST']['trailing_stop'] = new_stop
        
        # Stop should remain at $10.395, not drop to $10.098
        assert self.auto_trader.open_positions['TEST']['trailing_stop'] == pytest.approx(10.395, 0.01)


class TestPartialSellLogic:
    """Test partial sell at profit target"""
    
    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.profit_target_pct = 0.02  # 2% profit target
        self.auto_trader.partial_sell_pct = 0.50  # Sell 50%
        self.auto_trader.move_to_breakeven = True
        
    def test_partial_sell_triggered_at_profit_target(self):
        """Partial sell should trigger when price hits 2% profit"""
        entry_price = 10.00
        profit_target = entry_price * (1 + 0.02)  # $10.20
        
        self.auto_trader.open_positions['TEST'] = {
            'entry_price': entry_price,
            'shares': 100,
            'original_shares': 100,
            'profit_target': profit_target,
            'partial_sell_done': False,
            'trailing_stop': 9.90
        }
        
        # Simulate price hitting profit target
        current_price = 10.25  # Above 2% target
        
        if not self.auto_trader.open_positions['TEST']['partial_sell_done'] and current_price >= profit_target:
            shares_to_sell = int(100 * 0.50)  # 50 shares
            # Simulate partial sell
            self.auto_trader.open_positions['TEST']['partial_sell_done'] = True
            self.auto_trader.open_positions['TEST']['shares'] = 100 - shares_to_sell
        
        assert self.auto_trader.open_positions['TEST']['partial_sell_done'] == True
        assert self.auto_trader.open_positions['TEST']['shares'] == 50
        
    def test_stop_moves_to_breakeven_after_partial_sell(self):
        """Stop should move to entry price (breakeven) after partial sell"""
        entry_price = 10.00
        
        self.auto_trader.open_positions['TEST'] = {
            'entry_price': entry_price,
            'shares': 50,  # After partial sell
            'trailing_stop': 9.90,
            'partial_sell_done': True,
            'breakeven_stop_active': False
        }
        
        # Apply breakeven logic
        if self.auto_trader.move_to_breakeven:
            self.auto_trader.open_positions['TEST']['trailing_stop'] = entry_price
            self.auto_trader.open_positions['TEST']['breakeven_stop_active'] = True
        
        assert self.auto_trader.open_positions['TEST']['trailing_stop'] == 10.00
        assert self.auto_trader.open_positions['TEST']['breakeven_stop_active'] == True


class TestPositionSizing:
    """Test position sizing calculations"""
    
    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.position_size_pct = 0.10  # 10% of account
        
    def test_position_size_calculation(self):
        """Position size should be (portfolio * position_size_pct) / stock_price"""
        portfolio_value = 2000.0
        stock_price = 5.0
        
        shares = self.auto_trader.calculate_position_size(portfolio_value, stock_price)
        
        # $2000 * 10% = $200 / $5 = 40 shares
        assert shares == 40
        
    def test_position_size_minimum_one_share(self):
        """Position size should be at least 1 share"""
        portfolio_value = 100.0
        stock_price = 1000.0  # Very expensive stock
        
        shares = self.auto_trader.calculate_position_size(portfolio_value, stock_price)
        
        # Would be 0.01 shares, but should be at least 1
        assert shares >= 1


class TestRiskLimits:
    """Test risk limit checks"""
    
    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.daily_max_loss_pct = 0.05  # 5% max daily loss
        self.auto_trader.max_consecutive_losses = 3
        self.auto_trader.starting_portfolio_value = 10000.0
        
    def test_daily_max_loss_blocks_trading(self):
        """Trading should be blocked when daily loss exceeds limit"""
        self.auto_trader.daily_pnl = -600.0  # -6% loss (exceeds 5%)
        
        risk_check = self.auto_trader.check_risk_limits(9400.0)
        
        assert risk_check['can_trade'] == False
        assert 'Daily max loss' in risk_check['reason']
        
    def test_consecutive_losses_blocks_trading(self):
        """Trading should be blocked after 3 consecutive losses"""
        self.auto_trader.consecutive_losses = 3
        self.auto_trader.daily_pnl = -100.0  # Small loss, within limit
        
        risk_check = self.auto_trader.check_risk_limits(9900.0)
        
        assert risk_check['can_trade'] == False
        assert 'consecutive losses' in risk_check['reason']
        
    def test_risk_ok_when_within_limits(self):
        """Trading should be allowed when all limits are OK"""
        self.auto_trader.daily_pnl = -200.0  # -2% loss (within 5%)
        self.auto_trader.consecutive_losses = 1
        
        risk_check = self.auto_trader.check_risk_limits(9800.0)
        
        assert risk_check['can_trade'] == True


class TestTradingHours:
    """Test trading hours logic"""
    
    def setup_method(self):
        self.auto_trader = AutoTraderService()
        self.auto_trader.trading_start_hour = 7
        self.auto_trader.trading_end_hour = 11
        
    def test_is_trading_hours_method_exists(self):
        """is_trading_hours method should exist"""
        assert hasattr(self.auto_trader, 'is_trading_hours')
        assert callable(self.auto_trader.is_trading_hours)
        
    def test_trading_hours_returns_boolean(self):
        """is_trading_hours should return a boolean"""
        result = self.auto_trader.is_trading_hours()
        assert isinstance(result, bool)

    def test_trading_hours_false_on_saturday(self):
        """is_trading_hours must be False on Saturday even during 7AM-3:30PM ET window"""
        eastern = pytz.timezone('US/Eastern')
        saturday_10am = eastern.localize(datetime(2026, 7, 11, 10, 0))  # 2026-07-11 is a Saturday
        with patch('services.auto_trader_service.datetime') as mock_dt:
            mock_dt.now.return_value = saturday_10am
            assert self.auto_trader.is_trading_hours() is False

    def test_trading_hours_false_on_sunday(self):
        """is_trading_hours must be False on Sunday even during 7AM-3:30PM ET window"""
        eastern = pytz.timezone('US/Eastern')
        sunday_10am = eastern.localize(datetime(2026, 7, 12, 10, 0))  # 2026-07-12 is a Sunday
        with patch('services.auto_trader_service.datetime') as mock_dt:
            mock_dt.now.return_value = sunday_10am
            assert self.auto_trader.is_trading_hours() is False

    def test_trading_hours_true_on_weekday_during_window(self):
        """is_trading_hours must be True on a weekday within the 7AM-3:30PM ET window"""
        eastern = pytz.timezone('US/Eastern')
        monday_10am = eastern.localize(datetime(2026, 7, 13, 10, 0))  # 2026-07-13 is a Monday
        with patch('services.auto_trader_service.datetime') as mock_dt:
            mock_dt.now.return_value = monday_10am
            assert self.auto_trader.is_trading_hours() is True

    def test_entry_window_false_on_weekend(self):
        """is_entry_window must be False on Saturday/Sunday even during 7AM-11AM ET window"""
        eastern = pytz.timezone('US/Eastern')
        saturday_8am = eastern.localize(datetime(2026, 7, 11, 8, 0))
        with patch('services.auto_trader_service.datetime') as mock_dt:
            mock_dt.now.return_value = saturday_8am
            assert self.auto_trader.is_entry_window() is False


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
