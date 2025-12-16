"""
HFT Strategy Configuration

All configurable parameters for the high-frequency trading bot.
Adjust these values based on your risk tolerance and market conditions.
"""

from typing import List, Optional
from pydantic import BaseModel


class MarketConfig(BaseModel):
    """Configuration for market selection"""
    # Token IDs to trade (provided by user)
    token_ids: List[str] = []
    
    # Assets to track on Binance (for price reference)
    tracked_assets: List[str] = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]


class EntryConfig(BaseModel):
    """Configuration for entry timing and conditions"""
    # Time-based entry conditions
    min_minutes_since_open: int = 5  # Don't enter before 5 min
    max_minutes_until_close: int = 10  # Don't enter if < 10 min left
    
    # Price-based entry conditions
    max_entry_price: float = 0.50  # Don't buy if price > $0.50
    min_entry_price: float = 0.05  # Don't buy if price < $0.05
    
    # Side selection
    side_selection: str = "cheapest"  # "cheapest", "yes_only", "no_only", "binance_direction"


class PositionConfig(BaseModel):
    """Configuration for position sizing"""
    max_position_size: float = 50.00  # Max $ per position
    max_total_exposure: float = 200.00  # Max $ across all positions
    max_concurrent_positions: int = 1  # Start with 1, expand later


class ExitConfig(BaseModel):
    """Configuration for exit conditions"""
    # Profit target (percentage)
    profit_target_pct: float = 10.0  # Exit at +10%
    
    # Stop loss (percentage)
    stop_loss_pct: float = 20.0  # Exit at -20%
    
    # Time-based exit
    exit_buffer_minutes: int = 5  # Exit 5 min before resolution
    
    # Dynamic stop loss based on time remaining
    enable_time_based_stop: bool = True
    # Tighten stop loss as expiry approaches
    stop_loss_tightening: dict = {
        30: 15.0,  # 30 min left -> 15% stop
        15: 10.0,  # 15 min left -> 10% stop
        5: 5.0,    # 5 min left -> 5% stop
    }


class RiskConfig(BaseModel):
    """Configuration for risk management"""
    # Capital tracking
    initial_capital: float = 1000.0  # Starting capital for drawdown calculation
    
    # Exposure limits
    max_total_exposure: float = 200.0  # Max $ across all positions
    max_position_size: float = 50.0  # Max $ per single position
    
    # Drawdown protection
    max_drawdown_pct: float = 25.0  # Kill switch at -25% total
    
    # Trading frequency limits
    cooldown_seconds: int = 10  # Wait between trades
    max_trades_per_minute: int = 6  # Rate limiting (was max_orders_per_minute)
    
    # Order quality
    max_slippage_pct: float = 2.0  # Max acceptable slippage
    
    # Market timing
    exit_buffer_minutes: int = 5  # Don't enter if < 5 min until resolution
    min_minutes_after_open: int = 5  # Don't enter if < 5 min after market opens
    
    # Emergency control
    kill_switch: bool = False  # Set True to stop all trading


class ExecutionConfig(BaseModel):
    """Configuration for execution"""
    dry_run: bool = True  # Simulation mode (no real trades)
    mock_mode: bool = True  # Use mock data instead of live feeds
    
    # Order settings
    order_type: str = "limit"  # "limit" or "market"
    limit_offset_pct: float = 0.5  # Place limit orders 0.5% from mid
    
    # Order timeout
    order_timeout_seconds: int = 30  # How long to wait for fill before cancelling


class LoggingConfig(BaseModel):
    """Configuration for logging"""
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file: str = "logs/hft.log"
    json_logging: bool = True  # Structured JSON logs
    log_all_ticks: bool = False  # Set True for debugging (verbose!)


class HFTConfig(BaseModel):
    """Master configuration combining all sub-configs"""
    market: MarketConfig = MarketConfig()
    entry: EntryConfig = EntryConfig()
    position: PositionConfig = PositionConfig()
    exit: ExitConfig = ExitConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    logging: LoggingConfig = LoggingConfig()
    
    # Kill switch - set True to stop everything immediately
    kill_switch: bool = False


# Default configuration instance
config = HFTConfig()


def load_config(config_path: Optional[str] = None) -> HFTConfig:
    """Load configuration from JSON file or return defaults"""
    import json
    import os
    
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            data = json.load(f)
            return HFTConfig(**data)
    
    return HFTConfig()


def save_config(cfg: HFTConfig, config_path: str = "strategies/hft/config.json"):
    """Save configuration to JSON file"""
    import json
    
    with open(config_path, 'w') as f:
        json.dump(cfg.model_dump(), f, indent=2)