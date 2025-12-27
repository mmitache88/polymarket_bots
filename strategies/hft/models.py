"""
Pydantic models for HFT strategy

Strict typing for all events, states, and data transfer objects.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, model_validator
from enum import Enum


# ============================================================
# Enums
# ============================================================

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Outcome(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TradeIntentAction(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    HOLD = "HOLD"

class RejectionReason(str, Enum):
    """Reasons why a trade intent was rejected by RiskManager"""
    MAX_EXPOSURE = "MAX_EXPOSURE"
    MAX_POSITION = "MAX_POSITION"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    COOLDOWN = "COOLDOWN"
    RATE_LIMIT = "RATE_LIMIT"
    KILL_SWITCH = "KILL_SWITCH"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    MARKET_TIMING = "MARKET_TIMING"
    PRICE_SLIPPAGE = "PRICE_SLIPPAGE"

# ============================================================
# Market Data Models
# ============================================================

class OrderBookLevel(BaseModel):
    """Single level in order book"""
    price: float
    size: float


class OrderBook(BaseModel): # ✅ Inherit from BaseModel
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]

    @model_validator(mode='after')
    def sort_book(self) -> 'OrderBook':
        """Ensure bids and asks are always sorted correctly after initialization"""
        self.bids = sorted(self.bids, key=lambda x: x.price, reverse=True)
        self.asks = sorted(self.asks, key=lambda x: x.price)
        return self

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2
        return 0.0

    @property
    def spread_pct(self) -> float:
        mid = self.mid_price
        if mid > 0:
            return (self.best_ask - self.best_bid) / mid
        return 0.0


class MarketInfo(BaseModel):
    """Static market information"""
    timestamp: datetime
    order_book: OrderBook
    token_id: str
    condition_id: str
    question: str
    outcome: Outcome
    end_date: datetime
    market_slug: str
    
    @property
    def minutes_until_close(self) -> float:
        # ✅ FIX: Use aware datetime to match API end_date
        delta = self.end_date - datetime.now(timezone.utc)
        return delta.total_seconds() / 60


# ============================================================
# Event Models (Emitted by Gateways)
# ============================================================

class MarketUpdate(BaseModel):
    """Event emitted by MarketGateway on order book change"""
    token_id: str
    order_book: OrderBook
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OracleUpdate(BaseModel):
    """Event emitted by OracleGateway on price change"""
    asset: str  # e.g., "BTCUSDT"
    price: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# State Models (Maintained by StateAggregator)
# ============================================================

@dataclass
class MarketSnapshot:
    """Complete view of market state at a point in time"""
    # Identifiers
    token_id: str
    outcome: Outcome
    
    # Polymarket prices
    poly_mid_price: float
    poly_best_bid: Optional[float]
    poly_best_ask: Optional[float]
    poly_spread_pct: float
    poly_bid_liquidity: float
    poly_ask_liquidity: float
    
    # Oracle prices
    oracle_price: Optional[float]
    oracle_asset: str
    strike_price: float
    
    # Time metrics
    minutes_until_close: float
    minutes_since_open: float
    
    # Derived metrics
    implied_probability: float
    
    # ✅ Phase 1 metrics
    distance_to_strike_pct: float = 0.0
    order_flow_imbalance: float = 0.0
    market_session: str = "UNKNOWN"
    
    @property
    def is_market_open(self) -> bool:
        return self.minutes_until_close > 0


class Position(BaseModel):
    """Current position in a market"""
    token_id: str
    outcome: Outcome
    shares: float
    entry_price: float
    entry_time: datetime
    current_price: Optional[float] = None
    
    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price
    
    @property
    def current_value(self) -> Optional[float]:
        if self.current_price:
            return self.shares * self.current_price
        return None
    
    @property
    def unrealized_pnl(self) -> Optional[float]:
        if self.current_value:
            return self.current_value - self.cost_basis
        return None
    
    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        if self.unrealized_pnl and self.cost_basis > 0:
            return (self.unrealized_pnl / self.cost_basis) * 100
        return None


class Inventory(BaseModel):
    """Current inventory state"""
    positions: List[Position] = []
    cash_balance: float = 0.0
    total_exposure: float = 0.0
    realized_pnl: float = 0.0
    
    @property
    def unrealized_pnl(self) -> float:
        """Sum of unrealized PnL across all open positions"""
        return sum((p.unrealized_pnl or 0.0) for p in self.positions)

    @property
    def total_pnl(self) -> float:
        """Realized + Unrealized PnL"""
        return self.realized_pnl + self.unrealized_pnl

    def get_position(self, token_id: str) -> Optional[Position]:
        for pos in self.positions:
            if pos.token_id == token_id:
                return pos
        return None


# ============================================================
# Trade Models (Strategy Output -> Execution)
# ============================================================

class TradeIntent(BaseModel):
    """Output from StrategyEngine - what the strategy WANTS to do"""
    action: TradeIntentAction
    token_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float  # In dollars
    reason: str  # Human-readable explanation
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # ✅ FIX
    
    # Strategy metadata
    strategy_name: str = "unknown"
    confidence: float = 0.0  # 0-1 confidence score


class OrderRequest(BaseModel):
    """Approved trade request ready for execution"""
    intent: TradeIntent
    approved_size: float  # May be reduced by RiskManager
    order_type: Literal["limit", "market"] = "limit"
    limit_price: Optional[float] = None
    time_in_force: str = "GTC"  # Good Till Cancelled
    
    # Risk metadata
    risk_checks_passed: List[str] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # ✅ FIX


class Rejection(BaseModel):
    """Rejected trade intent"""
    intent: TradeIntent
    reason: RejectionReason  # Change from str to RejectionReason
    risk_check_failed: str
    details: str = ""  # Add this optional field
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # ✅ FIX


class OrderState(BaseModel):
    """Tracks order lifecycle"""
    order_id: str
    request: OrderRequest
    status: OrderStatus = OrderStatus.PENDING
    filled_shares: float = 0.0
    average_fill_price: Optional[float] = None
    submitted_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    error_message: Optional[str] = None

class ExecutionReport(BaseModel):
    """Report from ExecutionService after order execution"""
    order_id: Optional[str] = None
    order_request: OrderRequest
    status: OrderStatus
    filled_size: float = 0.0
    filled_price: Optional[float] = None
    filled_at: Optional[datetime] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # ✅ FIX

# ============================================================
# System Events
# ============================================================

class KillSwitchEvent(BaseModel):
    """Emergency shutdown event"""
    reason: str
    triggered_by: str  # "user", "drawdown", "error"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # ✅ FIX


class SystemStatus(BaseModel):
    """Overall system health"""
    is_running: bool = False
    kill_switch_active: bool = False
    polymarket_connected: bool = False
    binance_connected: bool = False
    last_market_update: Optional[datetime] = None
    last_oracle_update: Optional[datetime] = None
    open_orders: int = 0
    open_positions: int = 0
    total_pnl: float = 0.0
