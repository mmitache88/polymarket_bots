"""
HFT Strategy Main Entry Point

Async event loop that wires all components together.
"""

import asyncio
import signal
from datetime import datetime, timedelta
from typing import Optional

from .config import config, HFTConfig
from .models import (
    MarketSnapshot, MarketUpdate, OracleUpdate,
    Inventory, Position, TradeIntent, OrderRequest, Rejection,
    Outcome, OrderStatus
)
from .logger import get_logger, HFTLogger
from .db import init_db, get_open_positions, save_position, remove_position, save_trade
from .gateways.mock_gateway import MockPolymarketGateway, MockBinanceGateway
from .gateways.polymarket_gateway import PolymarketGateway
from .strategies.early_entry import EarlyEntryStrategy
from .core.risk_manager import RiskManager
from .core.execution_service import ExecutionService


class HFTBot:
    """
    Main HFT Bot orchestrator.
    
    Combines all components:
    - MarketGateway (Polymarket order book)
    - OracleGateway (Binance prices)
    - StateAggregator (combines data into snapshots)
    - StrategyEngine (generates trade intents)
    - RiskManager (validates trades)
    - ExecutionService (places orders)
    """
    
    def __init__(self, cfg: HFTConfig = None):
        self.config = cfg or config
        self.logger = get_logger("hft.main")
        
        # State
        self.is_running = False
        self.latest_market_update: Optional[MarketUpdate] = None
        self.latest_oracle_update: Optional[OracleUpdate] = None
        self.inventory = Inventory()
        self.market_start_time: Optional[datetime] = None
        self.market_end_time: Optional[datetime] = None
        
        # Components (initialized in setup)
        self.market_gateway = None
        self.oracle_gateway = None
        self.strategy = None
        self.risk_manager = None
        self.execution_service = None
    
    async def setup(self, token_id: str):
        """Initialize all components"""
        self.logger.info("SETUP_START", {"token_id": token_id})
        
        # Initialize database
        init_db()
        
        # Load existing positions
        self._load_positions()

        # Initialize client (will be None for mock mode)
        client = None

        # Initialize gateways
        if self.config.execution.mock_mode:
            self.logger.info("MOCK_MODE_ENABLED")
            self.market_gateway = MockPolymarketGateway(
                token_id=token_id,
                initial_mid=0.45,
                volatility=0.01,
                update_interval=0.5
            )
            self.oracle_gateway = MockBinanceGateway(
                assets=self.config.market.tracked_assets,
                update_interval=0.2
            )
        else:
            # Live mode: Initialize real client
            self.logger.info("LIVE_MODE_ENABLED")

            # Get real Polymarket client
            from shared.polymarket_client import get_client
            client = get_client(strategy="hft")

            #REAL market gateway
            self.market_gateway = PolymarketGateway(
                token_id=token_id,
                strategy="hft",
                update_interval=0.1  # 100ms polling
            )

            # Real oracle gateway (still using mock for now)
            # TODO: Replace with real Binance WebSocket gateway
            self.oracle_gateway = MockBinanceGateway(
                assets=self.config.market.tracked_assets,
                update_interval=0.2
            )
        
        # Set up callbacks
        self.market_gateway.on_update = self._on_market_update
        self.oracle_gateway.on_update = self._on_oracle_update
        
        # Initialize strategy
        self.strategy = EarlyEntryStrategy(self.config)
        
        # Initialize risk manager
        self.risk_manager = RiskManager(self.config.risk)
        
        # Initialize execution service with client (None for mock, real for live)
        self.execution_service = ExecutionService(
            client=client,  # ✅ None for mock, ClobClient for live
            config=self.config.execution
        )
        
        # Set market times (mock: 1 hour from now)
        self.market_start_time = datetime.utcnow()
        self.market_end_time = datetime.utcnow() + timedelta(minutes=55)
        
        self.logger.info("SETUP_COMPLETE", {
            "strategy": self.strategy.name,
            "mock_mode": self.config.execution.mock_mode,
            "dry_run": self.config.execution.dry_run,
            "market_end_time": self.market_end_time.isoformat(),  # Add for debugging
            "minutes_until_close": (self.market_end_time - datetime.utcnow()).total_seconds() / 60
        })
    
    def _load_positions(self):
        """Load existing positions from database"""
        positions = get_open_positions()
        self.inventory.positions = [
            Position(
                token_id=p['token_id'],
                outcome=Outcome(p['outcome']),
                shares=p['shares'],
                entry_price=p['entry_price'],
                entry_time=datetime.fromisoformat(p['entry_time'])
            )
            for p in positions
        ]
        self.inventory.total_exposure = sum(p.cost_basis for p in self.inventory.positions)
        
        self.logger.info("POSITIONS_LOADED", {
            "count": len(self.inventory.positions),
            "total_exposure": self.inventory.total_exposure
        })
    
    async def _on_market_update(self, update: MarketUpdate):
        """Callback for market gateway updates"""
        self.latest_market_update = update
        
        if self.config.logging.log_all_ticks:
            self.logger.market_update(
                token_id=update.token_id,
                bid=update.order_book.best_bid or 0,
                ask=update.order_book.best_ask or 0
            )
    
    async def _on_oracle_update(self, update: OracleUpdate):
        """Callback for oracle gateway updates"""
        self.latest_oracle_update = update
        
        if self.config.logging.log_all_ticks:
            self.logger.oracle_update(
                asset=update.asset,
                price=update.price
            )
    
    def _build_snapshot(self) -> Optional[MarketSnapshot]:
        """Build MarketSnapshot from latest updates"""
        if not self.latest_market_update:
            return None
        
        ob = self.latest_market_update.order_book
        
        # Calculate time metrics
        now = datetime.utcnow()
        minutes_since_open = (now - self.market_start_time).total_seconds() / 60 if self.market_start_time else 0
        minutes_until_close = (self.market_end_time - now).total_seconds() / 60 if self.market_end_time else 60
        
        return MarketSnapshot(
            token_id=self.latest_market_update.token_id,
            poly_mid_price=ob.mid_price,
            poly_best_bid=ob.best_bid,
            poly_best_ask=ob.best_ask,
            poly_spread_pct=ob.spread_pct,
            poly_bid_liquidity=sum(level.size for level in ob.bids),
            poly_ask_liquidity=sum(level.size for level in ob.asks),
            oracle_price=self.latest_oracle_update.price if self.latest_oracle_update else None,
            oracle_asset=self.latest_oracle_update.asset if self.latest_oracle_update else "",
            outcome=Outcome.YES,  # TODO: Handle both outcomes
            minutes_until_close=minutes_until_close,
            minutes_since_open=minutes_since_open,
            implied_probability=ob.mid_price
        )
    
    async def _main_loop(self):
        """Main trading loop"""
        self.logger.info("MAIN_LOOP_START")
        
        loop_count = 0
        while self.is_running:
            loop_count += 1
            # Debug: Log every 50 iterations
            if loop_count % 50 == 0:
                self.logger.info("LOOP_HEARTBEAT", {
                    "iteration": loop_count,
                    "has_market": self.latest_market_update is not None,
                    "has_oracle": self.latest_oracle_update is not None
                })

            # Check kill switch
            if self.config.kill_switch:
                self.logger.kill_switch("Config kill switch activated", "user")
                await self._emergency_shutdown()
                break
            
            # Build snapshot
            snapshot = self._build_snapshot()
            if not snapshot:
                await asyncio.sleep(0.1)
                continue

            # Debug: Log snapshot built
            self.logger.info("SNAPSHOT_BUILT", {
                "mid_price": snapshot.poly_mid_price,
                "oracle_price": snapshot.oracle_price,
                "minutes_since_open": snapshot.minutes_since_open,
                "minutes_until_close": snapshot.minutes_until_close  # ← ADD THIS
            })
            
            # Run strategy
            intent = self.strategy.evaluate(snapshot, self.inventory)

            self.logger.info("STRATEGY_RESULT", {
                "action": intent.action.value if intent else "NONE",
                "reason": intent.reason if intent else "No intent"
            })
            
            if intent:
                self.logger.trade_intent(
                    action=intent.action.value,
                    token_id=intent.token_id,
                    side=intent.side.value,
                    price=intent.price,
                    size=intent.size,
                    reason=intent.reason
                )
                
                # Run through risk manager
                result = self.risk_manager.validate(intent, self.inventory, snapshot)
                
                if isinstance(result, OrderRequest):
                    # Execute trade
                    if not self.config.execution.dry_run:
                        order_state = await self.execution_service.execute(result)
                        self._update_inventory(intent, order_state)
                    else:
                        self.logger.info("DRY_RUN_SKIP", {"intent": intent.reason})
                        # Simulate fill for dry run
                        self._simulate_fill(intent)
                
                elif isinstance(result, Rejection):
                    self.logger.risk_rejection(
                        reason=result.reason,
                        check_failed=result.risk_check_failed
                    )
            
            # Small delay to prevent CPU spinning
            await asyncio.sleep(0.1)
    
    def _simulate_fill(self, intent: TradeIntent):
        """Simulate order fill for dry run mode"""
        if intent.action.value == "ENTER":
            shares = intent.size / intent.price
            position = Position(
                token_id=intent.token_id,
                outcome=intent.outcome,
                shares=shares,
                entry_price=intent.price,
                entry_time=datetime.utcnow()
            )
            self.inventory.positions.append(position)
            self.inventory.total_exposure += intent.size
            
            self.logger.position_opened(
                token_id=intent.token_id,
                side=intent.outcome.value,
                entry_price=intent.price,
                size=intent.size
            )
        
        elif intent.action.value == "EXIT":
            position = self.inventory.get_position(intent.token_id)
            if position:
                pnl = (intent.price - position.entry_price) * position.shares
                pnl_pct = (pnl / position.cost_basis) * 100
                
                self.logger.position_closed(
                    token_id=intent.token_id,
                    exit_price=intent.price,
                    pnl=pnl,
                    pnl_pct=pnl_pct
                )
                
                self.inventory.positions.remove(position)
                self.inventory.total_exposure -= position.cost_basis
                self.inventory.realized_pnl += pnl
    
    def _update_inventory(self, intent: TradeIntent, order_state):
        """Update inventory after real trade execution"""
        # TODO: Implement based on order_state
        pass
    
    async def _emergency_shutdown(self):
        """Emergency shutdown - cancel all orders, log state"""
        self.logger.critical("EMERGENCY_SHUTDOWN", {
            "positions": len(self.inventory.positions),
            "exposure": self.inventory.total_exposure
        })
        
        # Cancel all open orders
        if self.execution_service:
            await self.execution_service.cancel_all_orders()
        
        self.is_running = False
    
    async def run(self, token_id: str):
        """Main entry point"""
        try:
            await self.setup(token_id)
            
            # Connect gateways
            await self.market_gateway.connect()
            await self.oracle_gateway.connect()
            
            self.is_running = True
            
            # Run all tasks concurrently
            await asyncio.gather(
                self.market_gateway.run(),
                self.oracle_gateway.run(),
                self._main_loop()
            )
        
        except KeyboardInterrupt:
            self.logger.info("KEYBOARD_INTERRUPT")
        
        except Exception as e:
            self.logger.error("FATAL_ERROR", {"error": str(e)})
            raise
        
        finally:
            self.is_running = False
            if self.market_gateway:
                await self.market_gateway.disconnect()
            if self.oracle_gateway:
                await self.oracle_gateway.disconnect()
            
            self.logger.info("SHUTDOWN_COMPLETE", {
                "realized_pnl": self.inventory.realized_pnl
            })


async def main():
    """Entry point for running the bot"""
    import argparse
    import json
    from pathlib import Path
    
    # 1. Read config.json DIRECTLY to bypass Python import cache
    config_path = Path(__file__).parent / "config.json"
    
    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
        
        # Extract token IDs safely
        token_ids = config_data.get("market", {}).get("token_ids", [])
        default_token = token_ids[0] if token_ids else "mock_token_123"
        
        print(f"DEBUG: Config path: {config_path}")
        print(f"DEBUG: Loaded {len(token_ids)} tokens from disk")
        print(f"DEBUG: Default token set to: {default_token}")
        
    except Exception as e:
        print(f"DEBUG: Failed to read config.json: {e}")
        default_token = "mock_token_123"

    # 2. Setup Arguments
    parser = argparse.ArgumentParser(description="HFT Trading Bot")
    parser.add_argument("--token-id", type=str, default=default_token, help="Token ID to trade")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    parser.add_argument("--live", action="store_true", help="Use live market data") 
    args = parser.parse_args()
    
    # 3. Now load the config object for the bot
    from .config import config
    
    # Override config from args
    if args.dry_run:
        config.execution.dry_run = True
    
    # Handle mock/live mode
    if args.live:
        config.execution.mock_mode = False
    elif args.mock:
        config.execution.mock_mode = True
    
    # 4. Run Bot
    bot = HFTBot(config)
    await bot.run(args.token_id)


if __name__ == "__main__":
    asyncio.run(main())