"""
Risk Manager - The Gatekeeper

Validates all trade intents before execution.
"""

from datetime import datetime, timedelta
from typing import Union, List

from ..models import (
    TradeIntent, OrderRequest, Rejection, Inventory,
    RejectionReason, TradeIntentAction, MarketSnapshot
)
from ..config import RiskConfig
from ..logger import get_logger


class RiskManager:
    """
    Validates trade intents against risk parameters.
    
    Checks:
    - Max exposure
    - Max drawdown
    - Cooldown timers
    - Rate limiting
    - Max slippage
    - Kill switch
    """
    
    def __init__(self, config: RiskConfig):
        self.config = config
        self.last_trade_time: datetime = datetime.min
        self.trades_this_minute: int = 0
        self.minute_start: datetime = datetime.utcnow()
        self.peak_equity: float = config.initial_capital
        self.current_equity: float = config.initial_capital
    
    def validate(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[OrderRequest, Rejection]:
        """
        Validate a trade intent against all risk checks.
        
        Args:
            intent: The trade intent from strategy engine
            inventory: Current inventory state
            snapshot: Current market snapshot
            
        Returns:
            OrderRequest if approved, Rejection if denied
        """
        # Check kill switch first
        if self.config.kill_switch:
            return Rejection(
                intent=intent,
                reason=RejectionReason.KILL_SWITCH,
                message="Kill switch is active"
            )
        
        # Skip validation for HOLD actions
        if intent.action == TradeIntentAction.HOLD:
            return Rejection(
                intent=intent,
                reason=RejectionReason.MARKET_CLOSED,
                message="No action required"
            )
        
        # Run all checks
        checks = [
            self._check_cooldown,
            self._check_rate_limit,
            self._check_max_exposure,
            self._check_max_drawdown,
            self._check_market_timing,
            self._check_price_slippage,
        ]
        
        for check in checks:
            rejection = check(intent, inventory, snapshot)
            if rejection:
                return rejection
        
        # All checks passed - create order request
        return OrderRequest(
            intent=intent,
            approved_at=datetime.utcnow(),
            max_slippage=self.config.max_slippage
        )
    
    def _check_cooldown(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if enough time has passed since last trade"""
        time_since_last = (datetime.utcnow() - self.last_trade_time).total_seconds()
        
        if time_since_last < self.config.cooldown_seconds:
            return Rejection(
                intent=intent,
                reason=RejectionReason.COOLDOWN,
                message=f"Cooldown active: {self.config.cooldown_seconds - time_since_last:.1f}s remaining"
            )
        return None
    
    def _check_rate_limit(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if we've exceeded trades per minute"""
        now = datetime.utcnow()
        
        # Reset counter if new minute
        if (now - self.minute_start).total_seconds() >= 60:
            self.trades_this_minute = 0
            self.minute_start = now
        
        if self.trades_this_minute >= self.config.max_trades_per_minute:
            return Rejection(
                intent=intent,
                reason=RejectionReason.COOLDOWN,
                message=f"Rate limit: {self.config.max_trades_per_minute} trades/min exceeded"
            )
        return None
    
    def _check_max_exposure(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if trade would exceed max exposure"""
        # Only check for ENTER actions
        if intent.action != TradeIntentAction.ENTER:
            return None
        
        # Calculate new exposure
        trade_value = intent.size * intent.price
        new_exposure = inventory.total_exposure + trade_value
        
        if new_exposure > self.config.max_total_exposure:
            return Rejection(
                intent=intent,
                reason=RejectionReason.MAX_EXPOSURE,
                message=f"Would exceed max exposure: ${new_exposure:.2f} > ${self.config.max_total_exposure:.2f}"
            )
        
        # Check per-position limit
        if trade_value > self.config.max_position_size:
            return Rejection(
                intent=intent,
                reason=RejectionReason.MAX_EXPOSURE,
                message=f"Position size ${trade_value:.2f} exceeds max ${self.config.max_position_size:.2f}"
            )
        
        return None
    
    def _check_max_drawdown(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if we've hit max drawdown"""
        # Update peak equity
        self.current_equity = self.config.initial_capital + inventory.total_pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        
        # Calculate drawdown
        if self.peak_equity > 0:
            drawdown_pct = ((self.peak_equity - self.current_equity) / self.peak_equity) * 100
            
            if drawdown_pct >= self.config.max_drawdown_pct:
                return Rejection(
                    intent=intent,
                    reason=RejectionReason.MAX_DRAWDOWN,
                    message=f"Max drawdown reached: {drawdown_pct:.1f}% >= {self.config.max_drawdown_pct:.1f}%"
                )
        
        return None
    
    def _check_market_timing(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if market timing is appropriate"""
        # Don't enter if too close to resolution
        if intent.action == TradeIntentAction.ENTER:
            if snapshot.minutes_until_resolution < self.config.exit_buffer_minutes:
                return Rejection(
                    intent=intent,
                    reason=RejectionReason.MARKET_CLOSED,
                    message=f"Too close to resolution: {snapshot.minutes_until_resolution:.1f}min < {self.config.exit_buffer_minutes}min buffer"
                )
            
            # Don't enter if market too young (optional)
            if snapshot.minutes_since_open < self.config.min_minutes_after_open:
                return Rejection(
                    intent=intent,
                    reason=RejectionReason.MARKET_CLOSED,
                    message=f"Market too young: {snapshot.minutes_since_open:.1f}min < {self.config.min_minutes_after_open}min minimum"
                )
        
        return None
    
    def _check_price_slippage(
        self,
        intent: TradeIntent,
        inventory: Inventory,
        snapshot: MarketSnapshot
    ) -> Union[Rejection, None]:
        """Check if price has moved too much since signal"""
        if intent.action == TradeIntentAction.ENTER:
            # For buys, check if ask has moved up
            if snapshot.poly_best_ask and intent.price:
                slippage = (snapshot.poly_best_ask - intent.price) / intent.price
                if slippage > self.config.max_slippage:
                    return Rejection(
                        intent=intent,
                        reason=RejectionReason.PRICE_MOVED,
                        message=f"Price slippage {slippage:.2%} > {self.config.max_slippage:.2%}"
                    )
        
        return None
    
    def record_trade(self):
        """Record that a trade was executed (call after successful execution)"""
        self.last_trade_time = datetime.utcnow()
        self.trades_this_minute += 1
    
    def update_equity(self, new_equity: float):
        """Update current equity for drawdown tracking"""
        self.current_equity = new_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

    def activate_kill_switch(self, reason: str = "manual"):
        """Activate the kill switch"""
        self.config.kill_switch = True
        logger = get_logger(__name__)
        logger.critical({
            "event": "KILL_SWITCH_ACTIVATED",
            "reason": reason
        })
    
    def deactivate_kill_switch(self):
        """Deactivate the kill switch"""
        self.config.kill_switch = False
        logger = get_logger(__name__)
        logger.warning({
            "event": "KILL_SWITCH_DEACTIVATED"
        })
    
    def get_stats(self) -> dict:
        """Get risk manager statistics"""
        return {
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time != datetime.min else None,
            "trades_this_minute": self.trades_this_minute,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            "drawdown_pct": ((self.peak_equity - self.current_equity) / self.peak_equity * 100) if self.peak_equity > 0 else 0,
            "kill_switch_active": self.config.kill_switch
        }
    
    def reset(self):
        """Reset risk manager state"""
        self.last_trade_time = datetime.min
        self.trades_this_minute = 0
        self.minute_start = datetime.utcnow()
        self.peak_equity = self.config.initial_capital
        self.current_equity = self.config.initial_capital