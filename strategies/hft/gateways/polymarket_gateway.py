"""
Real Polymarket Gateway - WebSocket order book streaming
"""

import asyncio
import json
from typing import Optional, Callable
from datetime import datetime

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderBookSummary

from ..models import MarketUpdate
from ..logger import get_logger
from shared.polymarket_client import get_client


class PolymarketGateway:
    """
    Real Polymarket order book gateway using py-clob-client.
    
    Streams live order book updates via WebSocket and converts them
    to MarketUpdate objects for the strategy.
    """
    
    def __init__(
        self,
        token_id: str,
        strategy: str = "hft",
        update_interval: float = 0.1  # Poll every 100ms
    ):
        self.token_id = token_id
        self.strategy = strategy
        self.update_interval = update_interval
        
        self.logger = get_logger(f"hft.gateway.polymarket")
        
        # Callback for market updates
        self.on_update: Optional[Callable[[MarketUpdate], None]] = None
        
        # Client (initialized in connect())
        self.client: Optional[ClobClient] = None
        
        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Metrics
        self._update_count = 0
        self._last_update: Optional[datetime] = None
    
    async def connect(self):
        """Initialize connection to Polymarket CLOB"""
        try:
            # Use shared client wrapper
            self.client = get_client(self.strategy)
            
            # Test connection by fetching initial orderbook
            book = self.client.get_order_book(self.token_id)
            
            self.logger.info("POLY_CONNECTED", {
                "token_id": self.token_id,
                "has_bids": len(book.bids) if book and book.bids else 0,
                "has_asks": len(book.asks) if book and book.asks else 0,
            })

            # ✅ FIX: Send this initial data to the strategy immediately
            if book and (book.bids or book.asks) and self.on_update:
                update = self._convert_orderbook(book)
                await self.on_update(update)
            
        except Exception as e:
            self.logger.error("POLY_CONNECT_FAILED", {
                "token_id": self.token_id,
                "error": str(e)
            })
            raise
    
    async def run(self):
        """Main loop - poll orderbook and emit updates"""
        self._running = True
        
        self.logger.info("POLY_GATEWAY_STARTED", {
            "token_id": self.token_id,
            "interval": self.update_interval
        })
        
        while self._running:
            try:
                # Fetch current order book (synchronous call)
                loop = asyncio.get_event_loop()
                book = await loop.run_in_executor(
                    None,
                    self.client.get_order_book,
                    self.token_id
                )
                
                if book and (book.bids or book.asks):
                    # Convert to MarketUpdate
                    update = self._convert_orderbook(book)
                    
                    # Track metrics
                    self._update_count += 1
                    self._last_update = datetime.utcnow()
                    
                    # Emit to callback
                    if self.on_update:
                        await self.on_update(update)
                    
                    # Log periodically
                    if self._update_count % 100 == 0:
                        self.logger.info("POLY_HEARTBEAT", {
                            "count": self._update_count,
                            "mid": update.order_book.mid_price,
                            "spread_pct": update.order_book.spread_pct,
                        })
                
                else:
                    self.logger.warning("POLY_EMPTY_BOOK", {
                        "token_id": self.token_id
                    })
                
                # Wait before next poll
                await asyncio.sleep(self.update_interval)
                
            except Exception as e:
                self.logger.error("POLY_UPDATE_ERROR", {
                    "error": str(e),
                    "count": self._update_count
                })
                # Don't crash on transient errors
                await asyncio.sleep(1.0)
    
    def _convert_orderbook(self, book: OrderBookSummary) -> MarketUpdate:
        """
        Convert py-clob-client OrderBookSummary to our MarketUpdate model.
        """
        timestamp = datetime.utcnow()
        
        # ✅ FIX: Explicitly sort to guarantee Top of Book
        # Bids: Highest price is best (Reverse sort)
        sorted_bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True) if book.bids else []
        
        # Asks: Lowest price is best (Normal sort)
        sorted_asks = sorted(book.asks, key=lambda x: float(x.price)) if book.asks else []
        
        # Extract best bid/ask
        best_bid = float(sorted_bids[0].price) if sorted_bids else 0.0
        best_ask = float(sorted_asks[0].price) if sorted_asks else 1.0

        # ✅ DEBUG: Log the raw values to see why mid_price is 0.5
        # (You can remove this later once verified)
        if self._update_count % 10 == 0:  # Log every 10th update to avoid spam
             self.logger.info("DEBUG_PRICES", {
                "raw_bid_0": book.bids[0].price if book.bids else "None",
                "sorted_bid_0": sorted_bids[0].price if sorted_bids else "None",
                "parsed_bid": best_bid,
                "parsed_ask": best_ask
            })
        
        # Calculate mid price
        if best_bid > 0 and best_ask < 1:
            mid_price = (best_bid + best_ask) / 2
        elif best_bid > 0:
            mid_price = best_bid
        elif best_ask < 1:
            mid_price = best_ask
        else:
            mid_price = 0.5  # Fallback
        
        # Calculate spread percentage
        spread_pct = ((best_ask - best_bid) / mid_price) if mid_price > 0 else 0
        
        # Convert full book depth to dictionaries
        bids = [
            {"price": float(level.price), "size": float(level.size)}
            for level in sorted_bids[:10]  # ✅ FIX: Use sorted_bids
        ] if sorted_bids else []
        
        asks = [
            {"price": float(level.price), "size": float(level.size)}
            for level in sorted_asks[:10]  # ✅ FIX: Use sorted_asks
        ] if sorted_asks else []
        
        # Construct the nested OrderBook structure
        order_book_data = {
            "token_id": self.token_id,  # ✅ ADDED: Required by OrderBook model
            "mid_price": mid_price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": spread_pct,
            "bids": bids,
            "asks": asks
        }
        
        return MarketUpdate(
            timestamp=timestamp,
            token_id=self.token_id,
            order_book=order_book_data
        )
    
    async def disconnect(self):
        """Stop the gateway"""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("POLY_DISCONNECTED", {
            "total_updates": self._update_count,
            "last_update": self._last_update.isoformat() if self._last_update else None
        })