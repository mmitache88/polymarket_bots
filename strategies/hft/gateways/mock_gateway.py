"""
Mock gateways for testing without live data

Simulates Polymarket and Binance WebSocket feeds.
"""

import asyncio
import random
from datetime import datetime
from typing import Callable, Optional

from ..models import MarketUpdate, OracleUpdate, OrderBook, OrderBookLevel
from ..logger import get_logger

logger = get_logger(__name__)


class MockPolymarketGateway:
    """
    Mock Polymarket WebSocket gateway.
    
    Simulates order book updates with realistic price movements.
    """
    
    def __init__(
        self,
        token_id: str,
        initial_mid: float = 0.50,
        volatility: float = 0.02,
        update_interval: float = 0.5
    ):
        self.token_id = token_id
        self.mid_price = initial_mid
        self.volatility = volatility
        self.update_interval = update_interval
        self.is_running = False
        self.on_update: Optional[Callable[[MarketUpdate], None]] = None
    
    async def connect(self):
        """Connect to mock feed"""
        logger.info("MOCK_POLY_CONNECT", {"token_id": self.token_id})
        self.is_running = True
    
    async def disconnect(self):
        """Disconnect from mock feed"""
        logger.info("MOCK_POLY_DISCONNECT")
        self.is_running = False
    
    async def run(self):
        """Generate mock market updates"""
        logger.info("MOCK_POLY_RUN_START", {"is_running": self.is_running})
        
        update_count = 0
        while self.is_running:
            update_count += 1
            
            # Simulate price movement (random walk)
            change = random.gauss(0, self.volatility)
            self.mid_price = max(0.01, min(0.99, self.mid_price + change))
            
            # Build order book
            spread = random.uniform(0.01, 0.03)
            half_spread = spread / 2
            
            order_book = OrderBook(
                token_id=self.token_id,
                bids=[
                    OrderBookLevel(price=self.mid_price - half_spread, size=random.uniform(100, 500)),
                    OrderBookLevel(price=self.mid_price - half_spread - 0.01, size=random.uniform(200, 800)),
                ],
                asks=[
                    OrderBookLevel(price=self.mid_price + half_spread, size=random.uniform(100, 500)),
                    OrderBookLevel(price=self.mid_price + half_spread + 0.01, size=random.uniform(200, 800)),
                ],
                timestamp=datetime.utcnow()
            )
            
            update = MarketUpdate(
                token_id=self.token_id,
                order_book=order_book,
                timestamp=datetime.utcnow()
            )
            
            # Log every 10th update
            if update_count % 10 == 1:
                logger.info("MOCK_MARKET_UPDATE", {
                    "count": update_count,
                    "mid": round(self.mid_price, 4),
                    "has_callback": self.on_update is not None
                })
            
            # Call the callback if set
            if self.on_update:
                self.on_update(update)
            
            await asyncio.sleep(self.update_interval)


class MockBinanceGateway:
    """
    Mock Binance WebSocket gateway.
    
    Simulates price updates for BTC, ETH, XRP.
    """
    
    def __init__(
        self,
        assets: list = None,
        update_interval: float = 0.2
    ):
        self.assets = assets or ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
        self.update_interval = update_interval
        self.is_running = False
        self.on_update: Optional[Callable[[OracleUpdate], None]] = None
        
        # Initial prices
        self.prices = {
            "BTCUSDT": 104500.0,
            "ETHUSDT": 3900.0,
            "XRPUSDT": 2.35
        }
        
        # Volatility per asset
        self.volatility = {
            "BTCUSDT": 50.0,
            "ETHUSDT": 5.0,
            "XRPUSDT": 0.01
        }
    
    async def connect(self):
        """Connect to mock feed"""
        logger.info("MOCK_BINANCE_CONNECT", {"assets": self.assets})
        self.is_running = True
    
    async def disconnect(self):
        """Disconnect from mock feed"""
        logger.info("MOCK_BINANCE_DISCONNECT")
        self.is_running = False
    
    async def run(self):
        """Generate mock price updates"""
        logger.info("MOCK_BINANCE_RUN_START", {"is_running": self.is_running})
        
        update_count = 0
        while self.is_running:
            update_count += 1
            
            # Update each asset
            for asset in self.assets:
                if asset not in self.prices:
                    continue
                
                # Random walk
                vol = self.volatility.get(asset, 1.0)
                change = random.gauss(0, vol)
                self.prices[asset] = max(0.01, self.prices[asset] + change)
                
                update = OracleUpdate(
                    asset=asset,
                    price=self.prices[asset],
                    timestamp=datetime.utcnow()
                )
                
                # Call the callback if set
                if self.on_update:
                    self.on_update(update)
            
            # Log every 50th update
            if update_count % 50 == 1:
                logger.info("MOCK_ORACLE_UPDATE", {
                    "count": update_count,
                    "prices": {k: round(v, 2) for k, v in self.prices.items()},
                    "has_callback": self.on_update is not None
                })
            
            await asyncio.sleep(self.update_interval)


class MockMarketInfo:
    """Provides mock market metadata"""
    
    @staticmethod
    def get_market_info(token_id: str) -> dict:
        """Return mock market info"""
        return {
            "token_id": token_id,
            "condition_id": f"condition_{token_id[:8]}",
            "question": "Will BTC be above $104,000 at 12:00 UTC?",
            "outcome": "YES",
            "end_date": (datetime.utcnow() + timedelta(minutes=55)).isoformat(),
            "market_slug": "btc-104000-12pm"
        }