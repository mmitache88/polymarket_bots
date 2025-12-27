"""
Polymarket WebSocket Gateway - Real-time order book streaming
"""

import asyncio
import json
import websockets
from typing import Optional, Callable
from datetime import datetime, timezone

from ..models import MarketUpdate, OrderBook, OrderBookLevel
from ..logger import get_logger


class PolymarketWebSocketGateway:
    """
    WebSocket-based market data gateway for Polymarket.
    Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self, token_id: str):
        self.token_id = token_id
        self.logger = get_logger("hft.gateway.polymarket_ws")
        
        # Callback for market updates
        self.on_update: Optional[Callable[[MarketUpdate], None]] = None
        
        # WebSocket state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Metrics
        self._message_count = 0
        self._book_update_count = 0
        self._last_update: Optional[datetime] = None
    
    async def connect(self):
        """Establish WebSocket connection and subscribe to token"""
        try:
            self._ws = await websockets.connect(self.WS_URL)
            
            # ✅ FIXED: Correct subscription payload (based on test_poly_ws.py)
            subscribe_payload = {
                "assets_ids": [self.token_id],
                "type": "market"
            }
            
            await self._ws.send(json.dumps(subscribe_payload))
            
            self.logger.info("POLY_WS_CONNECTED", {
                "token_id": self.token_id,
                "url": self.WS_URL,
                "payload": subscribe_payload
            })
            
        except Exception as e:
            self.logger.error("POLY_WS_CONNECT_FAILED", {
                "error": str(e),
                "token_id": self.token_id
            })
            raise
    
    async def run(self):
        """Main message loop - process incoming WebSocket messages"""
        self._running = True
        
        self.logger.info("POLY_WS_STARTED", {"token_id": self.token_id})
        
        try:
            while self._running and self._ws:
                # ✅ ADDED: Timeout protection (30 seconds)
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                    self._message_count += 1
                    
                    # Parse JSON
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        self.logger.warning("POLY_WS_INVALID_JSON", {"raw": message[:100]})
                        continue
                    
                    # ✅ CRITICAL FIX: Handle BATCHES (arrays) vs single events
                    events = data if isinstance(data, list) else [data]
                    
                    # ✅ Log first 5 raw messages for debugging
                    if self._message_count <= 5:
                        self.logger.info("POLY_WS_RAW_MESSAGE", {
                            "count": self._message_count,
                            "is_batch": isinstance(data, list),
                            "num_events": len(events),
                            "sample": str(data)[:300]
                        })
                    
                    # Process each event in the batch
                    for event in events:
                        # ✅ FIXED: Detect event type by checking fields
                        # Order book updates have 'bids' and 'asks' fields
                        if "bids" in event and "asks" in event:
                            await self._handle_book_update(event)
                        
                        # Price change events have 'price_changes' field
                        elif "price_changes" in event:
                            await self._handle_price_change(event)
                        
                        # Last trade price events have 'last_trade_price' field
                        elif "last_trade_price" in event:
                            pass  # Optional: log for debugging
                        
                        else:
                            # Unknown event - log first occurrence
                            if self._message_count <= 10:
                                self.logger.debug("POLY_WS_UNKNOWN_EVENT", {
                                    "fields": list(event.keys()),
                                    "sample": str(event)[:200]
                                })
                    
                    # Heartbeat logging
                    if self._book_update_count % 100 == 0 and self._book_update_count > 0:
                        self.logger.info("POLY_WS_HEARTBEAT", {
                            "book_updates": self._book_update_count,
                            "total_messages": self._message_count
                        })
                
                except asyncio.TimeoutError:
                    # No message for 30 seconds - log warning but continue
                    self.logger.warning("POLY_WS_TIMEOUT", {
                        "seconds": 30,
                        "last_book_update": self._book_update_count
                    })
                    continue
        
        except websockets.exceptions.ConnectionClosed as e:
            # ✅ Log close code and reason
            self.logger.warning("POLY_WS_CONNECTION_CLOSED", {
                "clean_close": e.code == 1000,
                "code": e.code,
                "reason": e.reason or "No reason provided"
            })
        
        except Exception as e:
            self.logger.error("POLY_WS_ERROR", {
                "error": str(e),
                "type": type(e).__name__
            })
            raise
    
    async def _handle_book_update(self, data: dict):
        """
        Process full order book update.
        
        Expected structure:
        {
            "asset_id": "67704...",
            "market": "0x456...",
            "timestamp": "1234567890",
            "bids": [{"price": "0.45", "size": "100.0"}, ...],
            "asks": [{"price": "0.46", "size": "50.0"}, ...]
        }
        """
        try:
            # ✅ CRITICAL FIX: Only process updates for OUR token
            asset_id = data.get("asset_id")
            if asset_id != self.token_id:
                # This is the OTHER side (NO token if we're trading YES)
                return
            
            # Extract order book data
            raw_bids = data.get("bids", [])
            raw_asks = data.get("asks", [])
            
            # ✅ CRITICAL FIX: SORT the order book
            # Bids: Highest price first (descending)
            sorted_bids = sorted(
                raw_bids,
                key=lambda x: float(x["price"]),
                reverse=True
            )
            
            # Asks: Lowest price first (ascending)
            sorted_asks = sorted(
                raw_asks,
                key=lambda x: float(x["price"])
            )
            
            # ✅ Log first book update structure (AFTER sorting)
            if self._book_update_count == 0:
                self.logger.info("POLY_WS_FIRST_BOOK", {
                    "asset_id": asset_id,
                    "token_id": self.token_id,
                    "num_bids": len(sorted_bids),
                    "num_asks": len(sorted_asks),
                    "sample_bid": sorted_bids[0] if sorted_bids else None,  # ✅ Now this is the BEST bid
                    "sample_ask": sorted_asks[0] if sorted_asks else None   # ✅ Now this is the BEST ask
                })
            
            # Convert to OrderBookLevel objects (use SORTED data)
            bids = [
                OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in sorted_bids[:10]  # ✅ Top 10 BEST bids
            ]
            
            asks = [
                OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in sorted_asks[:10]  # ✅ Top 10 BEST asks
            ]
            
            # Skip if empty book
            if not bids or not asks:
                self.logger.warning("POLY_WS_EMPTY_BOOK", {
                    "has_bids": len(bids),
                    "has_asks": len(asks)
                })
                return
            
            # Create OrderBook (Pydantic model will validate)
            order_book = OrderBook(bids=bids, asks=asks)
            
            # Build MarketUpdate
            update = MarketUpdate(
                token_id=self.token_id,
                order_book=order_book,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Track metrics
            self._book_update_count += 1
            self._last_update = update.timestamp
            
            # Emit to callback
            if self.on_update:
                await self.on_update(update)
            
            # Debug log every 10th update
            if self._book_update_count % 10 == 0:
                self.logger.debug("POLY_WS_BOOK", {
                    "bid": order_book.best_bid,
                    "ask": order_book.best_ask,
                    "mid": order_book.mid_price,
                    "spread_bps": order_book.spread_pct * 10000
                })
        
        except KeyError as e:
            self.logger.error("POLY_WS_BOOK_MISSING_FIELD", {
                "error": str(e),
                "sample": str(data)[:200]
            })
        
        except Exception as e:
            self.logger.error("POLY_WS_BOOK_PARSE_ERROR", {
                "error": str(e),
                "type": type(e).__name__,
                "sample": str(data)[:200]
            })
    
    async def _handle_price_change(self, data: dict):
        """
        Handle price change event (may not have full book).
        If you need full book, wait for 'book' event instead.
        """
        # Optional: log price changes for debugging
        if self._book_update_count % 50 == 0:
            self.logger.debug("POLY_WS_PRICE_CHANGE", {
                "price": data.get("price"),
                "asset_id": data.get("asset_id")
            })
    
    async def disconnect(self):
        """Close WebSocket connection"""
        self._running = False
        
        if self._ws:
            await self._ws.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("POLY_WS_DISCONNECTED", {
            "total_messages": self._message_count,
            "book_updates": self._book_update_count,
            "last_update": self._last_update.isoformat() if self._last_update else None
        })