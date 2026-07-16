from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import jwt
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Literal
import uuid
from datetime import datetime, timezone
import pandas as pd
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Shared MongoDB connection (see database.py) - avoids circular imports with services
from database import db, client
from auth import (
    verify_token, seed_user, create_access_token, verify_password,
    check_lockout, record_failed_attempt, clear_failed_attempts
)

app = FastAPI(title="MomentumX Trading Platform")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth routes live on their own unprotected router (no verify_token
# dependency) since /login must be reachable without a token in hand.
auth_router = APIRouter(prefix="/api/auth")

class LoginRequest(BaseModel):
    email: str
    password: str

@auth_router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    email = body.email.strip().lower()
    # Lockout is keyed by email only (not IP) - this is a single-user
    # internal tool, and get_remote_address() was observed to be unstable
    # through this environment's ingress proxy (different upstream IPs for
    # the same real client across consecutive requests), which made an
    # IP-based identifier unreliably split the failed-attempt count.
    await check_lockout(email)

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        await record_failed_attempt(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await clear_failed_attempts(email)
    token = create_access_token(email)
    return {"access_token": token, "email": email}

@auth_router.get("/me")
async def get_me(email: str = Depends(verify_token)):
    return {"email": email}

# WebSocket endpoint lives on its own unprotected router - browsers cannot
# set custom Authorization headers on a WebSocket handshake, so the JWT is
# passed as a `?token=` query param and verified manually below instead of
# via the shared Header-based verify_token() dependency.
ws_router = APIRouter()

@ws_router.websocket("/api/ws/market-data")
async def market_data_ws(websocket: WebSocket, token: Optional[str] = Query(None)):
    """
    Real-time market data push to the frontend - trades/quotes/minute-bars
    forwarded live from the Alpaca IEX WebSocket stream (see
    services/market_data_stream_service.py). Client sends
    {"action": "subscribe", "symbols": ["AAPL", ...]} to add symbols of
    interest; only messages for subscribed symbols are forwarded back.
    """
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    listener_queue = market_data_stream.register_listener()
    client_symbols: set = set()

    async def forward_stream():
        while True:
            msg = await listener_queue.get()
            symbol = msg.get("S")
            if symbol is None or symbol in client_symbols:
                await websocket.send_json(msg)

    forward_task = asyncio.create_task(forward_stream())
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                symbols = [str(s).upper() for s in data.get("symbols", []) if s]
                client_symbols.update(symbols)
                await market_data_stream.subscribe(symbols)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"market_data_ws client loop ended: {e}")
    finally:
        forward_task.cancel()
        market_data_stream.unregister_listener(listener_queue)

api_router = APIRouter(prefix="/api", dependencies=[Depends(verify_token)])

# Import services
from services.alpaca_service import alpaca_service
from services.scanner_service import scanner_service
from services.auto_trader_service import auto_trader
from services.position_monitor_service import position_monitor
from services.eod_closer_service import eod_closer
from services.trade_history_service import trade_history
from services.missed_opportunities_service import missed_opportunities
from services.market_data_stream_service import market_data_stream
import asyncio

class TradeOrder(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    qty: float = Field(..., gt=0)
    side: Literal["buy", "sell"] = "buy"
    stop_loss_pct: Optional[float] = Field(None, ge=0, le=50)
    take_profit_pct: Optional[float] = Field(None, ge=0, le=100)
    entry_price: Optional[float] = Field(None, gt=0)
    stop_type: Optional[Literal["fixed", "trailing"]] = "fixed"
    trailing_stop_pct: Optional[float] = Field(5.0, ge=0, le=50)
    partial_sell_pct: Optional[float] = Field(50.0, ge=0, le=100)
    partial_sell_trigger_pct: Optional[float] = Field(10.0, ge=0, le=100)
    move_to_breakeven: Optional[bool] = True

    @field_validator('symbol')
    @classmethod
    def symbol_uppercase(cls, v):
        return v.strip().upper()

class ScanCriteria(BaseModel):
    min_price: float = Field(2.0, gt=0)
    max_price: float = Field(20.0, gt=0)
    min_change: float = Field(10.0, ge=0)
    min_volume_ratio: float = Field(5.0, gt=0)
    max_float: int = Field(20_000_000, gt=0)

    @field_validator('max_price')
    @classmethod
    def max_greater_than_min(cls, v, info):
        min_price = info.data.get('min_price')
        if min_price is not None and v <= min_price:
            raise ValueError('max_price must be greater than min_price')
        return v

class SmaSettingsUpdate(BaseModel):
    """Non-secret strategy config. Alpaca keys are managed via .env only (Phase 1 #2)."""
    sma_short: int = Field(20, ge=5, le=100)
    sma_long: int = Field(50, ge=10, le=200)

class TradingModeUpdate(BaseModel):
    """Paper <-> Live trading account switch. Live requires typed confirmation."""
    mode: Literal['paper', 'live']
    confirm: Optional[str] = None

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
        account = await asyncio.to_thread(alpaca_service.get_account)
        return account
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/positions")
async def get_positions():
    try:
        positions = await asyncio.to_thread(alpaca_service.get_positions)
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
        positions = await asyncio.to_thread(alpaca_service.get_positions)
        
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
        orders = await asyncio.to_thread(alpaca_service.get_orders, status, limit)
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/orders")
@limiter.limit("20/minute")
async def place_order(request: Request, order: TradeOrder):
    try:
        # Check if market is open for buy orders (extended hours: 4 AM - 8 PM ET)
        if order.side.lower() == "buy" and not is_market_open():
            session = get_market_session()
            raise HTTPException(
                status_code=400, 
                detail=f"Market is {session}. Extended trading hours: 4:00 AM - 8:00 PM ET (Monday-Friday)"
            )
        
        # HARD KILL SWITCH: block new BUY orders once the daily loss limit / max
        # consecutive losses is hit (server-side, cannot be bypassed by the frontend)
        if order.side.lower() == "buy":
            try:
                account_check = await asyncio.to_thread(alpaca_service.get_account)
                risk_check = auto_trader.check_risk_limits(account_check.get('portfolio_value', 0))
                if not risk_check['can_trade']:
                    raise HTTPException(status_code=403, detail=f"Trading halted: {risk_check['reason']}")
            except HTTPException:
                raise
            except Exception as risk_err:
                logger.warning(f"Could not evaluate risk limits before order: {risk_err}")
        
        from services.position_monitor_service import position_monitor
        
        # For SELL orders, capture position data before selling to log to trade history
        position_data = None
        if order.side.lower() == "sell":
            try:
                positions = await asyncio.to_thread(alpaca_service.get_positions)
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
                quote = await asyncio.to_thread(alpaca_service.get_latest_quote, order.symbol)
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
                result = await asyncio.to_thread(alpaca_service.place_market_order, order.symbol, order.qty, "buy")
                
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
                    result = await asyncio.to_thread(
                        alpaca_service.place_bracket_order,
                        order.symbol,
                        order.qty,
                        stop_loss_price,
                        take_profit_price
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
                    result = await asyncio.to_thread(alpaca_service.place_market_order, order.symbol, order.qty, "buy")
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
            result = await asyncio.to_thread(alpaca_service.place_market_order, order.symbol, order.qty, order.side)
            
            # IMPORTANT: For ALL buy orders, add to position monitor with default settings
            # This ensures stop-loss and take-profit are always active
            if order.side.lower() == "buy":
                try:
                    # Get the order status to find the actual fill price - no artificial
                    # sleep here; market orders in paper trading fill near-instantly and
                    # we fall back to the current quote below if the fill isn't ready yet.
                    try:
                        order_status = await asyncio.to_thread(alpaca_service.get_order, result.get('order_id'))
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
                        quote = await asyncio.to_thread(alpaca_service.get_latest_quote, order.symbol)
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
                # Prefer the real fill price for exit P&L over the last quote (Phase 4 #14)
                exit_price = position_data['current_price']
                if result.get('filled_avg_price'):
                    exit_price = float(result['filled_avg_price'])
                shares = float(order.qty)
                pnl = (exit_price - entry_price) * shares
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                
                # Get actual entry time from order history
                entry_time = await asyncio.to_thread(alpaca_service.get_position_entry_time, order.symbol)
                if not entry_time:
                    entry_time = datetime.now(timezone.utc).isoformat()
                
                await trade_history.log_trade({
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
                await auto_trader.save_state()
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.delete("/orders")
@limiter.limit("10/minute")
async def cancel_all_orders(request: Request):
    """Cancel all open orders"""
    try:
        # Get all orders from Alpaca (filter for open statuses)
        orders = await asyncio.to_thread(alpaca_service.get_orders, "all", 50)
        open_statuses = ['new', 'pending_new', 'accepted', 'partially_filled']
        cancelled_count = 0
        
        for order in orders:
            if order['status'] in open_statuses:
                try:
                    await asyncio.to_thread(alpaca_service.cancel_order, order['order_id'])
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
        await asyncio.to_thread(alpaca_service.cancel_order, order_id)
        return {"message": f"Order {order_id} cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/scanner/scan")
@limiter.limit("10/minute")
async def scan_stocks(request: Request, criteria: ScanCriteria, use_demo: bool = False):
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
                    await missed_opportunities.log_scanner_results(results, traded_symbols)
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
    """Enable or disable auto-trading. Never allowed while in LIVE mode -
    the unattended algo is paper-only until manually trusted with real money."""
    try:
        if enabled and alpaca_service.trading_mode == "live":
            raise HTTPException(status_code=400, detail="Auto-trader cannot be enabled in LIVE trading mode (real money). Switch to PAPER mode in Settings to use the auto-trader.")
        auto_trader.active = enabled
        await auto_trader.save_state()
        status = "enabled" if enabled else "disabled"
        return {
            "status": status,
            "message": f"Auto-trading {status}",
            "active": auto_trader.active
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/auto-trader/status")
async def get_auto_trader_status():
    """Get current auto-trader status with Warrior Trading strategy metrics"""
    # Get account info for portfolio value
    try:
        account = await asyncio.to_thread(alpaca_service.get_account)
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
            "reward_risk_ratio": auto_trader.reward_risk_ratio,  # 2.0 = 2:1
            "daily_max_loss_pct": auto_trader.daily_max_loss_pct * 100,  # 1%
            "max_consecutive_losses": auto_trader.max_consecutive_losses,  # 3
            "trading_hours": f"{auto_trader.trading_start_hour}:00 AM - {auto_trader.trading_end_hour - 12 if auto_trader.trading_end_hour > 12 else auto_trader.trading_end_hour}:{auto_trader.trading_end_minute:02d} PM EST",
            "partial_sell_pct": auto_trader.partial_sell_pct * 100,  # 50%
            "partial_sell_trigger_pct": auto_trader.profit_target_pct * 100,  # 2%
            "move_to_breakeven": auto_trader.move_to_breakeven,  # True
            "eod_close_time": "3:30 PM EST"
        },
        "entry_conditions": {
            "pullback_min_candles": auto_trader.pullback_min_candles,
            "pullback_max_candles": auto_trader.pullback_max_candles,
            "pullback_lookback_bars": auto_trader.pullback_lookback_bars,
            "pullback_retracement_max_pct": auto_trader.pullback_retracement_max_pct * 100,
            "max_stop_distance_pct": auto_trader.max_stop_distance_pct * 100,
            "breakout_bailout_seconds": auto_trader.breakout_bailout_seconds,
            "require_micro_pullback": auto_trader.require_micro_pullback,
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
                "pullback_min_candles": auto_trader.pullback_min_candles,
                "pullback_max_candles": auto_trader.pullback_max_candles,
                "pullback_lookback_bars": auto_trader.pullback_lookback_bars,
                "pullback_retracement_max_pct": auto_trader.pullback_retracement_max_pct * 100,
                "max_stop_distance_pct": auto_trader.max_stop_distance_pct * 100,
                "breakout_bailout_seconds": auto_trader.breakout_bailout_seconds,
                "require_micro_pullback": auto_trader.require_micro_pullback,
                "require_macd_crossover": auto_trader.require_macd_crossover,
                "require_sma_crossover": auto_trader.require_sma_crossover,
                "require_bull_flag": auto_trader.require_bull_flag,
                "sma_period": auto_trader.sma_period,
                "trading_start_hour": auto_trader.trading_start_hour,
                "trading_end_hour": auto_trader.trading_end_hour,
                # Trade management
                "profit_target_pct": auto_trader.profit_target_pct * 100,
                "stop_loss_pct": auto_trader.stop_loss_pct * 100,
                "reward_risk_ratio": auto_trader.reward_risk_ratio,
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
    
    Entry conditions (Warrior Trading "First Pullback" Strategy):
    1. First pullback pattern (1-3 red candles, breaks prior high, holds the 50% Rule)
    2. MACD bullish (above signal line)
    3. Price above SMA20 (uptrend)
    4. Bull flag pattern (optional bonus)
    """
    try:
        # Get bars for analysis - REAL DATA ONLY (Alpaca -> Yahoo -> Nasdaq fallback
        # chain), merged with the real-time WebSocket stream to fill the free-tier's
        # ~15 minute REST embargo gap. Never fabricate bars; if no real data is
        # available, skip this symbol.
        await market_data_stream.subscribe([symbol])
        bars_result = await asyncio.to_thread(alpaca_service.get_bars_with_fallback, symbol, "5Min", 100)
        bars = [] if bars_result.get('no_historical_data') else bars_result.get('bars', [])
        bars = market_data_stream.merge_with_stream(symbol, bars, "5Min", 100)
        
        if not bars or len(bars) < 20:
            return {
                "symbol": symbol,
                "error": "No real market data available for this symbol - skipped (no synthetic data is ever used)",
                "conditions": {}
            }
        
        # Check each condition
        conditions = {}
        
        # 1. First-pullback pattern check (1-3 red candles, then breaks the prior candle's high, holding the 50% Rule)
        pullback_check = auto_trader.check_first_pullback(bars)
        pullback_candles = pullback_check.get('pullback_candles', 0)
        conditions['micro_pullback'] = {
            'met': pullback_check['is_valid'],
            'label': 'First Pullback (1-3 red)',
            'detail': pullback_check.get('pattern') if pullback_check['is_valid'] else pullback_check.get('reason', f"{pullback_candles} red candle{'s' if pullback_candles != 1 else ''} found")
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
            "trading_hours": f"{auto_trader.trading_start_hour}:00 AM - {auto_trader.trading_end_hour - 12 if auto_trader.trading_end_hour > 12 else auto_trader.trading_end_hour}:{auto_trader.trading_end_minute:02d} PM EST"
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
    trades = await trade_history.get_trades(limit=limit, symbol=symbol)
    return {"trades": trades}

@api_router.get("/trade-history/analytics")
async def get_trade_analytics(days: Optional[int] = 180):
    """Get trading performance analytics (bounded to last `days` days by default; pass 0 for all-time)"""
    analytics = await trade_history.get_analytics(days=days if days else None)
    return analytics

@api_router.get("/trade-history/daily-pnl")
async def get_daily_pnl(days: int = 30):
    """Get daily P&L for the last N days"""
    daily_pnl = await trade_history.get_daily_pnl(days=days)
    return {"daily_pnl": daily_pnl}

@api_router.post("/trade-history/log")
async def log_trade(trade_data: dict):
    """Manually log a trade"""
    await trade_history.log_trade(trade_data)
    return {"message": "Trade logged successfully"}

# ============ MISSED OPPORTUNITIES ENDPOINTS ============

@api_router.get("/missed-opportunities")
async def get_missed_opportunities(date: str = None, limit: int = 100):
    """Get missed trading opportunities"""
    opportunities = await missed_opportunities.get_opportunities(date=date, limit=limit)
    return {"opportunities": opportunities}

@api_router.get("/missed-opportunities/analytics")
async def get_missed_analytics(days: Optional[int] = 180):
    """Get analytics on missed opportunities (bounded to last `days` days by default; pass 0 for all-time)"""
    analytics = await missed_opportunities.get_analytics(days=days if days else None)
    return analytics

@api_router.post("/missed-opportunities/log")
async def log_missed_opportunity(data: dict):
    """Manually log a missed opportunity"""
    opportunity = await missed_opportunities.log_single_opportunity(
        stock_data=data.get('stock', {}),
        reason=data.get('reason', '')
    )
    return {"message": "Opportunity logged", "opportunity": opportunity}

@api_router.post("/missed-opportunities/log-scanner")
async def log_scanner_opportunities(data: dict):
    """Log all scanner results that weren't traded"""
    scanner_results = data.get('scanner_results', [])
    traded_symbols = data.get('traded_symbols', [])
    count = await missed_opportunities.log_scanner_results(scanner_results, traded_symbols)
    return {"message": f"Logged {count} missed opportunities"}

@api_router.put("/missed-opportunities/{opportunity_id}")
async def update_missed_opportunity(opportunity_id: int, updates: dict):
    """Update a missed opportunity (add notes, close price, status)"""
    success = await missed_opportunities.update_opportunity(opportunity_id, updates)
    if success:
        return {"message": "Opportunity updated"}
    raise HTTPException(status_code=404, detail="Opportunity not found")

# ============ END MISSED OPPORTUNITIES ============

@api_router.post("/auto-trader/process")
@limiter.limit("10/minute")
async def process_auto_trading(request: Request):
    """Manually trigger auto-trading processing (in addition to the background loop)"""
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
        
        # scan_market() (not scan_stocks() directly) so this manual trigger
        # reuses the same 120s-cached scan the dashboard/background loop use
        # instead of running a duplicate full 128-batch snapshot scan.
        scanner_results = await asyncio.to_thread(scanner_service.scan_market, criteria)
        account = await asyncio.to_thread(alpaca_service.get_account)
        portfolio_value = account.get('portfolio_value', 0)
        
        await auto_trader.process_scanner_results(scanner_results, portfolio_value)
        
        return {
            "processed": True,
            "stocks_analyzed": len(scanner_results),
            "positions_opened": len(auto_trader.open_positions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scanner/demo")
@limiter.limit("20/minute")
async def run_demo_scan(
    request: Request,
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
    results = await asyncio.to_thread(demo_scanner.scan_stocks, criteria)
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
        # Serve from the real-time stream cache wherever we have a fresh
        # (<8s old) quote - falls back to REST only for symbols not
        # actively streamed yet.
        result = {}
        rest_needed = []
        for s in symbol_list:
            cached = market_data_stream.get_cached_quote(s)
            if cached:
                result[s.upper()] = cached
            else:
                rest_needed.append(s)
        if rest_needed:
            rest_quotes = await asyncio.to_thread(alpaca_service.get_quotes, rest_needed)
            result.update(rest_quotes)
        asyncio.create_task(market_data_stream.subscribe(symbol_list))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/market/quote/{symbol}")
async def get_quote(symbol: str):
    try:
        cached = market_data_stream.get_cached_quote(symbol)
        if cached:
            asyncio.create_task(market_data_stream.subscribe([symbol]))
            return cached
        quotes = await asyncio.to_thread(alpaca_service.get_quotes, [symbol])
        asyncio.create_task(market_data_stream.subscribe([symbol]))
        if quotes and symbol in quotes:
            return quotes[symbol]
        else:
            raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/market/stream-status")
async def get_stream_status():
    """Debug/UI endpoint - current Alpaca real-time WebSocket stream health."""
    return market_data_stream.get_status()

@api_router.get("/market/large-trades/{symbol}")
async def get_large_trades(symbol: str, limit: int = 20):
    """
    Recent unusually-large trade prints (block trades) for `symbol`, tagged
    buy/sell via the tick rule - a real-data proxy for order-flow
    support/resistance, since Alpaca's IEX/free tier has no Level 2
    depth-of-book. Subscribes the symbol to the live stream as a side effect.
    """
    asyncio.create_task(market_data_stream.subscribe([symbol]))
    return {
        'symbol': symbol,
        'large_trades': market_data_stream.get_large_trades(symbol, limit=limit)
    }

@api_router.get("/market/bars/{symbol}")
async def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 100, use_fallback: bool = True, since: Optional[str] = None):
    """
    Get historical bar data for a symbol. REAL DATA ONLY.

    Never generates synthetic/fake OHLC data. If no real data is available
    from Alpaca, Yahoo, or Nasdaq, returns an explicit "no data" response
    instead of fabricating bars. For intraday timeframes, the free-tier's
    ~15 minute REST embargo gap is filled in with genuinely real-time bars
    from the Alpaca WebSocket stream (subscribing this symbol as a side effect).

    `since`: optional ISO timestamp of the last bar the caller already has
    cached - when provided, only bars newer than this are requested from
    Alpaca instead of re-pulling the full `limit`-sized historical window,
    so periodic UI refreshes are a small incremental fetch, not a full
    history re-download every time.
    """
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            since_dt = None
    try:
        if timeframe in ("10Sec", "10S", "10s"):
            # Alpaca's Bars API has no "seconds" timeframe at all - this is
            # built entirely from real trade ticks off the live WebSocket
            # stream (self-bucketed, never fabricated). Only available once
            # the symbol has been streaming for a little while.
            asyncio.create_task(market_data_stream.subscribe([symbol]))
            bars = market_data_stream.get_tick_bars(symbol, bucket_seconds=10, limit=limit)
            return {
                'bars': bars,
                'source': 'alpaca_realtime_ticks' if bars else 'none',
                'no_historical_data': not bars,
                'warning': None if bars else 'No real-time trade ticks yet for this symbol - 10-second bars build up as trades stream in (no historical 10-second data exists on Alpaca)',
                'symbol': symbol
            }
        if use_fallback and timeframe in ["5Min", "1Min"]:
            # Keep this symbol streaming going forward (fire-and-forget -
            # doesn't block this request; benefits the NEXT call/tick).
            asyncio.create_task(market_data_stream.subscribe([symbol]))
            # Use fallback method for intraday data - run in thread pool to avoid blocking
            result = await asyncio.to_thread(alpaca_service.get_bars_with_fallback, symbol, timeframe, limit, since_dt)
            bars = market_data_stream.merge_with_stream(symbol, result.get('bars', []), timeframe, limit)
            return {
                'bars': bars,
                'source': result.get('source', 'unknown'),
                'warning': result.get('warning'),
                'no_historical_data': result.get('no_historical_data', False) and not bars,
                'symbol': symbol
            }
        else:
            # Use standard Alpaca for daily data - run in thread pool
            bars = await asyncio.to_thread(alpaca_service.get_bars, symbol, timeframe, limit, since_dt)
            if not bars:
                return {
                    'bars': [],
                    'source': 'none',
                    'no_historical_data': True,
                    'warning': f'No real historical data available for {symbol}',
                    'symbol': symbol
                }
            return {'bars': bars, 'source': 'alpaca', 'symbol': symbol}
    except Exception as e:
        # Real data unavailable - never fabricate bars, but also never return a
        # 502: the platform's edge/CDN (Cloudflare) intercepts 502 responses and
        # replaces the JSON body with its own generic HTML error page, which
        # breaks frontend Promise.all() chart fetches. Return 200 with an
        # explicit no_historical_data flag instead, matching the shape already
        # used by the fallback branch above.
        logger.error(f"No real market data available for {symbol}: {e}")
        return {
            'bars': [],
            'source': 'none',
            'no_historical_data': True,
            'warning': f'No real historical data available for {symbol}: {str(e)}',
            'symbol': symbol
        }

@api_router.post("/settings")
async def save_settings(settings: SmaSettingsUpdate):
    """
    Update non-secret strategy configuration (SMA periods) - persisted to
    MongoDB, not .env. Alpaca API keys/secret are intentionally NOT
    configurable at runtime; manage them directly via the backend .env file
    (Phase 1 #2 - no runtime .env rewriting of secrets).
    """
    try:
        if settings.sma_short >= settings.sma_long:
            raise HTTPException(status_code=400, detail="sma_short must be less than sma_long")

        await db.app_config.update_one(
            {"_id": "sma_settings"},
            {"$set": {"sma_short": settings.sma_short, "sma_long": settings.sma_long}},
            upsert=True
        )
        return {"message": "Settings saved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/settings")
async def get_settings():
    """
    Return current configuration. Alpaca API key/secret are ALWAYS masked -
    never returned in plaintext (Phase 1 #2).
    """
    api_key = os.getenv('ALPACA_API_KEY', '')
    secret_key = os.getenv('ALPACA_SECRET_KEY', '')

    masked_api_key = (api_key[:4] + '*' * max(0, len(api_key) - 4)) if api_key else ''
    masked_secret = '*' * 32 if secret_key else ''

    config_doc = await db.app_config.find_one({"_id": "sma_settings"}) or {}

    return {
        "api_key_masked": masked_api_key,
        "has_api_key": bool(api_key),
        "secret_key_masked": masked_secret,
        "has_secret_key": bool(secret_key),
        "base_url": os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'),
        "paper_trading": alpaca_service.paper,
        "sma_short": config_doc.get('sma_short', int(os.getenv('SMA_SHORT', '20'))),
        "sma_long": config_doc.get('sma_long', int(os.getenv('SMA_LONG', '50')))
    }

@api_router.get("/trading-mode")
async def get_trading_mode():
    """Current paper/live trading mode + which account(s) are configured."""
    info = alpaca_service.get_trading_mode_info()
    info["auto_trader_active"] = auto_trader.active
    return info

@api_router.post("/trading-mode")
async def update_trading_mode(body: TradingModeUpdate):
    """
    Switch which real Alpaca account executes orders (paper vs live).
    Switching TO live requires confirm="GO LIVE" (typed by the user in the
    Settings page confirmation modal). Switching back to paper is always
    allowed instantly - it's the safe direction. The auto-trader (unattended
    algo) is force-disabled whenever live mode is entered - it is never
    allowed to place real-money orders on its own.
    """
    current_mode = alpaca_service.trading_mode
    if body.mode == current_mode:
        info = alpaca_service.get_trading_mode_info()
        info["auto_trader_active"] = auto_trader.active
        info["message"] = f"Already in {current_mode.upper()} mode"
        return info

    if body.mode == "live" and body.confirm != "GO LIVE":
        raise HTTPException(status_code=400, detail='Type "GO LIVE" to confirm switching to live trading with real money.')

    try:
        alpaca_service.set_trading_mode(body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.app_config.update_one(
        {"_id": "trading_mode"},
        {"$set": {"mode": body.mode}},
        upsert=True
    )

    if body.mode == "live" and auto_trader.active:
        auto_trader.active = False
        await auto_trader.save_state()
        logger.warning("⛔ Auto-trader force-disabled - switched to LIVE trading mode")

    info = alpaca_service.get_trading_mode_info()
    info["auto_trader_active"] = auto_trader.active
    info["message"] = f"Switched to {body.mode.upper()} trading mode"
    return info

@api_router.get("/news/{symbol}")
async def get_news(symbol: str, limit: int = 5):
    """
    Get recent news for a symbol - Alpaca/Benzinga first (fast, no scraping),
    Google News RSS fallback for illiquid micro-caps Benzinga doesn't cover.
    Same pipeline as the scanner's news check, for consistent results.
    """
    try:
        from services.google_news_service import google_news_service
        from services.scanner_service import scanner_service

        result = await asyncio.to_thread(scanner_service.check_alpaca_news, symbol, 24, limit)
        news_source = 'Benzinga (Alpaca)'

        if not result['has_news']:
            company_name = None
            try:
                asset_info = await asyncio.to_thread(alpaca_service.get_asset, symbol)
                company_name = asset_info.get('name')
            except Exception:
                pass
            result = await asyncio.to_thread(google_news_service.search_stock_news, symbol, 24, limit, company_name)
            news_source = 'Google News'

        return {
            "symbol": symbol,
            "has_news": result['has_news'],
            "articles": result['articles'],
            "news_source": news_source if result['has_news'] else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def auto_trader_loop():
    """
    Real background loop for the auto-trader (Phase 3 #9). Runs unattended
    on an interval, decoupled from the frontend, gated by auto_trader.active.
    /auto-trader/process remains available purely as a manual trigger.
    """
    logger.info("🔁 Auto-Trader background loop started (60s interval)")
    while True:
        try:
            # Defense-in-depth: the unattended algo must NEVER place a real
            # order. auto-trader/toggle + the live-mode switch already force
            # active=False when switching to live, but this extra guard
            # ensures a stray/stale active=True flag can never fire trades
            # if trading_mode somehow flipped without going through that path.
            if auto_trader.active and alpaca_service.trading_mode == "paper":
                criteria = {
                    "min_price": 2,
                    "max_price": 20,
                    "min_change": 10,
                    "min_volume_ratio": 5,
                    "max_float": 20_000_000
                }
                # scan_market() (not scan_stocks() directly) so this 60s loop
                # reuses the same 120s-cached scan the dashboard's own poll
                # already produced instead of always running a duplicate
                # full 128-batch snapshot scan. Entry timing/pricing is
                # unaffected - check_entry_signals() below always fetches
                # fresh live bars per-candidate regardless of scan cache age.
                scanner_results = await asyncio.to_thread(scanner_service.scan_market, criteria)
                # Keep the WebSocket stream fed with every scanner candidate
                # so entry-signal bar checks below have real-time data to
                # merge with the REST fallback chain (fills the free-tier's
                # ~15 min embargo gap right as candidates emerge).
                candidate_symbols = [s.get('symbol') for s in scanner_results if s.get('symbol')]
                if candidate_symbols:
                    await market_data_stream.subscribe(candidate_symbols)
                account = await asyncio.to_thread(alpaca_service.get_account)
                portfolio_value = account.get('portfolio_value', 0)
                await auto_trader.process_scanner_results(scanner_results, portfolio_value)
        except Exception as e:
            logger.error(f"Auto-trader loop error: {str(e)}")
        await asyncio.sleep(60)

app.include_router(auth_router)
app.include_router(ws_router)
app.include_router(api_router)

# CORS (Phase 1 #3): explicit origins only, never '*' with allow_credentials=True
cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
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
    if not os.environ.get('JWT_SECRET') or not os.environ.get('ADMIN_EMAIL') or not os.environ.get('ADMIN_PASSWORD'):
        logger.warning("⚠️  JWT_SECRET/ADMIN_EMAIL/ADMIN_PASSWORD not fully set - login will not work until configured in .env")
    else:
        await seed_user()
        logger.info(f"🔐 Auth seeded for {os.environ.get('ADMIN_EMAIL')}")

    # Restore persisted trading mode (paper/live) - defaults to PAPER if
    # never explicitly set. Live mode is only ever entered by an explicit,
    # confirmed action via POST /trading-mode, never a default.
    try:
        mode_doc = await db.app_config.find_one({"_id": "trading_mode"})
        if mode_doc and mode_doc.get("mode") == "live":
            alpaca_service.set_trading_mode("live")
    except Exception as e:
        logger.error(f"Failed to restore trading mode, defaulting to PAPER: {e}")

    trading_mode = "PAPER (safe/simulated)" if alpaca_service.paper else "🔴 LIVE — REAL MONEY AT RISK"
    logger.info("=" * 60)
    logger.info(f"  MomentumX starting up — TRADING MODE: {trading_mode}")
    logger.info("=" * 60)

    # Restore persisted risk/position state from MongoDB (Phase 3 #10) -
    # never silently reset daily loss limits / stops to defaults on restart.
    await auto_trader.load_state()
    await position_monitor.load_state()

    # Safety net: the unattended algo must never come back active if the
    # trading mode restored to LIVE - force it off and persist that.
    if alpaca_service.trading_mode == "live" and auto_trader.active:
        auto_trader.active = False
        await auto_trader.save_state()
        logger.warning("⛔ Auto-trader force-disabled on startup - trading mode is LIVE")


    position_monitor.start()
    # Start monitoring loop in background
    asyncio.create_task(position_monitor.monitor_positions())
    
    # Start end-of-day closer service
    eod_closer.start()
    asyncio.create_task(eod_closer.monitor_eod())
    logger.info("🚀 Position Monitor Service started")

    # Start the real auto-trader background loop (Phase 3 #9) - runs
    # unattended on the VPS, independent of the frontend/browser being open.
    asyncio.create_task(auto_trader_loop())

    # Start the real-time Alpaca WebSocket market data stream - replaces
    # REST polling (15-min free-tier embargo) for anything actively
    # subscribed. Always uses the LIVE/data key pair regardless of the
    # paper/live trading-mode toggle (see market_data_stream_service.py).
    market_data_stream.start()

    # IMPORTANT: Auto-sync all existing positions to monitoring on startup
    # This ensures stop-loss and take-profit are active for ALL positions
    try:
        existing_positions = await asyncio.to_thread(alpaca_service.get_positions)
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

        # Immediately start streaming live data for any open positions -
        # no need to wait for the auto-trader loop's next scan cycle.
        if existing_positions:
            await market_data_stream.subscribe([p['symbol'] for p in existing_positions])
    except Exception as e:
        logger.error(f"Failed to auto-sync positions on startup: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    position_monitor.stop()
    await market_data_stream.stop()
    eod_closer.stop()
    client.close()
    logger.info("🛑 Services shut down")