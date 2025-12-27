"""
HFT Strategy Main Entry Point

Async event loop that wires all components together.
"""

import asyncio
import signal
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import config, HFTConfig
from .models import (
    MarketSnapshot, MarketUpdate, OracleUpdate,
    Inventory, Position, TradeIntent, OrderRequest, Rejection,
    Outcome, OrderStatus
)
from .logger import get_logger, HFTLogger
from .db import (
    init_hft_db, 
    save_market_tick, 
    get_open_positions, 
    save_position, 
    remove_position, 
    save_trade
)
from .gateways.mock_gateway import MockPolymarketGateway, MockBinanceGateway
from .gateways.polymarket_gateway import PolymarketGateway
from .gateways.polymarket_ws_gateway import PolymarketWebSocketGateway  # ✅ NEW
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
        self.strike_price = 0.0
        
        # Components (initialized in setup)
        self.market_gateway = None
        self.oracle_gateway = None
        self.strategy = None
        self.risk_manager = None
        self.execution_service = None
        
        # ✅ NEW: Separate REST client for execution (initialized in setup)
        self.execution_client = None
    
    async def setup(self, token_id: str):
        """Initialize all components"""
        self.logger.info("SETUP_START", {"token_id": token_id})

        # ✅ Initialize HFT Database
        init_hft_db()

        # ✅ Ensure self.token_id is set even if not using "auto"
        self.token_id = token_id

        # ✅ AUTO-DISCOVERY LOGIC
        if token_id == "auto":
            self.logger.info("AUTO_FETCHING_MARKET")
            try:
                from shared.gamma_client import fetch_current_hourly_market
                market_data = fetch_current_hourly_market()
                
                if market_data and market_data['token_ids']:
                    # DEBUG: Print the type and content
                    self.logger.info("DEBUG_TOKEN_IDS", {
                        "type": str(type(market_data['token_ids'])),
                        "content": market_data['token_ids']
                    })

                    # Default to the "YES" token (Index 0 based on your verification)
                    # You could add logic here to pick based on config (e.g. "outcome": "YES")
                    
                    # SAFETY CHECK: Ensure it's a list
                    ids = market_data['token_ids']
                    if isinstance(ids, str):
                        import json
                        try:
                            ids = json.loads(ids)
                        except:
                            # If it's a string but not JSON, maybe it's just one ID?
                            pass
                    token_id = ids[0]

                    # ✅ Access the raw market object
                    raw_market = market_data.get('raw_market', {})
                    
                    # Try to get strike from API fields (will be None for Up/Down markets)
                    strike = (
                        raw_market.get('line') or
                        raw_market.get('strikePrice') or
                        raw_market.get('initialPrice')
                    )
                    
                    # ✅ Fallback: Calculate strike from Binance at eventStartTime
                    if not strike or float(strike or 0) == 0:
                        from shared.binance_client import get_btc_price_at_timestamp
                        from datetime import datetime
                        
                        event_start = raw_market.get('eventStartTime')
                        if event_start:
                            start_time = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                            strike = get_btc_price_at_timestamp(start_time)
                            
                            self.logger.info("STRIKE_FROM_BINANCE", {
                                "timestamp": event_start,
                                "price": strike
                            })
                        else:
                            strike = 0.0
                    
                    self.strike_price = float(strike)
                    
                    self.logger.info("MARKET_FOUND", {
                        "question": market_data['question'],
                        "strike_price": self.strike_price, # ✅ FIXED: Use self.strike_price, not market_data
                        "token_id": token_id,
                        "end_date": market_data['end_date']
                    })
                    
                    # Update the instance token_id
                    self.token_id = token_id
                    
                    # OPTIONAL: Set exact market times from API data
                    if market_data.get('end_date'):
                        # Parse ISO format (e.g. 2025-12-24T22:00:00Z)
                        self.market_end_time = datetime.fromisoformat(market_data['end_date'].replace('Z', '+00:00'))
                        self.market_start_time = self.market_end_time - timedelta(hours=1)
                else:
                    raise ValueError("Could not find active hourly market via Gamma API")
            except Exception as e:
                self.logger.error("AUTO_FETCH_FAILED", {"error": str(e)})
                raise e
        
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

            # No execution client in mock mode
            self.execution_client = None

        else:
            # ✅ LIVE MODE: WebSocket for market data, REST for execution
            self.logger.info("LIVE_MODE_ENABLED")

            # ✅ FIX: Initialize REST client for EXECUTION ONLY and store in instance variable
            from shared.polymarket_client import get_client
            self.execution_client = get_client(strategy="hft")  # ✅ CHANGED: Use self.execution_client

            # ✅ FIX: Only infer times if they weren't already set by Auto-Discovery
            if not self.market_end_time:
                now = datetime.now(timezone.utc)
                next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                self.market_start_time = next_hour - timedelta(hours=1)
                self.market_end_time = next_hour
                
                self.logger.info("MARKET_TIMES_INFERRED", {
                    "end": self.market_end_time.isoformat()
                })

            # ✅ CHANGED: Use WebSocket gateway for MARKET DATA
            self.market_gateway = PolymarketWebSocketGateway(
                token_id=token_id
            )

            # ✅ Use real Binance WebSocket in live mode
            from strategies.hft.gateways.binance_gateway import BinanceWebSocketGateway
            self.oracle_gateway = BinanceWebSocketGateway(
                symbols=["BTCUSDT"],
                update_interval=0.2
            )
        
        # Set up callbacks (same for both modes)
        self.market_gateway.on_update = self._on_market_update
        self.oracle_gateway.on_update = self._on_oracle_update
        
        # Initialize strategy
        self.strategy = EarlyEntryStrategy(self.config)
        
        # Initialize risk manager
        self.risk_manager = RiskManager(self.config.risk)
        
        # ✅ CHANGED: Pass execution_client (None for mock, ClobClient for live)
        self.execution_service = ExecutionService(
            client=self.execution_client,  # ✅ Separate REST client for execution
            config=self.config.execution
        )

        
        self.logger.info("SETUP_COMPLETE", {
            "strategy": self.strategy.name,
            "mock_mode": self.config.execution.mock_mode,
            "dry_run": self.config.execution.dry_run,
            "market_data_source": "WebSocket" if not self.config.execution.mock_mode else "Mock",
            "execution_source": "REST API" if self.execution_client else "Mock",
            "market_end_time": self.market_end_time.isoformat(),
            "minutes_until_close": (self.market_end_time - datetime.now(timezone.utc)).total_seconds() / 60
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

    async def _check_market_rollover(self) -> bool:
        """
        Check if current market is about to close and switch to next market.
        Returns True if rollover happened, False otherwise.
        """
        now = datetime.now(timezone.utc)
        minutes_left = (self.market_end_time - now).total_seconds() / 60
        
        # Switch 2 minutes before close to avoid missing the new market
        if minutes_left <= 2.0:
            self.logger.info("MARKET_ROLLOVER_TRIGGERED", {
                "old_market": self.token_id,
                "minutes_left": minutes_left
            })
            
            try:
                # Re-run auto-discovery to find next market
                from shared.gamma_client import fetch_current_hourly_market
                market_data = fetch_current_hourly_market()
                
                if market_data and market_data['token_ids']:
                    import json
                    ids = market_data['token_ids']
                    if isinstance(ids, str):
                        ids = json.loads(ids)
                    
                    new_token_id = ids[0]
                    
                    # Only switch if it's a different market
                    if new_token_id == self.token_id:
                        self.logger.info("ROLLOVER_SKIPPED", {"reason": "Same market still active"})
                        return False
                    
                    # Extract new strike price
                    raw_market = market_data.get('raw_market', {})
                    event_start = raw_market.get('eventStartTime')
                    
                    if event_start:
                        from shared.binance_client import get_btc_price_at_timestamp
                        start_time = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                        self.strike_price = get_btc_price_at_timestamp(start_time)
                        
                        self.logger.info("NEW_STRIKE_FROM_BINANCE", {
                            "timestamp": event_start,
                            "price": self.strike_price
                        })
                    
                    # Update market times
                    self.market_end_time = datetime.fromisoformat(
                        market_data['end_date'].replace('Z', '+00:00')
                    )
                    self.market_start_time = self.market_end_time - timedelta(hours=1)
                    
                    # ✅ CRITICAL FIX: Restart market gateway with new token
                    old_token = self.token_id
                    self.token_id = new_token_id
                    
                    # Stop the old market gateway task
                    if hasattr(self, '_market_gateway_task'):
                        self._market_gateway_task.cancel()
                        try:
                            await self._market_gateway_task
                        except asyncio.CancelledError:
                            pass
                        
                        self.logger.info("GATEWAY_TASK_CANCELLED")
                    
                    # ✅ CHANGED: Properly restart WebSocket gateway
                    await self.market_gateway.disconnect()
                    
                    # ✅ For WebSocket: Create new instance with new token_id
                    if isinstance(self.market_gateway, PolymarketWebSocketGateway):
                        self.market_gateway = PolymarketWebSocketGateway(
                            token_id=new_token_id
                        )
                        self.market_gateway.on_update = self._on_market_update
                    else:
                        # For REST gateway (fallback)
                        self.market_gateway.token_id = new_token_id
                    
                    await self.market_gateway.connect()
                    self._market_gateway_task = asyncio.create_task(self.market_gateway.run())
                    
                    self.logger.info("GATEWAY_TASK_RESTARTED", {"new_token": new_token_id})
                    
                    # Clear positions for new market
                    self.inventory.positions = []
                    self.inventory.total_exposure = 0
                    
                    self.logger.info("MARKET_ROLLOVER_COMPLETE", {
                        "old_token_id": old_token,
                        "new_token_id": new_token_id,
                        "new_strike": self.strike_price,
                        "new_end_time": self.market_end_time.isoformat()
                    })
                    
                    return True
                
            except Exception as e:
                self.logger.error("ROLLOVER_FAILED", {"error": str(e)})
                return False
        
        return False
    
    def _build_snapshot(self) -> Optional[MarketSnapshot]:
        """Build MarketSnapshot from latest updates"""
        if not self.latest_market_update or not self.latest_oracle_update:
            return None

        ob = self.latest_market_update.order_book
        if not ob:
            return None

        now = datetime.now(timezone.utc)
        
        # Calculate time metrics
        total_duration = (self.market_end_time - self.market_start_time).total_seconds() / 60
        minutes_until_close = (self.market_end_time - now).total_seconds() / 60
        minutes_since_open = (now - self.market_start_time).total_seconds() / 60
        
        # ✅ Calculate Phase 1 metrics
        bid_liquidity = sum(level.size for level in ob.bids) if ob.bids else 0.0
        ask_liquidity = sum(level.size for level in ob.asks) if ob.asks else 0.0
        
        oracle_price = self.latest_oracle_update.price if self.latest_oracle_update else 0.0
        
        # Distance to strike (%)
        distance_to_strike_pct = (
            ((oracle_price - self.strike_price) / self.strike_price * 100)
            if self.strike_price > 0 else 0.0
        )
        
        # Order flow imbalance (-1 to +1)
        total_liquidity = bid_liquidity + ask_liquidity
        order_flow_imbalance = (
            ((bid_liquidity - ask_liquidity) / total_liquidity)
            if total_liquidity > 0 else 0.0
        )
        
        # Market session (EARLY/MID/LATE)
        if minutes_since_open < 20:
            market_session = "EARLY"
        elif minutes_since_open < 40:
            market_session = "MID"
        else:
            market_session = "LATE"
        
        return MarketSnapshot(
            token_id=self.latest_market_update.token_id,
            strike_price=self.strike_price,
            poly_mid_price=ob.mid_price,
            poly_best_bid=ob.best_bid,
            poly_best_ask=ob.best_ask,
            poly_spread_pct=ob.spread_pct,
            poly_bid_liquidity=bid_liquidity,
            poly_ask_liquidity=ask_liquidity,
            oracle_price=oracle_price,
            oracle_asset=self.latest_oracle_update.asset if self.latest_oracle_update else "",
            outcome=Outcome.YES,
            minutes_until_close=minutes_until_close,
            minutes_since_open=minutes_since_open,
            implied_probability=ob.mid_price,
            # ✅ Store Phase 1 metrics in snapshot for easy access
            distance_to_strike_pct=distance_to_strike_pct,
            order_flow_imbalance=order_flow_imbalance,
            market_session=market_session
        )

    async def _main_loop(self):
        """Main trading loop"""
        self.logger.info("MAIN_LOOP_START")
        
        loop_count = 0
        last_db_save = 0  # Track last save time
        
        while self.is_running:
            loop_count += 1

            # ✅ Check for market rollover
            rolled_over = await self._check_market_rollover()
            if rolled_over:
                # Clear positions for new market (or implement position carry-over logic)
                self.inventory.positions = []
                self.inventory.total_exposure = 0
                continue  # Skip this iteration to let new market data flow in

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

            # ✅ SAVE TO DB (Every 5 seconds)
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            if now_ts - last_db_save >= 5.0:
                try:
                    save_market_tick(
                        token_id=self.token_id,
                        strike_price=snapshot.strike_price,
                        best_bid=snapshot.poly_best_bid,
                        best_ask=snapshot.poly_best_ask,
                        mid_price=snapshot.poly_mid_price,
                        oracle_price=snapshot.oracle_price or 0.0,
                        minutes_until_close=snapshot.minutes_until_close,
                        # ✅ Phase 1 metrics
                        bid_liquidity=snapshot.poly_bid_liquidity,
                        ask_liquidity=snapshot.poly_ask_liquidity,
                        distance_to_strike_pct=snapshot.distance_to_strike_pct,
                        order_flow_imbalance=snapshot.order_flow_imbalance,
                        market_session=snapshot.market_session
                    )
                    last_db_save = now_ts
                    self.logger.info("DB_TICK_SAVED", {
                        "token_id": self.token_id, 
                        "bid": snapshot.poly_best_bid, 
                        "ask": snapshot.poly_best_ask,
                        "session": snapshot.market_session,  # ✅ Log session
                        "imbalance": f"{snapshot.order_flow_imbalance:.3f}"  # ✅ Log imbalance
                    })
                except Exception as e:
                    self.logger.error("DB_SAVE_ERROR", {"error": str(e)})

            # Debug: Log snapshot built
            self.logger.info("SNAPSHOT_BUILT", {
                "mid_price": snapshot.poly_mid_price,
                "oracle_price": snapshot.oracle_price,
                "minutes_since_open": snapshot.minutes_since_open,
                "minutes_until_close": snapshot.minutes_until_close
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
        # ✅ Build snapshot to get market context
        snapshot = self._build_snapshot()

        if intent.action.value == "ENTER":
            shares = intent.size / intent.price
            position = Position(
                token_id=intent.token_id,
                outcome=intent.outcome,
                shares=shares,
                entry_price=intent.price,
                entry_time=datetime.now(timezone.utc)  # ✅ FIXED
            )
            self.inventory.positions.append(position)
            self.inventory.total_exposure += intent.size

            # ✅ ADDED: Record to database
            save_position(
                token_id=intent.token_id,
                outcome=intent.outcome.value,
                shares=shares,
                entry_price=intent.price,
                entry_time=position.entry_time
            )
            
            save_trade(
                token_id=intent.token_id,
                side=intent.side.value,
                outcome=intent.outcome.value,  # ✅ ADDED
                price=intent.price,
                size=intent.size,
                shares=shares,  # ✅ ADDED
                pnl=0.0,
                strategy_reason=intent.reason,  # ✅ ADDED
                oracle_price=snapshot.oracle_price if snapshot else 0.0,  # ✅ ADDED
                strike_price=self.strike_price,  # ✅ ADDED
                minutes_until_close=snapshot.minutes_until_close if snapshot else 0.0,  # ✅ ADDED
                spread_pct=snapshot.poly_spread_pct if snapshot else 0.0,  # ✅ ADDED
                bid_liquidity=snapshot.poly_bid_liquidity if snapshot else 0.0,  # ✅ ADDED
                ask_liquidity=snapshot.poly_ask_liquidity if snapshot else 0.0  # ✅ ADDED
            )
            
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

                # ✅ ADDED: Record exit trade with P&L
                save_trade(
                    token_id=intent.token_id,
                    side=intent.side.value,
                    outcome=intent.outcome.value,  # ✅ ADDED
                    price=intent.price,
                    size=intent.size,
                    shares=position.shares,  # ✅ ADDED
                    pnl=pnl,
                    strategy_reason=intent.reason,  # ✅ ADDED
                    oracle_price=snapshot.oracle_price if snapshot else 0.0,  # ✅ ADDED
                    strike_price=self.strike_price,  # ✅ ADDED
                    minutes_until_close=snapshot.minutes_until_close if snapshot else 0.0,  # ✅ ADDED
                    spread_pct=snapshot.poly_spread_pct if snapshot else 0.0,  # ✅ ADDED
                    bid_liquidity=snapshot.poly_bid_liquidity if snapshot else 0.0,  # ✅ ADDED
                    ask_liquidity=snapshot.poly_ask_liquidity if snapshot else 0.0  # ✅ ADDED
                )
                
                # ✅ ADDED: Remove from positions table
                remove_position(intent.token_id)
                
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
            
            # ✅ Start tasks
            self._market_gateway_task = asyncio.create_task(self.market_gateway.run())
            self._oracle_gateway_task = asyncio.create_task(self.oracle_gateway.run())
            self._main_loop_task = asyncio.create_task(self._main_loop())
            
            # ✅ Wait for main loop to finish (it controls shutdown)
            # Don't wait for gateway tasks since they may be cancelled during rollover
            await self._main_loop_task
        
        except KeyboardInterrupt:
            self.logger.info("KEYBOARD_INTERRUPT")
        
        except Exception as e:
            self.logger.error("FATAL_ERROR", {"error": str(e)})
            raise
        
        finally:
            self.is_running = False
            
            # ✅ Cancel all tasks
            for task in [self._market_gateway_task, self._oracle_gateway_task, self._main_loop_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Disconnect gateways
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