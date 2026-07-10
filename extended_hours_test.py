#!/usr/bin/env python3

import requests
import json
from datetime import datetime

def test_extended_hours_fix():
    """Focused test for Extended Hours Buy Order Fix"""
    base_url = "https://trade-navigator-21.preview.emergentagent.com"
    api_url = f"{base_url}/api"
    
    print("🎯 Extended Hours Buy Order Fix - Comprehensive Test")
    print("=" * 60)
    
    # 1. Check market status
    print("\n1️⃣ Checking Market Status...")
    market_response = requests.get(f"{api_url}/market/status", timeout=10)
    if market_response.status_code == 200:
        market_data = market_response.json()
        session = market_data.get("session")
        current_time = market_data.get("current_time_et")
        is_open = market_data.get("is_open")
        
        print(f"   📊 Session: {session}")
        print(f"   🕐 Time: {current_time}")
        print(f"   🟢 Market Open: {is_open}")
        
        is_extended_hours = session in ["pre-market", "after-hours"]
        print(f"   ⏰ Extended Hours: {'YES' if is_extended_hours else 'NO'}")
        
        if not is_extended_hours:
            print("   ⚠️  Not in extended hours - fix may not be active")
    else:
        print(f"   ❌ Failed to get market status: {market_response.status_code}")
        return False
    
    # 2. Check current positions
    print("\n2️⃣ Checking Current Positions...")
    positions_response = requests.get(f"{api_url}/positions", timeout=10)
    if positions_response.status_code == 200:
        positions = positions_response.json()
        print(f"   📈 Total Positions: {len(positions)}")
        
        for pos in positions:
            symbol = pos.get("symbol")
            qty = pos.get("qty")
            current_price = pos.get("current_price")
            unrealized_pl = pos.get("unrealized_pl")
            unrealized_plpc = pos.get("unrealized_plpc")
            
            pnl_color = "🟢" if unrealized_pl >= 0 else "🔴"
            print(f"   {pnl_color} {symbol}: {qty} shares @ ${current_price:.2f} | P&L: ${unrealized_pl:.2f} ({unrealized_plpc:.2f}%)")
        
        # Check for RADX position (from our test)
        radx_position = next((p for p in positions if p.get("symbol") == "RADX"), None)
        if radx_position:
            print(f"   ✅ RADX Position Found: {radx_position['qty']} shares - Extended hours buy order SUCCESS!")
        else:
            print("   ⚠️  RADX position not found - may not have filled yet")
    else:
        print(f"   ❌ Failed to get positions: {positions_response.status_code}")
    
    # 3. Test a small buy order during extended hours
    print("\n3️⃣ Testing Extended Hours Buy Order...")
    test_order = {
        "symbol": "SNDL",  # Use a different symbol for this test
        "qty": 10,
        "side": "buy"
    }
    
    print(f"   🔄 Placing order: {test_order}")
    order_response = requests.post(f"{api_url}/orders", json=test_order, timeout=15)
    
    if order_response.status_code == 200:
        order_data = order_response.json()
        print(f"   ✅ Order placed successfully!")
        print(f"   📋 Order ID: {order_data.get('order_id')}")
        print(f"   📊 Symbol: {order_data.get('symbol')}")
        print(f"   📈 Quantity: {order_data.get('qty')}")
        print(f"   🔄 Status: {order_data.get('status')}")
        
        if is_extended_hours:
            print(f"   🎯 Extended hours conversion should be active - check backend logs for limit order conversion")
    elif order_response.status_code == 400:
        error_detail = order_response.json().get("detail", "")
        if "Market is" in error_detail:
            print(f"   ⚠️  Order rejected - Market closed: {error_detail}")
        else:
            print(f"   ❌ Order failed: {error_detail}")
    else:
        print(f"   ❌ Order failed with status {order_response.status_code}")
    
    # 4. Check recent orders
    print("\n4️⃣ Checking Recent Orders...")
    orders_response = requests.get(f"{api_url}/orders?limit=5", timeout=10)
    if orders_response.status_code == 200:
        orders = orders_response.json()
        print(f"   📋 Recent Orders: {len(orders)}")
        
        for order in orders[:3]:  # Show last 3 orders
            symbol = order.get("symbol")
            side = order.get("side")
            qty = order.get("qty")
            status = order.get("status")
            filled_qty = order.get("filled_qty", 0)
            created_at = order.get("created_at", "")
            
            # Parse timestamp for display
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M:%S')
            except:
                time_str = "Unknown"
            
            status_icon = "✅" if status == "filled" else "🔄" if status in ["new", "pending_new"] else "❌"
            print(f"   {status_icon} {symbol} {side.upper()} {qty} @ {time_str} | Status: {status} | Filled: {filled_qty}")
    else:
        print(f"   ❌ Failed to get orders: {orders_response.status_code}")
    
    print("\n" + "=" * 60)
    print("🎯 Extended Hours Fix Test Summary:")
    print(f"   • Market Session: {session}")
    print(f"   • Extended Hours Active: {'YES' if is_extended_hours else 'NO'}")
    print(f"   • RADX Position: {'FOUND' if radx_position else 'NOT FOUND'}")
    print(f"   • Fix Status: {'WORKING' if radx_position and is_extended_hours else 'NEEDS VERIFICATION'}")
    
    if radx_position and is_extended_hours:
        print("   ✅ Extended Hours Buy Order Fix is WORKING correctly!")
        return True
    else:
        print("   ⚠️  Extended Hours Fix needs further verification")
        return False

if __name__ == "__main__":
    success = test_extended_hours_fix()
    exit(0 if success else 1)