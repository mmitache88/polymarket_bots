"""
Base strategy interface for HFT strategies

All strategies must implement this interface to be pluggable.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..models import MarketSnapshot, Inventory, TradeIntent


class BaseStrategy(ABC):
    """
    Abstract base class for HFT strategies.
    
    Strategies are:
    - Stateless: All state is passed in via MarketSnapshot and Inventory
    - Synchronous: No async operations allowed
    - Deterministic: Same inputs should produce same outputs
    - Pure: No side effects, only returns TradeIntent
    """
    
    name: str = "base"
    
    @abstractmethod
    def evaluate(
        self,
        snapshot: MarketSnapshot,
        inventory: Inventory
    ) -> Optional[TradeIntent]:
        """
        Evaluate current market state and decide on action.
        
        Args:
            snapshot: Current market state from all data sources
            inventory: Current positions and cash
        
        Returns:
            TradeIntent if action should be taken, None otherwise
        """
        pass
    
    def should_enter(self, snapshot: MarketSnapshot, inventory: Inventory) -> bool:
        """Check if conditions are met for entry"""
        return False
    
    def should_exit(self, snapshot: MarketSnapshot, inventory: Inventory) -> bool:
        """Check if conditions are met for exit"""
        return False
    
    def calculate_size(self, snapshot: MarketSnapshot, inventory: Inventory) -> float:
        """Calculate position size in dollars"""
        return 0.0