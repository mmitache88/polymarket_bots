"""
Mock gateways for testing without live data

Simulates Polymarket and Binance WebSocket feeds.
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, List, Any  # ✅ Added List, Any

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
                timestamp=datetime.now(timezone.utc) # ✅ FIX: Use aware datetime
            )
            
            update = MarketUpdate(
                token_id=self.token_id,
                order_book=order_book,
                timestamp=datetime.now(timezone.utc) # ✅ FIX: Use aware datetime
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
                if asyncio.iscoroutinefunction(self.on_update):
                    await self.on_update(update)
                else:
                    self.on_update(update)
            
            await asyncio.sleep(self.update_interval)


class MockBinanceGateway:
    """
    Simulates a Binance Oracle by generating random price walks.
    Useful for testing strategy logic without needing API keys.
    """
    
    def __init__(
        self,
        assets: List[str] = None,
        update_interval: float = 1.0,
        volatility: float = 0.0001
    ):
        self.assets = assets or ["BTCUSDT"]
        self.update_interval = update_interval
        self.volatility = volatility
        self.logger = get_logger("strategies.hft.gateways.mock_gateway")
        
        # ✅ FIX: Iterate over self.assets (not assets, which could be None)
        self.prices = {}
        for asset in self.assets:
            if "BTC" in asset:
                self.prices[asset] = 104500.0
            else:
                self.prices[asset] = 1.0
        
        self.on_update: None
        self._running = False
        self._update_count = 0
        self.logger = get_logger("strategies.hft.gateways.mock_gateway")

    async def connect(self):
        """Mock connection"""
        self.logger.info("MOCK_BINANCE_CONNECT", {"assets": self.assets})
        await asyncio.sleep(0.1)

    async def run(self):
        """Start generating mock updates"""
        self._running = True
        self.logger.info("MOCK_BINANCE_RUN_START", {"is_running": self._running})
        
        while self._running:
            try:
                # Update prices with random walk
                for asset in self.assets:
                    change_pct = random.gauss(0, self.volatility)
                    self.prices[asset] *= (1 + change_pct)
                
                self._update_count += 1
                
                # Create update object
                primary_asset = self.assets[0]
                update = OracleUpdate(
                    timestamp=datetime.now(timezone.utc), # ✅ FIX: Use aware datetime
                    asset=primary_asset,
                    price=self.prices[primary_asset]
                )
                
                if self._update_count % 5 == 0: # Log every 5th to reduce noise
                    self.logger.info("MOCK_ORACLE_UPDATE", {
                        "count": self._update_count,
                        "prices": {k: round(v, 2) for k, v in self.prices.items()}
                    })
                
                if self.on_update:
                    if asyncio.iscoroutinefunction(self.on_update):
                        await self.on_update(update)
                    else:
                        self.on_update(update)
                
                await asyncio.sleep(self.update_interval)
                
            except Exception as e:
                self.logger.error("MOCK_ORACLE_ERROR", {"error": str(e)})
                await asyncio.sleep(1.0)

    async def disconnect(self):  # ✅ FIX: Changed 'sync def' to 'async def'
        """Stop the gateway"""
        self._running = False
        self.logger.info("MOCK_BINANCE_DISCONNECT")


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
            "end_date": (datetime.now(timezone.utc) + timedelta(minutes=55)).isoformat(), # ✅ FIX: Use aware datetime
            "market_slug": "btc-104000-12pm"
        }