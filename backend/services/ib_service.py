"""
Interactive Brokers API Integration Service

Provides:
- Fundamental data (float, shares outstanding)
- Real-time market data
- Order execution for live trading
"""

import os
import time
import logging
import threading
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

logger = logging.getLogger(__name__)


class IBClient(EWrapper, EClient):
    """Interactive Brokers API Client with EWrapper callbacks"""
    
    def __init__(self):
        EClient.__init__(self, self)
        
        # Storage for responses
        self.fundamental_data = {}
        self.next_order_id = None
        self.is_connected = False
        
        # Threading
        self.lock = threading.Lock()
        
    def error(self, reqId: int, errorCode: int, errorString: str):
        """Error callback"""
        logger.error(f"IB Error - ReqId: {reqId}, Code: {errorCode}, Msg: {errorString}")
        
    def nextValidId(self, orderId: int):
        """Callback when connection established"""
        super().nextValidId(orderId)
        self.next_order_id = orderId
        self.is_connected = True
        logger.info(f"IB Connection established. Next Order ID: {orderId}")
        
    def fundamentalData(self, reqId: int, data: str):
        """Callback for fundamental data"""
        with self.lock:
            self.fundamental_data[reqId] = data
        logger.info(f"Received fundamental data for reqId: {reqId}")


class IBService:
    """
    Interactive Brokers Service
    
    Manages connection to IB Gateway/TWS and provides:
    - Float/shares outstanding data
    - Market data
    - Order execution
    """
    
    def __init__(self):
        self.client = None
        self.api_thread = None
        self.request_counter = 0
        self.float_cache = {}  # Cache float data {symbol: {data, timestamp}}
        self.cache_duration = timedelta(days=7)  # Refresh weekly
        
        # IB Connection settings from environment
        self.ib_host = os.getenv('IB_GATEWAY_HOST', '127.0.0.1')
        self.ib_port = int(os.getenv('IB_GATEWAY_PORT', '7497'))  # 7497=TWS Paper, 7496=TWS Live
        self.ib_client_id = int(os.getenv('IB_CLIENT_ID', '1'))
        
        # Feature flags
        self.use_ib_for_float = os.getenv('USE_IB_FLOAT', 'false').lower() == 'true'
        
    def connect(self) -> bool:
        """Connect to IB Gateway/TWS"""
        try:
            if self.client and self.client.is_connected:
                logger.info("Already connected to IB")
                return True
                
            logger.info(f"Connecting to IB Gateway at {self.ib_host}:{self.ib_port}...")
            
            self.client = IBClient()
            self.client.connect(self.ib_host, self.ib_port, self.ib_client_id)
            
            # Start the client thread
            self.api_thread = threading.Thread(target=self.client.run, daemon=True)
            self.api_thread.start()
            
            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.client.is_connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)
                
            if self.client.is_connected:
                logger.info("✅ Successfully connected to IB Gateway")
                return True
            else:
                logger.error("Failed to connect to IB Gateway (timeout)")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to IB: {str(e)}")
            return False
            
    def disconnect(self):
        """Disconnect from IB Gateway"""
        if self.client:
            self.client.disconnect()
            self.client = None
            logger.info("Disconnected from IB Gateway")
            
    def get_float_data(self, symbol: str) -> Optional[Dict]:
        """
        Get float and shares outstanding data for a symbol
        
        Returns:
        {
            "symbol": "AAPL",
            "float_shares": 15000000000,
            "shares_outstanding": 16000000000,
            "free_float_pct": 93.75,
            "data_date": "2025-01-15",
            "source": "IB"
        }
        """
        try:
            # Check cache first
            if symbol in self.float_cache:
                cached = self.float_cache[symbol]
                if datetime.now() - cached['timestamp'] < self.cache_duration:
                    logger.debug(f"Using cached float data for {symbol}")
                    return cached['data']
            
            # Ensure connected
            if not self.client or not self.client.is_connected:
                if not self.connect():
                    logger.error(f"Cannot get float data for {symbol}: Not connected to IB")
                    return None
            
            # Create contract
            contract = Contract()
            contract.symbol = symbol
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            
            # Request fundamental data
            req_id = self._get_next_request_id()
            self.client.reqFundamentalData(req_id, contract, "ReportSnapshot", [])
            
            # Wait for response (max 10 seconds)
            timeout = 10
            start_time = time.time()
            while req_id not in self.client.fundamental_data and (time.time() - start_time) < timeout:
                time.sleep(0.1)
                
            if req_id not in self.client.fundamental_data:
                logger.warning(f"Timeout waiting for float data for {symbol}")
                return None
                
            # Parse XML response
            xml_data = self.client.fundamental_data[req_id]
            float_data = self._parse_fundamental_xml(symbol, xml_data)
            
            # Cache the result
            if float_data:
                self.float_cache[symbol] = {
                    'data': float_data,
                    'timestamp': datetime.now()
                }
                
            return float_data
            
        except Exception as e:
            logger.error(f"Error getting float data for {symbol}: {str(e)}")
            return None
            
    def _parse_fundamental_xml(self, symbol: str, xml_data: str) -> Optional[Dict]:
        """
        Parse IB fundamental data XML to extract float and shares outstanding
        
        Example XML structure:
        <ReportSnapshot>
            <Fundamentals>
                <SharesOutstanding>16000000000</SharesOutstanding>
                <SharesFloat>15000000000</SharesFloat>
            </Fundamentals>
        </ReportSnapshot>
        """
        try:
            root = ET.fromstring(xml_data)
            
            # Extract shares outstanding
            shares_outstanding_elem = root.find('.//SharesOutstanding')
            shares_float_elem = root.find('.//SharesFloat') or root.find('.//FloatShares')
            
            if not shares_outstanding_elem:
                logger.warning(f"SharesOutstanding not found in XML for {symbol}")
                return None
                
            shares_outstanding = float(shares_outstanding_elem.text)
            
            # Float might not always be available
            if shares_float_elem is not None:
                shares_float = float(shares_float_elem.text)
            else:
                # Estimate float as ~90% of outstanding (conservative estimate)
                shares_float = shares_outstanding * 0.90
                logger.info(f"Float not found for {symbol}, estimated as 90% of outstanding")
            
            # Calculate free float percentage
            free_float_pct = (shares_float / shares_outstanding * 100) if shares_outstanding > 0 else 0
            
            return {
                "symbol": symbol,
                "float_shares": int(shares_float),
                "shares_outstanding": int(shares_outstanding),
                "free_float_pct": round(free_float_pct, 2),
                "data_date": datetime.now().strftime("%Y-%m-%d"),
                "source": "IB"
            }
            
        except Exception as e:
            logger.error(f"Error parsing fundamental XML for {symbol}: {str(e)}")
            return None
            
    def get_batch_float_data(self, symbols: List[str], max_concurrent: int = 10) -> Dict[str, Dict]:
        """
        Get float data for multiple symbols
        
        Args:
            symbols: List of stock symbols
            max_concurrent: Max number of concurrent requests to IB
            
        Returns:
            Dict mapping symbol to float data
        """
        results = {}
        
        # Process in batches to avoid overwhelming IB
        for i in range(0, len(symbols), max_concurrent):
            batch = symbols[i:i + max_concurrent]
            logger.info(f"Fetching float data for batch {i//max_concurrent + 1} ({len(batch)} symbols)")
            
            for symbol in batch:
                float_data = self.get_float_data(symbol)
                if float_data:
                    results[symbol] = float_data
                    
                # Small delay between requests
                time.sleep(0.1)
                
        logger.info(f"Retrieved float data for {len(results)}/{len(symbols)} symbols")
        return results
        
    def _get_next_request_id(self) -> int:
        """Get next request ID"""
        self.request_counter += 1
        return self.request_counter
        
    def clear_cache(self):
        """Clear the float data cache"""
        self.float_cache = {}
        logger.info("Float data cache cleared")
        
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "cached_symbols": len(self.float_cache),
            "cache_duration_days": self.cache_duration.days,
            "symbols": list(self.float_cache.keys())
        }


# Global instance
ib_service = IBService()


def get_float_for_symbol(symbol: str) -> Optional[Dict]:
    """
    Convenience function to get float data for a symbol
    
    Usage:
        float_data = get_float_for_symbol("AAPL")
        if float_data:
            print(f"Float: {float_data['float_shares']:,}")
    """
    if not ib_service.use_ib_for_float:
        logger.warning("IB float data disabled. Set USE_IB_FLOAT=true in .env")
        return None
        
    return ib_service.get_float_data(symbol)
