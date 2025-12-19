"""
Pydantic models for HFT strategy

Strict typing for all events, states, and data transfer objects.
"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
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


class OrderBook(BaseModel):
    """Local order book state"""
    token_id: str
    bids: List[OrderBookLevel] = []
    asks: List[OrderBookLevel] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None
    
    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_pct(self) -> Optional[float]:
        if self.mid_price and self.spread:
            return (self.spread / self.mid_price) * 100
        return None


class MarketInfo(BaseModel):
    """Static market information"""
    token_id: str
    condition_id: str
    question: str
    outcome: Outcome
    end_date: datetime
    market_slug: str
    
    @property
    def minutes_until_close(self) -> float:
        delta = self.end_date - datetime.utcnow()
        return delta.total_seconds() / 60


# ============================================================
# Event Models (Emitted by Gateways)
# ============================================================

class MarketUpdate(BaseModel):
    """Event emitted by MarketGateway on order book change"""
    token_id: str
    order_book: OrderBook
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OracleUpdate(BaseModel):
    """Event emitted by OracleGateway on price change"""
    asset: str  # e.g., "BTCUSDT"
    price: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# State Models (Maintained by StateAggregator)
# ============================================================

class MarketSnapshot(BaseModel):
    """Combined state from all data sources - input to StrategyEngine"""
    # Polymarket data
    token_id: str
    poly_mid_price: Optional[float] = None
    poly_best_bid: Optional[float] = None
    poly_best_ask: Optional[float] = None
    poly_spread_pct: Optional[float] = None
    poly_bid_liquidity: float = 0.0
    poly_ask_liquidity: float = 0.0
    
    # Oracle data (Binance)
    oracle_price: Optional[float] = None
    oracle_asset: str = ""
    
    # Market metadata
    outcome: Outcome = Outcome.YES
    minutes_until_close: float = 60.0
    minutes_since_open: float = 0.0
    
    # Derived metrics
    implied_probability: Optional[float] = None  # poly_mid_price
    
    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.utcnow)


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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
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
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Rejection(BaseModel):
    """Rejected trade intent"""
    intent: TradeIntent
    reason: RejectionReason  # Change from str to RejectionReason
    risk_check_failed: str
    details: str = ""  # Add this optional field
    timestamp: datetime = Field(default_factory=datetime.utcnow)


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
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# ============================================================
# System Events
# ============================================================

class KillSwitchEvent(BaseModel):
    """Emergency shutdown event"""
    reason: str
    triggered_by: str  # "user", "drawdown", "error"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


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
