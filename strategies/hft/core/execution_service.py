"""
Execution Service - Order Management

Handles order submission, tracking, and lifecycle management.
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Callable, Awaitable
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from ..models import (
    OrderRequest, OrderStatus, Side, Outcome,
    ExecutionReport, TradeIntentAction
)
from ..config import ExecutionConfig
from ..logger import get_logger

logger = get_logger(__name__)


class ExecutionService:
    """
    Manages order execution lifecycle.
    
    Responsibilities:
    - Submit orders to Polymarket
    - Track in-flight orders
    - Handle fills and cancellations
    - Manage order timeouts
    """
    
    def __init__(
        self,
        client,  # ClobClient from shared.polymarket_client
        config: ExecutionConfig,
        on_fill: Optional[Callable[[ExecutionReport], Awaitable[None]]] = None
    ):
        self.client = client
        self.config = config
        self.on_fill = on_fill
        
        # Order tracking
        self.pending_orders: Dict[str, OrderRequest] = {}
        self.order_history: List[ExecutionReport] = []
        self.cancelled_orders: set = set()
    
    async def execute(self, order_request: OrderRequest) -> ExecutionReport:
        """
        Execute an approved order request.
        
        Args:
            order_request: Approved order from RiskManager
            
        Returns:
            ExecutionReport with fill details or error
        """
        intent = order_request.intent
        
        logger.info({
            "event": "ORDER_SUBMIT",
            "token_id": intent.token_id,
            "side": intent.side.value,
            "action": intent.action.value,
            "price": intent.price,
            "size": intent.size
        })
        
        # Determine order side
        if intent.action == TradeIntentAction.ENTER:
            order_side = BUY
        else:  # EXIT
            order_side = SELL
        
        try:
            if self.config.dry_run:
                # Simulate order execution
                report = await self._simulate_execution(order_request)
            else:
                # Real order execution
                report = await self._execute_real(order_request, order_side)
            
            # Track order
            self.order_history.append(report)
            
            # Callback on fill
            if report.status == OrderStatus.FILLED and self.on_fill:
                await self.on_fill(report)
            
            logger.info({
                "event": "ORDER_RESULT",
                "order_id": report.order_id,
                "status": report.status.value,
                "filled_size": report.filled_size,
                "filled_price": report.filled_price
            })
            
            return report
            
        except Exception as e:
            logger.error({
                "event": "ORDER_ERROR",
                "token_id": intent.token_id,
                "error": str(e)
            })
            
            return ExecutionReport(
                order_id=None,
                order_request=order_request,
                status=OrderStatus.REJECTED,
                error_message=str(e)
            )
    
    async def _execute_real(
        self,
        order_request: OrderRequest,
        order_side: str
    ) -> ExecutionReport:
        """Execute real order on Polymarket"""
        intent = order_request.intent
        
        # Build order args
        order_args = OrderArgs(
            price=intent.price,
            size=intent.size,
            side=order_side,
            token_id=intent.token_id
        )
        
        # Create and sign order
        signed_order = self.client.create_and_post_order(order_args)
        
        # Parse response
        if signed_order and 'orderID' in signed_order:
            order_id = signed_order['orderID']
            
            # Track as pending
            self.pending_orders[order_id] = order_request
            
            # Wait for fill (with timeout)
            filled = await self._wait_for_fill(order_id)
            
            if filled:
                # Remove from pending
                self.pending_orders.pop(order_id, None)
                
                return ExecutionReport(
                    order_id=order_id,
                    order_request=order_request,
                    status=OrderStatus.FILLED,
                    filled_size=intent.size,
                    filled_price=intent.price,
                    filled_at=datetime.utcnow()
                )
            else:
                # Cancel unfilled order
                await self._cancel_order(order_id)
                
                # Remove from pending
                self.pending_orders.pop(order_id, None)
                
                return ExecutionReport(
                    order_id=order_id,
                    order_request=order_request,
                    status=OrderStatus.CANCELLED,
                    error_message="Order timeout - not filled within time limit"
                )
        else:
            # Order submission failed
            return ExecutionReport(
                order_id=None,
                order_request=order_request,
                status=OrderStatus.REJECTED,
                error_message="Order submission failed - no order ID returned"
            )
    
    async def _simulate_execution(self, order_request: OrderRequest) -> ExecutionReport:
        """Simulate order execution for dry run / mock mode"""
        intent = order_request.intent
        
        # Simulate network latency
        await asyncio.sleep(0.05)
        
        # Generate mock order ID
        order_id = f"mock_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        
        # Simulate fill (assume 100% fill rate in mock mode)
        return ExecutionReport(
            order_id=order_id,
            order_request=order_request,
            status=OrderStatus.FILLED,
            filled_size=intent.size,
            filled_price=intent.price,
            filled_at=datetime.utcnow()
        )
    
    async def _wait_for_fill(self, order_id: str) -> bool:
        """
        Wait for order to be filled.
        
        Args:
            order_id: Order ID to monitor
            
        Returns:
            True if filled, False if timeout
        """
        timeout = self.config.order_timeout_seconds
        poll_interval = 0.5  # Check every 500ms
        elapsed = 0.0
        
        while elapsed < timeout:
            # Check if order was cancelled externally
            if order_id in self.cancelled_orders:
                return False
            
            # Query order status
            try:
                order_status = self.client.get_order(order_id)
                
                if order_status:
                    status = order_status.get('status', '').lower()
                    
                    if status == 'filled':
                        return True
                    elif status in ('cancelled', 'expired', 'rejected'):
                        return False
                    # else: still pending, continue waiting
                    
            except Exception as e:
                logger.warning({
                    "event": "ORDER_STATUS_CHECK_FAILED",
                    "order_id": order_id,
                    "error": str(e)
                })
            
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        
        # Timeout reached
        logger.warning({
            "event": "ORDER_TIMEOUT",
            "order_id": order_id,
            "timeout_seconds": timeout
        })
        
        return False
    
    async def _cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        try:
            logger.info({
                "event": "ORDER_CANCEL_REQUEST",
                "order_id": order_id
            })
            
            result = self.client.cancel(order_id)
            
            self.cancelled_orders.add(order_id)
            self.pending_orders.pop(order_id, None)
            
            logger.info({
                "event": "ORDER_CANCELLED",
                "order_id": order_id
            })
            
            return True
            
        except Exception as e:
            logger.error({
                "event": "ORDER_CANCEL_FAILED",
                "order_id": order_id,
                "error": str(e)
            })
            return False
    
    async def cancel_all_orders(self) -> int:
        """
        Cancel all pending orders (emergency shutdown).
        
        Returns:
            Number of orders cancelled
        """
        logger.warning({
            "event": "CANCEL_ALL_ORDERS",
            "pending_count": len(self.pending_orders)
        })
        
        cancelled_count = 0
        
        # Copy keys to avoid dict modification during iteration
        order_ids = list(self.pending_orders.keys())
        
        for order_id in order_ids:
            success = await self._cancel_order(order_id)
            if success:
                cancelled_count += 1
        
        # Also try to cancel via bulk API if available
        try:
            self.client.cancel_all()
            logger.info({"event": "BULK_CANCEL_SENT"})
        except Exception as e:
            logger.warning({
                "event": "BULK_CANCEL_FAILED",
                "error": str(e)
            })
        
        logger.info({
            "event": "CANCEL_ALL_COMPLETE",
            "cancelled_count": cancelled_count
        })
        
        return cancelled_count
    
    def get_pending_orders(self) -> List[OrderRequest]:
        """Get list of pending orders"""
        return list(self.pending_orders.values())
    
    def get_order_history(
        self,
        status: Optional[OrderStatus] = None,
        limit: int = 100
    ) -> List[ExecutionReport]:
        """
        Get order history.
        
        Args:
            status: Filter by status (None for all)
            limit: Max number of orders to return
            
        Returns:
            List of execution reports
        """
        history = self.order_history
        
        if status:
            history = [r for r in history if r.status == status]
        
        return history[-limit:]
    
    def get_fill_rate(self) -> float:
        """Calculate fill rate percentage"""
        if not self.order_history:
            return 0.0
        
        filled = sum(1 for r in self.order_history if r.status == OrderStatus.FILLED)
        return (filled / len(self.order_history)) * 100
    
    def get_stats(self) -> dict:
        """Get execution statistics"""
        total_orders = len(self.order_history)
        filled_orders = sum(1 for r in self.order_history if r.status == OrderStatus.FILLED)
        rejected_orders = sum(1 for r in self.order_history if r.status == OrderStatus.REJECTED)
        cancelled_orders = sum(1 for r in self.order_history if r.status == OrderStatus.CANCELLED)
        
        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "rejected_orders": rejected_orders,
            "cancelled_orders": cancelled_orders,
            "pending_orders": len(self.pending_orders),
            "fill_rate_pct": self.get_fill_rate()
        }