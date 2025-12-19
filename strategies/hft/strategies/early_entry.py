""""
Early Entry Strategy

Buy low-priced YES or NO early in the market (5+ minutes in),
exit on profit target or before resolution.
"""

from typing import Optional
from datetime import datetime

from .base import BaseStrategy
from ..models import (
    MarketSnapshot, Inventory, TradeIntent,
    TradeIntentAction, Side, Outcome
)
from ..config import HFTConfig
from ..logger import HFTLogger


class EarlyEntryStrategy(BaseStrategy):
    """
    Strategy: Buy cheap options early, sell on profit target.
    
    Entry conditions:
    - Market has been open for at least `min_minutes_since_open`
    - Price is below `max_entry_price`
    - No existing position in this token
    
    Exit conditions:
    - Profit target reached
    - Stop loss hit
    - Approaching market close
    """
    
    name: str = "early_entry"
    
    def __init__(self, config: HFTConfig):
        self.config = config
        self.entry_config = config.entry
        self.position_config = config.position
        self.exit_config = config.exit  # <--- FIX: Added this line
    
    def evaluate(
        self,
        snapshot: MarketSnapshot,
        inventory: Inventory
    ) -> Optional[TradeIntent]:
        """Evaluate market and return trade intent"""
        
        # Check if we have an existing position
        position = inventory.get_position(snapshot.token_id)
        
        if position:
            # Check for exit
            return self._evaluate_exit(snapshot, inventory, position)
        else:
            # Check for entry
            return self._evaluate_entry(snapshot, inventory)
    
    def _evaluate_entry(
        self,
        snapshot: MarketSnapshot,
        inventory: Inventory
    ) -> Optional[TradeIntent]:
        """Evaluate entry conditions"""
        logger = HFTLogger("hft.strategy")
        
        # Time check: must be at least X minutes into market
        if snapshot.minutes_since_open < self.entry_config.min_minutes_since_open:
            logger.debug("ENTRY_REJECT", {
                "reason": "too_early",
                "minutes_since_open": snapshot.minutes_since_open,
                "min_required": self.entry_config.min_minutes_since_open
            })
            return None
        
        # Time check: don't enter if too close to resolution
        if snapshot.minutes_until_close is None:
            logger.debug("ENTRY_REJECT", {
                "reason": "minutes_until_close is None"
            })
            return None

        if snapshot.minutes_until_close < self.entry_config.max_minutes_until_close:
            logger.debug("ENTRY_REJECT", {
                "reason": "too_close_to_resolution",
                "minutes_until_close": snapshot.minutes_until_close,
                "max_allowed": self.entry_config.max_minutes_until_close
            })
            return None
        
        # Price check
        entry_price = self._select_entry_price(snapshot)
        if entry_price is None:
            logger.debug("ENTRY_REJECT", {"reason": "no_entry_price"})
            return None
        
        if entry_price > self.entry_config.max_entry_price:
            logger.debug("ENTRY_REJECT", {
                "reason": "price_too_high",
                "entry_price": entry_price,
                "max": self.entry_config.max_entry_price
            })
            return None
        
        if entry_price < self.entry_config.min_entry_price:
            logger.debug("ENTRY_REJECT", {
                "reason": "price_too_low",
                "entry_price": entry_price,
                "min": self.entry_config.min_entry_price
            })
            return None
        
        # Exposure check
        if inventory.total_exposure >= self.position_config.max_total_exposure:
            logger.debug("ENTRY_REJECT", {
                "reason": "max_exposure_reached",
                "current": inventory.total_exposure,
                "max": self.position_config.max_total_exposure
            })
            return None
        
        # Concurrent position check
        if len(inventory.positions) >= self.position_config.max_concurrent_positions:
            logger.debug("ENTRY_REJECT", {
                "reason": "max_positions_reached",
                "current": len(inventory.positions),
                "max": self.position_config.max_concurrent_positions
            })
            return None
        
        # Calculate size
        size = self._calculate_entry_size(snapshot, inventory)
        if size <= 0:
            logger.debug("ENTRY_REJECT", {"reason": "size_zero"})
            return None
        
        # Determine side
        side, outcome = self._select_side(snapshot)
        
        logger.info("ENTRY_ACCEPTED", {
            "price": entry_price,
            "size": size,
            "outcome": outcome.value
        })
        
        return TradeIntent(
            action=TradeIntentAction.ENTER,
            token_id=snapshot.token_id,
            outcome=outcome,
            side=Side.BUY,
            price=entry_price,
            size=size,
            reason=f"Early entry: {outcome.value} @ ${entry_price:.3f}, {snapshot.minutes_since_open:.0f}m in",
            strategy_name=self.name,
            confidence=self._calculate_confidence(snapshot)
        )
    
    def _evaluate_exit(
        self,
        snapshot: MarketSnapshot,
        inventory: Inventory,
        position
    ) -> Optional[TradeIntent]:
        """Evaluate exit conditions"""
        
        current_price = snapshot.poly_best_bid  # Use bid for sell
        if current_price is None:
            return None
        
        # Update position's current price
        entry_price = position.entry_price
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check profit target
        if pnl_pct >= self.exit_config.profit_target_pct:
            return TradeIntent(
                action=TradeIntentAction.EXIT,
                token_id=snapshot.token_id,
                outcome=Outcome(position.outcome),
                side=Side.SELL,
                price=current_price,
                size=position.shares * current_price,
                reason=f"Profit target hit: {pnl_pct:.1f}% >= {self.exit_config.profit_target_pct}%",
                strategy_name=self.name,
                confidence=1.0
            )
        
        # Check stop loss (dynamic based on time remaining)
        stop_loss = self._get_dynamic_stop_loss(snapshot.minutes_until_close)
        if pnl_pct <= -stop_loss:
            return TradeIntent(
                action=TradeIntentAction.EXIT,
                token_id=snapshot.token_id,
                outcome=Outcome(position.outcome),
                side=Side.SELL,
                price=current_price,
                size=position.shares * current_price,
                reason=f"Stop loss hit: {pnl_pct:.1f}% <= -{stop_loss}%",
                strategy_name=self.name,
                confidence=1.0
            )
        
        # Check time-based exit
        if snapshot.minutes_until_close <= self.exit_config.exit_buffer_minutes:
            return TradeIntent(
                action=TradeIntentAction.EXIT,
                token_id=snapshot.token_id,
                outcome=Outcome(position.outcome),
                side=Side.SELL,
                price=current_price,
                size=position.shares * current_price,
                reason=f"Time exit: {snapshot.minutes_until_close:.0f}m until close",
                strategy_name=self.name,
                confidence=1.0
            )
        
        return None
    
    def _select_entry_price(self, snapshot: MarketSnapshot) -> Optional[float]:
        """Select the entry price based on configuration"""
        if self.entry_config.side_selection == "cheapest":
            # Use the lower of YES or NO mid price
            # For YES token, mid price is the YES price
            # NO price would be (1 - YES price) approximately
            return snapshot.poly_best_ask  # Buy at ask
        
        return snapshot.poly_best_ask
    
    def _select_side(self, snapshot: MarketSnapshot) -> tuple[Side, Outcome]:
        """Select which side to trade (YES or NO)"""
        if self.entry_config.side_selection == "cheapest":
            # If YES is cheap (< 0.50), buy YES; otherwise buy NO
            if snapshot.poly_mid_price and snapshot.poly_mid_price < 0.50:
                return Side.BUY, Outcome.YES
            else:
                return Side.BUY, Outcome.NO
        
        elif self.entry_config.side_selection == "yes_only":
            return Side.BUY, Outcome.YES
        
        elif self.entry_config.side_selection == "no_only":
            return Side.BUY, Outcome.NO
        
        # Default to YES
        return Side.BUY, Outcome.YES
    
    def _calculate_entry_size(self, snapshot: MarketSnapshot, inventory: Inventory) -> float:
        """Calculate position size in dollars"""
        max_size = self.position_config.max_position_size
        remaining_exposure = self.position_config.max_total_exposure - inventory.total_exposure
        
        return min(max_size, remaining_exposure)
    
    def _get_dynamic_stop_loss(self, minutes_until_close: float) -> float:
        """Get stop loss percentage based on time remaining"""
        if not self.exit_config.enable_time_based_stop:
            return self.exit_config.stop_loss_pct
        
        # Find the appropriate stop loss based on time
        for threshold_minutes, stop_pct in sorted(
            self.exit_config.stop_loss_tightening.items(),
            reverse=True
        ):
            if minutes_until_close <= threshold_minutes:
                return stop_pct
        
        return self.exit_config.stop_loss_pct
    
    def _calculate_confidence(self, snapshot: MarketSnapshot) -> float:
        """Calculate confidence score (0-1) for the trade"""
        confidence = 0.5  # Base confidence
        
        # Higher confidence for lower prices
        if snapshot.poly_mid_price:
            if snapshot.poly_mid_price < 0.20:
                confidence += 0.2
            elif snapshot.poly_mid_price < 0.35:
                confidence += 0.1
        
        # Higher confidence for tighter spreads
        if snapshot.poly_spread_pct:
            if snapshot.poly_spread_pct < 5:
                confidence += 0.2
            elif snapshot.poly_spread_pct < 10:
                confidence += 0.1
        
        return min(1.0, confidence)