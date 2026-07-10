from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone
import pandas as pd

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="MomentumX Trading Platform")
api_router = APIRouter(prefix="/api")

# Import services
from services.alpaca_service import alpaca_service
from services.scanner_service import scanner_service
from services.auto_trader_service import auto_trader
from services.position_monitor_service import position_monitor
from services.eod_closer_service import eod_closer
from services.trade_history_service import trade_history
from services.missed_opportunities_service import missed_opportunities
import asyncio

class TradeOrder(BaseModel):
    symbol: str
    qty: float
    side: str = "buy"
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    entry_price: Optional[float] = None
    stop_type: Optional[str] = "fixed"  # 'fixed' or 'trailing'
    trailing_stop_pct: Optional[float] = 5.0
    partial_sell_pct: Optional[float] = 50.0
    partial_sell_trigger_pct: Optional[float] = 10.0
    move_to_breakeven: Optional[bool] = True

class ScanCriteria(BaseModel):
    min_price: float = 2.0
    max_price: float = 20.0
    min_change: float = 10.0
    min_volume_ratio: float = 5.0
    max_float: int = 20_000_000

class Settings(BaseModel):
    api_key: str
    secret_key: str
    base_url: str = "https://paper-api.alpaca.markets"
    day_trading_mode: bool = False
    sma_short: int = 20
    sma_long: int = 50

def is_market_open() -> bool:
    """Check if US market is currently open (extended hours for paper trading)
    
    Alpaca Paper Trading supports extended hours:
    - Pre-market: 4:00 AM - 9:30 AM ET
    - Regular: 9:30 AM - 4:00 PM ET  
    - After-hours: 4:00 PM - 8:00 PM ET
    """
    from datetime import datetime
    import pytz
    
    et = pytz.timezone('America/New_York')
    now_et = datetime.now(et)
    
    # Check if weekday
    if now_et.weekday() >= 5:  # Saturday or Sunday
        return False
    
    # Extended trading hours: 4:00 AM - 8:00 PM ET (Alpaca Paper Trading)
    hour = now_et.hour
    
    if hour < 4:  # Before 4:00 AM
        return False
    if hour >= 20:  # After 8:00 PM
        return False
    
    return True

def get_market_session() -> str:
    """Get current market session type"""
    from datetime import datetime
    import pytz
    
    et = pytz.timezone('America/New_York')
    now_et = datetime.now(et)
    hour = now_et.hour
    minute = now_et.minute
    
    if now_et.weekday() >= 5:
        return "closed"
    
    if hour < 4 or hour >= 20:
        return "closed"
    elif hour < 9 or (hour == 9 and minute < 30):
        return "pre-market"
    elif hour < 16:
        return "regular"
    else:
        return "after-hours"

@api_router.get("/")
async def root():
    return {"message": "MomentumX Trading API", "version": "1.0.0"}

@api_router.get("/market/status")
async def get_market_status():
    """Get current market status"""
    from datetime import datetime
    import pytz
    
    et = pytz.timezone('America/New_York')
    now_et = datetime.now(et)
    is_open = is_market_open()
    session = get_market_session()
    
    return {
        "is_open": is_open,
        "session": session,
        "current_time_et": now_et.strftime('%I:%M %p %Z'),
        "day_of_week": now_et.strftime('%A'),
        "extended_hours": "4:00 AM - 8:00 PM ET (Paper Trading)",
        "regular_hours": "9:30 AM - 4:00 PM ET",
        "pre_market": "4:00 AM - 9:30 AM ET",
        "after_hours": "4:00 PM - 8:00 PM ET"
    }

@api_router.get("/account")
async def get_account():
    try:
        account = alpaca_service.get_account()
        
        # Check if day trading mode is enabled
        day_trading_mode = os.getenv('DAY_TRADING_MODE', 'false').lower() == 'true'
        
        if day_trading_mode and not account.get('pattern_day_trader'):
            # Simulate 4x day trading buying power
            portfolio_value = account.get('portfolio_value', 0)
            account['buying_power'] = portfolio_value * 4
            account['day_trading_buying_power'] = portfolio_value * 4
            account['pattern_day_trader'] = True
            account['simulated_pdt'] = True
        
        return account
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/positions")
async def get_positions():
    try:
        positions = alpaca_service.get_positions()
        return positions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/positions/monitored")
async def get_monitored_positions():
    """Get all positions being monitored for trailing stops"""
    try:
        return {
            "active": position_monitor.active,
            "monitored_count": len(position_monitor.monitored_positions),
            "positions": position_monitor.monitored_positions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/positions/sync-monitoring")
async def sync_position_monitoring(config: dict = None):
    """
    Sync all existing Alpaca positions to position monitor with trailing stops.
    This ensures ALL positions (including manual ones) are monitored.
    
    config: {
        'stop_loss_pct': float (default 1.0),
        'trailing_stop_pct': float (default 1.0),
        'take_profit_pct': float (default 2.0),
        'partial_sell_pct': float (default 50.0),
        'partial_sell_trigger_pct': float (default 2.0),
        'move_to_breakeven': bool (default True),
        'stop_type': 'trailing' or 'fixed' (default 'trailing')
    }
    """
    try:
        # Default config
        default_config = {
            'stop_loss_pct': 1.0,
            'trailing_stop_pct': 1.0,
            'take_profit_pct': 2.0,
            'partial_sell_pct': 50.0,
            'partial_sell_trigger_pct': 2.0,
            'move_to_breakeven': True,
            'stop_type': 'trailing'
        }
        
        if config:
            default_config.update(config)
        
        # Get all positions from Alpaca
        positions = alpaca_service.get_positions()
        
        synced = []
        already_monitored = []
        
        for pos in positions:
            symbol = pos['symbol']
            qty = pos['qty']
            
            # Skip short positions
            if qty <= 0:
                continue
            
            # Check if already monitored
            if symbol in position_monitor.monitored_positions:
                already_monitored.append(symbol)
                continue
            
            # Add to monitor
            position_monitor.add_position(symbol, {
                'entry_price': pos['avg_entry_price'],
                'shares': int(qty),
                'stop_type': default_config['stop_type'],
                'stop_loss_pct': default_config['stop_loss_pct'],
                'trailing_stop_pct': default_config['trailing_stop_pct'],
                'take_profit_pct': default_config['take_profit_pct'],
                'partial_sell_pct': default_config['partial_sell_pct'],
                'partial_sell_trigger_pct': default_config['partial_sell_trigger_pct'],
                'move_to_breakeven': default_config['move_to_breakeven']
            })
            synced.append(symbol)
            logger.info(f"📊 Synced {symbol} to position monitor: entry=${pos['avg_entry_price']:.2f}, {int(qty)} shares")
        
        return {
            "success": True,
            "synced": synced,
            "already_monitored": already_monitored,
            "total_monitored": len(position_monitor.monitored_positions),
            "config_used": default_config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/orders")
async def get_orders(status: str = "all", limit: int = 50):
    try:
        orders = alpaca_service.get_orders(status, limit)
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/orders")
async def place_order(order: TradeOrder):
    try:
        # Check if market is open for buy orders (extended hours: 4 AM - 8 PM ET)
        if order.side.lower() == "buy" and not is_market_open():
            session = get_market_session()
            raise HTTPException(
                status_code=400, 
                detail=f"Market is {session}. Extended trading hours: 4:00 AM - 8:00 PM ET (Monday-Friday)"
            )
        
        from services.position_monitor_service import position_monitor
        
        # For SELL orders, capture position data before selling to log to trade history
        position_data = None
        if order.side.lower() == "sell":
            try:
                positions = alpaca_service.get_positions()
                position_data = next((p for p in positions if p['symbol'] == order.symbol), None)
            except:
                pass
        
        # Check if this is a buy order with stop loss/take profit
        if order.side.lower() == "buy" and order.stop_loss_pct and order.take_profit_pct:
            
            # ALWAYS get fresh quote for accurate entry price AND spread check
            spread_warning = None
            bid_price = 0
            ask_price = 0
            spread_pct = 0
            
            try:
                quote = alpaca_service.get_latest_quote(order.symbol)
                current_price = quote.get('ask_price') or quote.get('bid_price') or order.entry_price or 10.0
                spread_pct = quote.get('spread_pct', 0)
                bid_price = quote.get('bid_price', 0)
                ask_price = quote.get('ask_price', 0)
                
                logger.info(f"📊 {order.symbol}: Bid ${bid_price:.2f} | Ask ${ask_price:.2f} | Spread {spread_pct:.1f}%")
                
                # SPREAD WARNING - Warn if spread > 3% but still allow the trade
                if spread_pct > 3.0:
                    spread_warning = f"⚠️ Wide spread alert! {order.symbol} has {spread_pct:.1f}% spread (Bid: ${bid_price:.2f}, Ask: ${ask_price:.2f}). Stop loss will be calculated from BID price."
                    logger.warning(spread_warning)
                    
            except Exception as quote_err:
                logger.warning(f"Could not get quote for {order.symbol}: {quote_err}")
                current_price = order.entry_price or 10.0
                spread_pct = 0
                bid_price = current_price  # Fallback
            
            # For TRAILING stops, use position monitor (software-based)
            if order.stop_type == "trailing":
                # Place simple market order first
                result = alpaca_service.place_market_order(order.symbol, order.qty, "buy")
                
                # Use current market price for position monitoring (not stale frontend price)
                entry_price = current_price
                
                # CRITICAL: Calculate stop loss from BID price, not entry price
                # This prevents instant stop loss triggers due to bid-ask spread
                stop_reference_price = bid_price if bid_price > 0 else entry_price
                
                # Add to position monitor for trailing stop management
                position_monitor.add_position(order.symbol, {
                    'entry_price': entry_price,
                    'stop_reference_price': stop_reference_price,  # Use BID for stop calculation
                    'bid_at_entry': bid_price,
                    'ask_at_entry': ask_price,
                    'spread_at_entry': spread_pct,
                    'shares': order.qty,
                    'stop_type': 'trailing',
                    'stop_loss_pct': order.stop_loss_pct,
                    'trailing_stop_pct': order.trailing_stop_pct,
                    'take_profit_pct': order.take_profit_pct,
                    'partial_sell_pct': order.partial_sell_pct,
                    'partial_sell_trigger_pct': order.partial_sell_trigger_pct,
                    'move_to_breakeven': order.move_to_breakeven
                })
                
                result['stop_type'] = 'trailing'
                result['monitored'] = True
                result['actual_price'] = entry_price
                result['stop_reference_price'] = stop_reference_price
                result['spread_pct'] = spread_pct
                if spread_warning:
                    result['spread_warning'] = spread_warning
            else:
                # For FIXED stops, try Alpaca bracket orders first, fall back to trailing if fails
                # CRITICAL: Calculate stop loss from BID price to prevent instant triggers
                stop_reference_price = bid_price if bid_price > 0 else current_price
                
                # Round to 2 decimal places to avoid sub-penny pricing errors
                stop_loss_price = round(stop_reference_price * (1 - order.stop_loss_pct / 100), 2)
                take_profit_price = round(current_price * (1 + order.take_profit_pct / 100), 2)
                
                # Alpaca requires minimum $0.01 difference from base price
                if stop_reference_price - stop_loss_price < 0.01:
                    stop_loss_price = round(stop_reference_price - 0.01, 2)
                if take_profit_price - current_price < 0.01:
                    take_profit_price = round(current_price + 0.01, 2)
                
                logger.info(f"📊 {order.symbol}: Trying bracket order - Stop ${stop_loss_price:.2f} (from BID ${stop_reference_price:.2f}), Target ${take_profit_price:.2f}")
                
                try:
                    result = alpaca_service.place_bracket_order(
                        symbol=order.symbol,
                        qty=order.qty,
                        stop_loss_price=stop_loss_price,
                        take_profit_price=take_profit_price
                    )
                    result['actual_price'] = current_price
                    result['stop_reference_price'] = stop_reference_price
                    result['spread_pct'] = spread_pct
                    if spread_warning:
                        result['spread_warning'] = spread_warning
                except Exception as bracket_err:
                    # Bracket order failed - fall back to market order with trailing stop
                    error_msg = str(bracket_err)
                    logger.warning(f"⚠️ {order.symbol}: Bracket order failed, using market order with trailing stop - {error_msg}")
                    
                    # Place simple market order instead
                    result = alpaca_service.place_market_order(order.symbol, order.qty, "buy")
                    result['warning'] = f"Bracket order failed, using trailing stop instead"
                    result['price_changed'] = True
                    result['actual_price'] = current_price
                    result['stop_type'] = 'trailing'
                    result['stop_reference_price'] = stop_reference_price
                    result['spread_pct'] = spread_pct
                    if spread_warning:
                        result['spread_warning'] = spread_warning
                    
                    # Add to position monitor with trailing stop - use BID for stop calculation
                    position_monitor.add_position(order.symbol, {
                        'entry_price': current_price,
                        'stop_reference_price': stop_reference_price,
                        'bid_at_entry': bid_price,
                        'ask_at_entry': ask_price,
                        'spread_at_entry': spread_pct,
                        'shares': order.qty,
                        'stop_type': 'trailing',
                        'stop_loss_pct': order.stop_loss_pct,
                        'trailing_stop_pct': order.trailing_stop_pct or order.stop_loss_pct,
                        'take_profit_pct': order.take_profit_pct,
                        'partial_sell_pct': order.partial_sell_pct,
                        'partial_sell_trigger_pct': order.partial_sell_trigger_pct,
                        'move_to_breakeven': order.move_to_breakeven
                    })
                    result['monitored'] = True
                
                # Still add to monitor for partial sell feature (if bracket succeeded)
                if 'monitored' not in result and order.partial_sell_pct > 0:
                    position_monitor.add_position(order.symbol, {
                        'entry_price': current_price,
                        'stop_reference_price': stop_reference_price,
                        'bid_at_entry': bid_price,
                        'ask_at_entry': ask_price,
                        'spread_at_entry': spread_pct,
                        'shares': order.qty,
                        'stop_type': 'fixed',
                        'stop_loss_pct': order.stop_loss_pct,
                        'trailing_stop_pct': 0,
                        'take_profit_pct': order.take_profit_pct,
                        'partial_sell_pct': order.partial_sell_pct,
                        'partial_sell_trigger_pct': order.partial_sell_trigger_pct,
                        'move_to_breakeven': order.move_to_breakeven
                    })
        else:
            # Place simple market order (for sells or buys without stop/profit)
            result = alpaca_service.place_market_order(order.symbol, order.qty, order.side)
            
            # IMPORTANT: For ALL buy orders, add to position monitor with default settings
            # This ensures stop-loss and take-profit are always active
            if order.side.lower() == "buy":
                try:
                    # Wait briefly for order to fill
                    import asyncio
                    await asyncio.sleep(2)
                    
                    # Get the order status to find the actual fill price
                    try:
                        order_status = alpaca_service.get_order(result.get('order_id'))
                        if order_status and order_status.get('filled_avg_price'):
                            entry_price = float(order_status['filled_avg_price'])
                            logger.info(f"📊 {order.symbol}: Got fill price from order: ${entry_price:.2f}")
                        else:
                            entry_price = None
                    except Exception as order_err:
                        logger.warning(f"📊 {order.symbol}: Could not get order status: {order_err}")
                        entry_price = None
                    
                    # Fallback: Use current quote (mid-price) - this is what we'll trade at
                    if not entry_price:
                        quote = alpaca_service.get_latest_quote(order.symbol)
                        bid = quote.get('bid_price', 0)
                        ask = quote.get('ask_price', 0)
                        # Use mid-price or available price
                        if bid > 0 and ask > 0:
                            entry_price = (bid + ask) / 2
                        else:
                            entry_price = ask or bid or 0
                        logger.info(f"📊 {order.symbol}: Using quote mid-price ${entry_price:.2f}")
                    
                    if entry_price and entry_price > 0:
                        # Use provided settings or defaults
                        config = {
                            'entry_price': float(entry_price),
                            'shares': float(order.qty),
                            'stop_type': order.stop_type or 'trailing',
                            'stop_loss_pct': order.stop_loss_pct or 1.0,
                            'trailing_stop_pct': order.trailing_stop_pct or 1.0,
                            'take_profit_pct': order.take_profit_pct or 2.0,
                            'partial_sell_pct': order.partial_sell_pct if order.partial_sell_pct is not None else 50.0,
                            'partial_sell_trigger_pct': order.partial_sell_trigger_pct if order.partial_sell_trigger_pct is not None else 2.0,
                            'move_to_breakeven': order.move_to_breakeven if order.move_to_breakeven is not None else True
                        }
                        position_monitor.add_position(order.symbol, config)
                        result['monitored'] = True
                        result['stop_type'] = config['stop_type']
                        logger.info(f"📊 Auto-added {order.symbol} to position monitor: entry=${entry_price:.2f}, {order.qty} shares")
                except Exception as monitor_error:
                    logger.error(f"Failed to add {order.symbol} to position monitor: {monitor_error}")
        
        # Log trade to history when selling
        if order.side.lower() == "sell" and position_data:
            try:
                entry_price = position_data['avg_entry_price']
                exit_price = position_data['current_price']  # Use current price as exit estimate
                shares = float(order.qty)
                pnl = (exit_price - entry_price) * shares
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                
                # Get actual entry time from order history
                entry_time = alpaca_service.get_position_entry_time(order.symbol)
                if not entry_time:
                    entry_time = datetime.now(timezone.utc).isoformat()
                
                trade_history.log_trade({
                    'symbol': order.symbol,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'shares': shares,
                    'entry_time': entry_time,
                    'exit_time': datetime.now(timezone.utc).isoformat(),
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'exit_reason': 'Manual sell',
                    'strategy': 'Manual'
                })
                logger.info(f"📊 Trade logged: {order.symbol} | P&L: ${pnl:.2f} ({pnl_pct:.2f}%)")
                
                # Add to exited_today set for No Re-Entry rule
                auto_trader.exited_today.add(order.symbol)
                logger.info(f"🚫 No Re-Entry: {order.symbol} blocked for rest of day")
            except Exception as e:
                logger.error(f"Failed to log trade history: {str(e)}")
        
        # Store in MongoDB
        order_doc = {
            "order_id": result['order_id'],
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "status": result['status'],
            "stop_loss_pct": order.stop_loss_pct,
            "take_profit_pct": order.take_profit_pct,
            "entry_price": order.entry_price,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.orders.insert_one(order_doc)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.delete("/orders")
async def cancel_all_orders():
    """Cancel all open orders"""
    try:
        # Get all orders from Alpaca (filter for open statuses)
        orders = alpaca_service.get_orders(status="all", limit=50)
        open_statuses = ['new', 'pending_new', 'accepted', 'partially_filled']
        cancelled_count = 0
        
        for order in orders:
            if order['status'] in open_statuses:
                try:
                    alpaca_service.cancel_order(order['order_id'])
                    cancelled_count += 1
                except Exception as e:
                    logger.error(f"Failed to cancel order {order['order_id']}: {str(e)}")
        
        return {
            "message": f"Cancelled {cancelled_count} order(s)",
            "cancelled_count": cancelled_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.delete("/orders/{order_id}")
async def cancel_order(order_id: str):
    """Cancel a specific order"""
    try:
        alpaca_service.cancel_order(order_id)
        return {"message": f"Order {order_id} cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/scanner/scan")
async def scan_stocks(criteria: ScanCriteria, use_demo: bool = False):
    try:
        # Use demo scanner for simulation/testing
        if use_demo:
            from services.demo_scanner_service import demo_scanner
            results = await asyncio.to_thread(demo_scanner.scan_stocks, criteria.model_dump())
        else:
            # Use scan_market which has aggressive caching for instant results
            # Run in thread pool to avoid blocking the event loop
            results = await asyncio.to_thread(scanner_service.scan_market, criteria.model_dump())
        
        # Return results immediately - do storage/logging in background
        # This ensures the API responds quickly even if DB is slow
        
        async def background_tasks():
            try:
                # Store scan results
                scan_doc = {
                    "scan_id": str(uuid.uuid4()),
                    "criteria": criteria.model_dump(),
                    "results": results,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "demo_mode": use_demo
                }
                await db.scans.insert_one(scan_doc)
                
                # Auto-log scanner results as potential missed opportunities
                positions = await asyncio.to_thread(alpaca_service.get_positions)
                traded_symbols = [p['symbol'] for p in positions]
                if results and len(results) > 0:
                    await asyncio.to_thread(missed_opportunities.log_scanner_results, results, traded_symbols)
            except Exception as bg_err:
                logger.warning(f"Background scanner tasks failed: {bg_err}")
        
        # Fire and forget - don't wait for background tasks
        asyncio.create_task(background_tasks())
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scanner/momentum")
async def get_momentum_stocks():
    """
    Get stocks building momentum (higher highs) with 3/5 criteria
    These are potential pullback candidates - watch for entry opportunities
    """
    try:
        # First check if we have cached momentum data
        if hasattr(scanner_service, 'momentum_cache') and scanner_service.momentum_cache:
            cache_age = (datetime.now() - scanner_service.momentum_cache_time).seconds if hasattr(scanner_service, 'momentum_cache_time') else 999
            logger.info(f"⚡ Returning cached momentum: {len(scanner_service.momentum_cache)} stocks (age: {cache_age}s)")
            return {
                "stocks": scanner_service.momentum_cache,
                "count": len(scanner_service.momentum_cache),
                "description": "Stocks making higher highs with 3/5 criteria - watch for pullback entries",
                "cached": True,
                "cache_age": cache_age
            }
        
        # No cache - run with timeout
        try:
            momentum_stocks = await asyncio.wait_for(
                asyncio.to_thread(scanner_service.get_momentum_stocks),
                timeout=15.0  # 15 second timeout
            )
            return {
                "stocks": momentum_stocks,
                "count": len(momentum_stocks),
                "description": "Stocks making higher highs with 3/5 criteria - watch for pullback entries"
            }
        except asyncio.TimeoutError:
            logger.warning("Momentum scan timed out, returning empty result")
            return {
                "stocks": [],
                "count": 0,
                "description": "Momentum scan in progress - try again shortly",
                "timeout": True
            }
    except Exception as e:
        logger.error(f"Momentum scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/auto-trader/toggle")
async def toggle_auto_trader(enabled: bool):
    """Enable or disable auto-trading"""
    try:
        auto_trader.active = enabled
        status = "enabled" if enabled else "disabled"
        return {
            "status": status,
            "message": f"Auto-trading {status}",
            "active": auto_trader.active
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/auto-trader/status")
async def get_auto_trader_status():
    """Get current auto-trader status with Warrior Trading strategy metrics"""
    # Get account info for portfolio value
    try:
        account = alpaca_service.get_account()
        portfolio_value = float(account.get('portfolio_value', 0))
    except:
        portfolio_value = 0
    
    return {
        "active": auto_trader.active,
        "open_positions": len(auto_trader.open_positions),
        "max_positions": auto_trader.max_positions,
        "positions": list(auto_trader.open_positions.values()),
        "strategy": {
            "name": "Warrior Trading - Quick Scalp",
            "position_size_pct": auto_trader.position_size_pct * 100,  # 10%
            "profit_target_pct": auto_trader.profit_target_pct * 100,  # 2%
            "stop_loss_pct": auto_trader.stop_loss_pct * 100,  # 1%
            "daily_max_loss_pct": auto_trader.daily_max_loss_pct * 100,  # 5%
            "max_consecutive_losses": auto_trader.max_consecutive_losses,  # 3
            "trading_hours": f"{auto_trader.trading_start_hour}:00 AM - {auto_trader.trading_end_hour}:{auto_trader.trading_end_minute:02d} PM EST",
            "partial_sell_pct": auto_trader.partial_sell_pct * 100,  # 50%
            "partial_sell_trigger_pct": auto_trader.profit_target_pct * 100,  # 2%
            "move_to_breakeven": auto_trader.move_to_breakeven,  # True
            "eod_close_time": "3:30 PM EST"
        },
        "entry_conditions": {
            "pullback_min_candles": auto_trader.pullback_min_candles,
            "pullback_max_candles": auto_trader.pullback_max_candles,
            "pullback_lookback_bars": auto_trader.pullback_lookback_bars,
            "require_macd_crossover": auto_trader.require_macd_crossover,
            "require_sma_crossover": auto_trader.require_sma_crossover,
            "require_bull_flag": auto_trader.require_bull_flag,
            "sma_period": auto_trader.sma_period,
            "trading_start_hour": auto_trader.trading_start_hour,
            "trading_end_hour": auto_trader.trading_end_hour,
            "trading_end_minute": auto_trader.trading_end_minute
        },
        "daily_tracking": {
            "daily_pnl": round(auto_trader.daily_pnl, 2),
            "daily_pnl_pct": round((auto_trader.daily_pnl / auto_trader.starting_portfolio_value * 100) if auto_trader.starting_portfolio_value > 0 else 0, 2),
            "consecutive_losses": auto_trader.consecutive_losses,
            "starting_portfolio_value": round(auto_trader.starting_portfolio_value, 2),
            "current_portfolio_value": round(portfolio_value, 2),
            "exited_today": list(auto_trader.exited_today),
            "exited_today_count": len(auto_trader.exited_today)
        },
        "risk_status": auto_trader.check_risk_limits(portfolio_value)
    }

@api_router.post("/auto-trader/settings")
async def update_auto_trader_settings(settings: dict):
    """Update auto-trader entry condition settings"""
    try:
        auto_trader.update_settings(settings)
        return {
            "success": True,
            "message": "Settings updated successfully",
            "current_settings": {
                # Entry conditions
                "pullback_min_pct": auto_trader.pullback_min_pct,
                "pullback_max_pct": auto_trader.pullback_max_pct,
                "pullback_lookback_bars": auto_trader.pullback_lookback_bars,
                "require_macd_crossover": auto_trader.require_macd_crossover,
                "require_sma_crossover": auto_trader.require_sma_crossover,
                "require_bull_flag": auto_trader.require_bull_flag,
                "sma_period": auto_trader.sma_period,
                "trading_start_hour": auto_trader.trading_start_hour,
                "trading_end_hour": auto_trader.trading_end_hour,
                # Trade management
                "profit_target_pct": auto_trader.profit_target_pct * 100,
                "stop_loss_pct": auto_trader.stop_loss_pct * 100,
                "max_positions": auto_trader.max_positions,
                "position_size_pct": auto_trader.position_size_pct * 100,
                "daily_max_loss_pct": auto_trader.daily_max_loss_pct * 100
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@api_router.get("/auto-trader/history")
async def get_auto_trader_history():
    """Get today's trade history"""
    winners = [t for t in auto_trader.trade_history if t['pnl'] > 0]
    losers = [t for t in auto_trader.trade_history if t['pnl'] < 0]
    
    return {
        "trades": auto_trader.trade_history,
        "summary": {
            "total_trades": len(auto_trader.trade_history),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": (len(winners) / len(auto_trader.trade_history) * 100) if auto_trader.trade_history else 0,
            "total_pnl": sum(t['pnl'] for t in auto_trader.trade_history),
            "avg_win": (sum(t['pnl'] for t in winners) / len(winners)) if winners else 0,
            "avg_loss": (sum(t['pnl'] for t in losers) / len(losers)) if losers else 0
        }
    }

@api_router.get("/auto-trader/entry-conditions/{symbol}")
async def check_entry_conditions(symbol: str):
    """
    Check entry conditions for a specific stock.
    Returns which conditions are met vs pending for the auto-trader.
    
    Entry conditions (Warrior Trading Strategy):
    1. Micro-pullback pattern (1-3% retracement)
    2. MACD bullish (above signal line)
    3. Price above SMA20 (uptrend)
    4. Bull flag pattern (optional bonus)
    """
    try:
        # Get bars for analysis - use the same method as market/bars endpoint
        bars = None
        try:
            bars = alpaca_service.get_bars(symbol, timeframe="5Min", limit=100)
        except Exception as bar_err:
            error_msg = str(bar_err).lower()
            if "subscription" in error_msg or "permit" in error_msg:
                # Generate simulated bars for analysis (same as market/bars endpoint)
                from datetime import timedelta
                import random
                
                # Get current price from quote
                try:
                    quote = alpaca_service.get_latest_quote(symbol)
                    current_price = (quote.get('ask_price', 0) + quote.get('bid_price', 0)) / 2
                    if current_price == 0:
                        current_price = quote.get('ask_price', 0) or quote.get('bid_price', 0)
                except:
                    current_price = 10.0
                
                now = datetime.now(timezone.utc)
                bars = []
                seed_base = hash(symbol + now.strftime('%Y-%m-%d'))
                volatility = 0.002
                
                random.seed(seed_base)
                day_open = current_price * random.uniform(0.92, 0.97)
                
                for i in range(100):
                    bar_time = now - timedelta(minutes=(100 - i - 1) * 5)
                    random.seed(seed_base + i)
                    progress = (i + 1) / 100
                    target_price = day_open + (current_price - day_open) * progress
                    noise = random.gauss(0, volatility * target_price)
                    bar_price = target_price + noise
                    
                    open_price = bar_price * (1 + random.uniform(-volatility/2, volatility/2))
                    close_price = bar_price * (1 + random.uniform(-volatility/2, volatility/2))
                    high_price = max(open_price, close_price) * (1 + random.uniform(0, volatility))
                    low_price = min(open_price, close_price) * (1 - random.uniform(0, volatility))
                    volume = int(random.uniform(50000, 200000))
                    
                    bars.append({
                        "timestamp": bar_time.isoformat(),
                        "open": round(max(0.01, open_price), 2),
                        "high": round(max(0.01, high_price), 2),
                        "low": round(max(0.01, low_price), 2),
                        "close": round(max(0.01, close_price), 2),
                        "volume": volume
                    })
            else:
                raise bar_err
        
        if not bars or len(bars) < 20:
            return {
                "symbol": symbol,
                "error": "Insufficient bar data",
                "conditions": {}
            }
        
        # Check each condition
        conditions = {}
        
        # 1. Micro-pullback pattern check (1-3 green candles)
        pullback_check = auto_trader.check_micro_pullback(bars)
        green_candles = pullback_check.get('green_candles', 0)
        conditions['micro_pullback'] = {
            'met': pullback_check['is_valid'],
            'label': 'Pullback (1-3 green)',
            'detail': f"{green_candles} green candle{'s' if green_candles != 1 else ''}" if pullback_check['is_valid'] else f"{green_candles} green candle{'s' if green_candles != 1 else ''} (need 1-3)"
        }
        
        # 2. MACD check (crossover or just above, based on settings)
        closes = [b['close'] for b in bars]
        macd_check = auto_trader.calculate_macd(closes)
        if auto_trader.require_macd_crossover:
            conditions['macd_crossover'] = {
                'met': macd_check.get('crossover', False),
                'label': 'MACD Crossover',
                'detail': f"MACD crossed above Signal" if macd_check.get('crossover', False) else f"Waiting for crossover (MACD: {macd_check['macd']:.4f} vs Signal: {macd_check['signal']:.4f})"
            }
        else:
            conditions['macd_bullish'] = {
                'met': macd_check['bullish'],
                'label': 'MACD Bullish',
                'detail': f"MACD: {macd_check['macd']:.4f} {'>' if macd_check['bullish'] else '<'} Signal: {macd_check['signal']:.4f}"
            }
        
        # 3. SMA check (SMA20 vs SMA50, crossover or just above)
        sma_check = auto_trader.check_sma_confirmation(bars)
        sma_fast = sma_check.get('sma_fast', 0)
        sma_slow = sma_check.get('sma_slow', 0)
        
        if auto_trader.require_sma_crossover:
            conditions['sma_crossover'] = {
                'met': sma_check.get('crossover', False),
                'label': f'SMA{auto_trader.sma_period}/50 Cross',
                'detail': f"SMA{auto_trader.sma_period} crossed above SMA50" if sma_check.get('crossover', False) else f"Waiting for crossover (SMA{auto_trader.sma_period}: ${sma_fast:.2f} vs SMA50: ${sma_slow:.2f})"
            }
        else:
            conditions['above_sma'] = {
                'met': sma_check['confirmed'],
                'label': f'SMA{auto_trader.sma_period} > SMA50',
                'detail': f"SMA{auto_trader.sma_period}: ${sma_fast:.2f} {'>' if sma_check['confirmed'] else '<'} SMA50: ${sma_slow:.2f}"
            }
        
        # 4. Bull flag pattern (required if setting is on, otherwise bonus)
        bull_flag = scanner_service.check_bull_flag_pattern(bars)
        conditions['bull_flag'] = {
            'met': bull_flag,
            'label': 'Bull Flag' + (' (Required)' if auto_trader.require_bull_flag else ''),
            'detail': 'Pattern detected ✓' if bull_flag else 'No pattern detected'
        }
        
        # Count how many conditions are met
        required_conditions = ['micro_pullback', 'macd_crossover', 'macd_bullish', 'sma_crossover', 'above_sma']
        conditions_met = sum(1 for key, c in conditions.items() if key in required_conditions and c['met'])
        
        # Bull flag is required if setting is on
        if auto_trader.require_bull_flag:
            required_conditions.append('bull_flag')
        
        total_required = 3 + (1 if auto_trader.require_bull_flag else 0)
        
        # Check trading hours
        is_trading_hours = auto_trader.is_trading_hours()
        
        # Check if already in position
        already_in_position = symbol in auto_trader.open_positions
        
        # Ready to trade = all required conditions met + trading hours + not already in position
        all_conditions_met = all(
            conditions.get(key, {}).get('met', False) 
            for key in ['micro_pullback'] + 
            (['macd_crossover'] if auto_trader.require_macd_crossover else ['macd_bullish']) +
            (['sma_crossover'] if auto_trader.require_sma_crossover else ['above_sma']) +
            (['bull_flag'] if auto_trader.require_bull_flag else [])
        )
        ready = all_conditions_met and is_trading_hours and not already_in_position
        
        return {
            "symbol": symbol,
            "conditions": conditions,
            "conditions_met": conditions_met,
            "total_required": total_required,
            "ready_for_auto_trade": ready,
            "is_trading_hours": is_trading_hours,
            "already_in_position": already_in_position,
            "trading_hours": f"{auto_trader.trading_start_hour}:00 AM - {auto_trader.trading_end_hour}:00 AM EST"
        }
        
    except Exception as e:
        logger.error(f"Error checking entry conditions for {symbol}: {str(e)}")
        return {
            "symbol": symbol,
            "error": str(e),
            "conditions": {}
        }

@api_router.get("/trade-history")
async def get_trade_history(limit: int = 100, symbol: str = None):
    """Get historical trades"""
    trades = trade_history.get_trades(limit=limit, symbol=symbol)
    return {"trades": trades}

@api_router.get("/trade-history/analytics")
async def get_trade_analytics():
    """Get trading performance analytics"""
    analytics = trade_history.get_analytics()
    return analytics

@api_router.get("/trade-history/daily-pnl")
async def get_daily_pnl(days: int = 30):
    """Get daily P&L for the last N days"""
    daily_pnl = trade_history.get_daily_pnl(days=days)
    return {"daily_pnl": daily_pnl}

@api_router.post("/trade-history/log")
async def log_trade(trade_data: dict):
    """Manually log a trade"""
    trade_history.log_trade(trade_data)
    return {"message": "Trade logged successfully"}

# ============ MISSED OPPORTUNITIES ENDPOINTS ============

@api_router.get("/missed-opportunities")
async def get_missed_opportunities(date: str = None, limit: int = 100):
    """Get missed trading opportunities"""
    # Run synchronous file I/O in thread pool to avoid blocking the event loop
    opportunities = await asyncio.to_thread(missed_opportunities.get_opportunities, date=date, limit=limit)
    return {"opportunities": opportunities}

@api_router.get("/missed-opportunities/analytics")
async def get_missed_analytics():
    """Get analytics on missed opportunities"""
    # Run synchronous file I/O in thread pool to avoid blocking the event loop
    analytics = await asyncio.to_thread(missed_opportunities.get_analytics)
    return analytics

@api_router.post("/missed-opportunities/log")
async def log_missed_opportunity(data: dict):
    """Manually log a missed opportunity"""
    opportunity = missed_opportunities.log_single_opportunity(
        stock_data=data.get('stock', {}),
        reason=data.get('reason', '')
    )
    return {"message": "Opportunity logged", "opportunity": opportunity}

@api_router.post("/missed-opportunities/log-scanner")
async def log_scanner_opportunities(data: dict):
    """Log all scanner results that weren't traded"""
    scanner_results = data.get('scanner_results', [])
    traded_symbols = data.get('traded_symbols', [])
    count = missed_opportunities.log_scanner_results(scanner_results, traded_symbols)
    return {"message": f"Logged {count} missed opportunities"}

@api_router.put("/missed-opportunities/{opportunity_id}")
async def update_missed_opportunity(opportunity_id: int, updates: dict):
    """Update a missed opportunity (add notes, close price, status)"""
    success = missed_opportunities.update_opportunity(opportunity_id, updates)
    if success:
        return {"message": "Opportunity updated"}
    raise HTTPException(status_code=404, detail="Opportunity not found")

# ============ END MISSED OPPORTUNITIES ============

@api_router.post("/auto-trader/process")
async def process_auto_trading():
    """Manually trigger auto-trading processing (called by scanner)"""
    try:
        if not auto_trader.active:
            return {"message": "Auto-trader not active"}
        
        # Get scanner results from most recent scan
        criteria = {
            "min_price": 2,
            "max_price": 20,
            "min_change": 10,
            "min_volume_ratio": 5,
            "max_float": 20_000_000
        }
        
        scanner_results = scanner_service.scan_stocks(criteria)
        account = alpaca_service.get_account()
        buying_power = account.get('buying_power', 0)
        portfolio_value = account.get('portfolio_value', 0)
        
        await auto_trader.process_scanner_results(scanner_results, buying_power, portfolio_value)
        
        return {
            "processed": True,
            "stocks_analyzed": len(scanner_results),
            "positions_opened": len(auto_trader.open_positions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scanner/demo")
async def run_demo_scan(
    min_price: float = 2.0,
    max_price: float = 20.0,
    min_change: float = 10.0,
    min_volume_ratio: float = 5.0,
    max_float: int = 20_000_000
):
    """Run a demo scan with simulated market data"""
    from services.demo_scanner_service import demo_scanner
    criteria = {
        "min_price": min_price,
        "max_price": max_price,
        "min_change": min_change,
        "min_volume_ratio": min_volume_ratio,
        "max_float": max_float
    }
    results = demo_scanner.scan_stocks(criteria)
    return {
        "results": results,
        "is_market_hours": demo_scanner.is_market_hours(),
        "is_momentum_window": demo_scanner.is_momentum_window(),
        "scan_count": demo_scanner.scan_counter
    }

@api_router.get("/market/quotes")
async def get_quotes(symbols: str):
    try:
        symbol_list = symbols.split(",")
        quotes = alpaca_service.get_quotes(symbol_list)
        return quotes
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/market/quote/{symbol}")
async def get_quote(symbol: str):
    try:
        quotes = alpaca_service.get_quotes([symbol])
        if quotes and symbol in quotes:
            return quotes[symbol]
        else:
            raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/market/bars/{symbol}")
async def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 100, use_fallback: bool = True):
    """
    Get historical bar data for a symbol.
    
    If use_fallback=True (default), will automatically use Nasdaq data when Alpaca IEX data
    is incomplete or doesn't match the current quote price.
    """
    try:
        if use_fallback and timeframe in ["5Min", "1Min"]:
            # Use fallback method for intraday data - run in thread pool to avoid blocking
            result = await asyncio.to_thread(alpaca_service.get_bars_with_fallback, symbol, timeframe, limit)
            bars = result.get('bars', [])
            source = result.get('source', 'unknown')
            warning = result.get('warning')
            
            # Add source info to response
            return {
                'bars': bars,
                'source': source,
                'warning': warning,
                'symbol': symbol
            }
        else:
            # Use standard Alpaca for daily data - run in thread pool
            bars = await asyncio.to_thread(alpaca_service.get_bars, symbol, timeframe, limit)
            return {'bars': bars, 'source': 'alpaca', 'symbol': symbol}
    except Exception as e:
        # If Alpaca historical data fails, generate realistic bars based on ACTUAL current price
        error_msg = str(e).lower()
        if "subscription" in error_msg or "permit" in error_msg:
            logger.warning(f"Alpaca subscription doesn't permit historical data for {symbol} - generating simulated bars")
            from datetime import datetime, timedelta
            import random
            
            # Get ACTUAL current price from quote (most accurate) - run in thread pool
            try:
                quote = await asyncio.to_thread(alpaca_service.get_latest_quote, symbol)
                logger.info(f"Got quote for {symbol}: {quote}")
                current_price = (quote.get('ask_price', 0) + quote.get('bid_price', 0)) / 2
                if current_price == 0:
                    current_price = quote.get('ask_price', 0) or quote.get('bid_price', 0)
                if current_price == 0:
                    # Fallback to position
                    positions = await asyncio.to_thread(alpaca_service.get_positions)
                    position = next((p for p in positions if p['symbol'] == symbol), None)
                    current_price = position['current_price'] if position else 10.0
                    logger.info(f"Used position price for {symbol}: ${current_price}")
            except Exception as quote_err:
                logger.error(f"Failed to get quote for {symbol}: {quote_err}")
                # Try position as fallback
                try:
                    positions = await asyncio.to_thread(alpaca_service.get_positions)
                    position = next((p for p in positions if p['symbol'] == symbol), None)
                    current_price = position['current_price'] if position else 10.0
                    logger.info(f"Used position fallback for {symbol}: ${current_price}")
                except:
                    current_price = 10.0
            
            logger.info(f"Generating simulated bars for {symbol} based on real quote: ${current_price:.2f}")
            
            now = datetime.now()
            bars = []
            
            # Use symbol + date as seed for consistency within a day
            seed_base = hash(symbol + now.strftime('%Y-%m-%d'))
            
            # Calculate time intervals based on timeframe
            if timeframe == "5Min":
                interval_minutes = 5
            elif timeframe == "1Min":
                interval_minutes = 1
            elif timeframe == "1Hour":
                interval_minutes = 60
            else:
                interval_minutes = 1440  # 1 day
            
            # Generate bars going back from now
            volatility = 0.002 if timeframe in ["1Min", "5Min"] else 0.01
            
            # Start from a base price (today's estimated open, ~5% below current for gapper)
            random.seed(seed_base)
            day_open = current_price * random.uniform(0.92, 0.97)
            
            for i in range(limit):
                bar_time = now - timedelta(minutes=(limit - i - 1) * interval_minutes)
                
                # Use consistent seed for each bar
                random.seed(seed_base + i)
                
                # Progress through the day toward current price
                progress = (i + 1) / limit
                target_price = day_open + (current_price - day_open) * progress
                
                # Add noise
                noise = random.gauss(0, volatility * target_price)
                bar_price = target_price + noise
                
                # Generate OHLC
                open_price = bar_price * (1 + random.uniform(-volatility/2, volatility/2))
                close_price = bar_price * (1 + random.uniform(-volatility/2, volatility/2))
                high_price = max(open_price, close_price) * (1 + random.uniform(0, volatility))
                low_price = min(open_price, close_price) * (1 - random.uniform(0, volatility))
                
                volume = int(random.uniform(50000, 200000))
                
                bars.append({
                    "timestamp": bar_time.isoformat(),
                    "open": round(max(0.01, open_price), 2),
                    "high": round(max(0.01, high_price), 2),
                    "low": round(max(0.01, low_price), 2),
                    "close": round(max(0.01, close_price), 2),
                    "volume": volume
                })
            
            # CRITICAL: Last bar must use REAL current price from quote
            if bars:
                # Make last bar reflect actual real-time price
                last_bar = bars[-1]
                last_bar["close"] = round(current_price, 2)
                last_bar["high"] = round(max(last_bar["high"], current_price), 2)
                last_bar["low"] = round(min(last_bar["low"], current_price), 2)
                # Update timestamp to current time
                last_bar["timestamp"] = now.isoformat()
            
            return bars
        else:
            raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/settings")
async def save_settings(settings: Settings):
    try:
        os.environ['ALPACA_API_KEY'] = settings.api_key
        os.environ['ALPACA_SECRET_KEY'] = settings.secret_key
        os.environ['ALPACA_BASE_URL'] = settings.base_url
        os.environ['DAY_TRADING_MODE'] = 'true' if settings.day_trading_mode else 'false'
        os.environ['SMA_SHORT'] = str(settings.sma_short)
        os.environ['SMA_LONG'] = str(settings.sma_long)
        
        # Save to .env file
        env_path = ROOT_DIR / '.env'
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        # Check what settings exist
        has_day_trading_mode = any(line.startswith('DAY_TRADING_MODE') for line in lines)
        has_sma_short = any(line.startswith('SMA_SHORT') for line in lines)
        has_sma_long = any(line.startswith('SMA_LONG') for line in lines)
        
        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith('ALPACA_API_KEY'):
                    f.write(f'ALPACA_API_KEY="{settings.api_key}"\n')
                elif line.startswith('ALPACA_SECRET_KEY'):
                    f.write(f'ALPACA_SECRET_KEY="{settings.secret_key}"\n')
                elif line.startswith('ALPACA_BASE_URL'):
                    f.write(f'ALPACA_BASE_URL="{settings.base_url}"\n')
                elif line.startswith('DAY_TRADING_MODE'):
                    f.write(f'DAY_TRADING_MODE="{"true" if settings.day_trading_mode else "false"}"\n')
                elif line.startswith('SMA_SHORT'):
                    f.write(f'SMA_SHORT="{settings.sma_short}"\n')
                elif line.startswith('SMA_LONG'):
                    f.write(f'SMA_LONG="{settings.sma_long}"\n')
                else:
                    f.write(line)
            
            # Add new settings if they don't exist
            if not has_day_trading_mode:
                f.write(f'DAY_TRADING_MODE="{"true" if settings.day_trading_mode else "false"}"\n')
            if not has_sma_short:
                f.write(f'SMA_SHORT="{settings.sma_short}"\n')
            if not has_sma_long:
                f.write(f'SMA_LONG="{settings.sma_long}"\n')
        
        return {"message": "Settings saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/settings")
async def get_settings():
    secret_key = os.getenv('ALPACA_SECRET_KEY', '')
    # Mask the secret key for security (show *** if it exists)
    masked_secret = '*' * 32 if secret_key else ''
    
    return {
        "api_key": os.getenv('ALPACA_API_KEY', ''),
        "secret_key_masked": masked_secret,
        "has_secret_key": bool(secret_key),
        "base_url": os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'),
        "day_trading_mode": os.getenv('DAY_TRADING_MODE', 'false').lower() == 'true',
        "sma_short": int(os.getenv('SMA_SHORT', '20')),
        "sma_long": int(os.getenv('SMA_LONG', '50'))
    }

@api_router.get("/news/{symbol}")
async def get_news(symbol: str, limit: int = 5):
    """Get recent news for a symbol from Google News"""
    try:
        from services.google_news_service import google_news_service
        
        # Get company name for better search
        company_name = None
        try:
            asset_info = alpaca_service.get_asset(symbol)
            company_name = asset_info.get('name')
        except:
            pass
        
        result = google_news_service.search_stock_news(symbol, hours_back=24, limit=limit, company_name=company_name)
        
        return {
            "symbol": symbol,
            "company_name": company_name,
            "has_news": result['has_news'],
            "articles": result['articles']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_services():
    """Start background services"""
    position_monitor.start()
    # Start monitoring loop in background
    asyncio.create_task(position_monitor.monitor_positions())
    
    # Start end-of-day closer service
    eod_closer.start()
    asyncio.create_task(eod_closer.monitor_eod())
    logger.info("🚀 Position Monitor Service started")
    
    # IMPORTANT: Auto-sync all existing positions to monitoring on startup
    # This ensures stop-loss and take-profit are active for ALL positions
    try:
        existing_positions = alpaca_service.get_positions()
        if existing_positions:
            synced_count = 0
            for pos in existing_positions:
                symbol = pos['symbol']
                if symbol not in position_monitor.monitored_positions:
                    config = {
                        'entry_price': pos['avg_entry_price'],
                        'shares': pos['qty'],
                        'stop_type': 'trailing',
                        'stop_loss_pct': 1.0,
                        'trailing_stop_pct': 1.0,
                        'take_profit_pct': 2.0,
                        'partial_sell_pct': 50.0,
                        'partial_sell_trigger_pct': 2.0,
                        'move_to_breakeven': True
                    }
                    position_monitor.add_position(symbol, config)
                    synced_count += 1
            if synced_count > 0:
                logger.info(f"📊 Auto-synced {synced_count} existing position(s) to monitoring")
    except Exception as e:
        logger.error(f"Failed to auto-sync positions on startup: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    position_monitor.stop()
    eod_closer.stop()
    client.close()
    logger.info("🛑 Services shut down")