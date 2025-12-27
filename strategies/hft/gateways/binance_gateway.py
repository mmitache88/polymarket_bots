import asyncio
import json
import websockets
from typing import Callable, Optional, List
from datetime import datetime
import structlog

logger = structlog.get_logger()


class BinanceWebSocketGateway:
    """Real-time price feed from Binance WebSocket API"""
    
    def __init__(self, symbols: List[str] = ["BTCUSDT"], update_interval: float = 0.1):
        """
        Args:
            symbols: List of trading pairs (e.g., ["BTCUSDT", "ETHUSDT"])
            update_interval: Minimum seconds between price updates (throttle)
        """
        self.symbols = [s.lower() for s in symbols]
        self.update_interval = update_interval
        self.prices = {s.upper(): 0.0 for s in symbols}
        self.on_update: Optional[Callable] = None
        self._running = False
        self._ws = None
        self._last_update = datetime.now()
        
    async def connect(self):
        """Connect to Binance WebSocket"""
        # Build stream names: btcusdt@ticker, ethusdt@ticker
        streams = "/".join([f"{s}@ticker" for s in self.symbols])
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        
        self._ws = await websockets.connect(url)
        self._running = True
        
        logger.info("BINANCE_WS_CONNECTED", symbols=self.symbols)
        
    async def disconnect(self):
        """Close WebSocket connection"""
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info("BINANCE_WS_DISCONNECTED")
        
    async def run(self):
        """Main event loop - processes incoming messages"""
        # Import here to avoid circular dependency
        from strategies.hft.models import OracleUpdate
        
        if not self._ws:
            await self.connect()
            
        logger.info("BINANCE_WS_RUN_START", is_running=self._running)
        
        try:
            async for message in self._ws:
                if not self._running:
                    break
                    
                data = json.loads(message)
                
                # Message format: {"stream": "btcusdt@ticker", "data": {...}}
                if "data" in data:
                    ticker = data["data"]
                    symbol = ticker["s"]  # e.g., "BTCUSDT"
                    price = float(ticker["c"])  # Last price
                    
                    # Update price
                    self.prices[symbol] = price
                    
                    # Throttle updates
                    now = datetime.now()
                    elapsed = (now - self._last_update).total_seconds()
                    
                    if elapsed >= self.update_interval:
                        self._last_update = now
                        
                        if self.on_update:
                            # ✅ Send OracleUpdate object, not dict
                            update = OracleUpdate(
                                asset="BTCUSDT",
                                price=self.prices.get("BTCUSDT", 0.0),
                                oracle_time=now
                            )
                            await self.on_update(update)
                            
        except Exception as e:
            logger.error("BINANCE_WS_ERROR", error=str(e))
            self._running = False