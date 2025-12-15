"""
Mock gateways for testing without live data

Simulates Polymarket and Binance WebSocket feeds.
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Callable, Optional

from ..models import MarketUpdate, OracleUpdate, OrderBook, OrderBookLevel


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
    
    def _generate_order_book(self) -> OrderBook:
        """Generate a realistic order book around current mid price"""
        # Random walk for mid price
        change = random.gauss(0, self.volatility)
        self.mid_price = max(0.01, min(0.99, self.mid_price + change))
        
        # Generate spread (1-5%)
        spread_pct = random.uniform(0.01, 0.05)
        half_spread = self.mid_price * spread_pct / 2
        
        best_bid = self.mid_price - half_spread
        best_ask = self.mid_price + half_spread
        
        # Generate order book levels
        bids = []
        asks = []
        
        for i in range(5):
            bid_price = best_bid - (i * 0.005)
            ask_price = best_ask + (i * 0.005)
            bid_size = random.uniform(100, 1000)
            ask_size = random.uniform(100, 1000)
            
            bids.append(OrderBookLevel(price=round(bid_price, 4), size=round(bid_size, 2)))
            asks.append(OrderBookLevel(price=round(ask_price, 4), size=round(ask_size, 2)))
        
        return OrderBook(
            token_id=self.token_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.utcnow()
        )
    
    async def connect(self):
        """Start the mock feed"""
        self.is_running = True
    
    async def disconnect(self):
        """Stop the mock feed"""
        self.is_running = False
    
    async def run(self):
        """Main loop emitting mock market updates"""
        while self.is_running:
            order_book = self._generate_order_book()
            update = MarketUpdate(
                token_id=self.token_id,
                order_book=order_book,
                timestamp=datetime.utcnow()
            )
            
            if self.on_update:
                self.on_update(update)
            
            await asyncio.sleep(self.update_interval)


class MockBinanceGateway:
    """
    Mock Binance WebSocket gateway.
    
    Simulates BTC/ETH/XRP price feeds with realistic movements.
    """
    
    INITIAL_PRICES = {
        "BTCUSDT": 104000.0,
        "ETHUSDT": 3900.0,
        "XRPUSDT": 2.40
    }
    
    VOLATILITIES = {
        "BTCUSDT": 50.0,  # $50 per tick
        "ETHUSDT": 5.0,   # $5 per tick
        "XRPUSDT": 0.01   # $0.01 per tick
    }
    
    def __init__(
        self,
        assets: list[str] = None,
        update_interval: float = 0.1
    ):
        self.assets = assets or ["BTCUSDT"]
        self.prices = {asset: self.INITIAL_PRICES.get(asset, 100.0) for asset in self.assets}
        self.update_interval = update_interval
        self.is_running = False
        self.on_update: Optional[Callable[[OracleUpdate], None]] = None
    
    async def connect(self):
        """Start the mock feed"""
        self.is_running = True
    
    async def disconnect(self):
        """Stop the mock feed"""
        self.is_running = False
    
    async def run(self):
        """Main loop emitting mock oracle updates"""
        while self.is_running:
            for asset in self.assets:
                volatility = self.VOLATILITIES.get(asset, 1.0)
                change = random.gauss(0, volatility)
                self.prices[asset] = max(0.01, self.prices[asset] + change)
                
                update = OracleUpdate(
                    asset=asset,
                    price=round(self.prices[asset], 2),
                    timestamp=datetime.utcnow()
                )
                
                if self.on_update:
                    self.on_update(update)
            
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