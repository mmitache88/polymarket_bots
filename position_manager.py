import time
from datetime import datetime, timedelta
from trader import get_client
from utils.db import get_open_positions, update_position_exit
from utils.logger import setup_logger
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import SELL

# Setup logger
logger = setup_logger('position_manager')

# Configuration
CHECK_INTERVAL = 300  # Check every 5 minutes
PROFIT_TARGET_5X = 5.0
PROFIT_TARGET_10X = 10.0
MAX_HOLD_DAYS = 30
MIN_HOLD_DAYS = 7  # Don't sell before 1 week unless 10x

def get_current_price(client, token_id):
    """Fetch current market price for a token (mid-price between best bid and ask)"""
    try:
        order_book = client.get_order_book(token_id)
        
        best_bid = None
        best_ask = None
        
        if hasattr(order_book, 'bids') and order_book.bids:
            sorted_bids = sorted(order_book.bids, key=lambda x: float(x.price), reverse=True)
            best_bid = float(sorted_bids[0].price)
        
        if hasattr(order_book, 'asks') and order_book.asks:
            sorted_asks = sorted(order_book.asks, key=lambda x: float(x.price))
            best_ask = float(sorted_asks[0].price)
        
        # Calculate mid-price if both bid and ask exist
        if best_bid and best_ask:
            mid_price = (best_bid + best_ask) / 2
            return mid_price
        elif best_ask:
            # No bids, use lowest ask
            return best_ask
        elif best_bid:
            # No asks, use highest bid
            return best_bid
        
        logger.warning(f"No bids or asks available for {token_id[:20]}...")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching price for {token_id[:20]}...: {e}")
        return None

def should_exit_position(position):
    """Determine if position should be closed"""
    entry_price = position['entry_price']
    current_price = position.get('current_price')
    entry_date = datetime.fromisoformat(position['entry_date'])
    days_held = (datetime.now() - entry_date).days
    
    if not current_price:
        return False, "No current price available"
    
    profit_multiple = current_price / entry_price if entry_price > 0 else 0
    
    if profit_multiple >= PROFIT_TARGET_10X:
        return True, f"10x profit target hit ({profit_multiple:.1f}x)"
    
    if profit_multiple >= PROFIT_TARGET_5X and days_held >= MIN_HOLD_DAYS:
        return True, f"5x profit after {days_held} days ({profit_multiple:.1f}x)"
    
    if days_held >= MAX_HOLD_DAYS:
        return True, f"Max hold duration reached ({days_held} days, {profit_multiple:.1f}x)"
    
    return False, f"Holding ({days_held}d, {profit_multiple:.1f}x)"

def monitor_positions():
    """Main monitoring loop"""
    logger.info("=" * 60)
    logger.info("Position Manager Started")
    logger.info("=" * 60)
    logger.info(f"Check Interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL // 60} minutes)")
    logger.info(f"Profit Targets: {PROFIT_TARGET_5X}x (after {MIN_HOLD_DAYS}d), {PROFIT_TARGET_10X}x (immediate)")
    logger.info(f"Max Hold: {MAX_HOLD_DAYS} days")
    logger.info("=" * 60)
    
    client = get_client()
    
    while True:
        try:
            positions = get_open_positions()
            
            if not positions:
                logger.info("No open positions to monitor.")
                time.sleep(CHECK_INTERVAL)
                continue
            
            logger.info(f"Monitoring {len(positions)} positions...")
            
            for pos in positions:
                token_id = pos['token_id']
                entry_price = pos['entry_price']
                shares = pos['shares']
                question = pos.get('market_question', 'Unknown')[:50]  # Changed from 'question'
                entry_date = pos.get('entry_date')
                
                logger.info(f"  • {question}")
                
                # Get current price
                current_price = get_current_price(client, token_id)
                
                # Handle case where price is unavailable
                if current_price is None:
                    logger.warning(f"    ⚠️ Could not fetch price - market may be closed or inactive")
                    continue
                
                # Calculate metrics
                profit_pct = ((current_price - entry_price) / entry_price) * 100
                multiplier = current_price / entry_price if entry_price > 0 else 0
                
                # Calculate days held
                if entry_date:
                    days_held = (datetime.now() - datetime.fromisoformat(entry_date)).days
                else:
                    days_held = 0
                
                logger.info(f"    Entry: ${entry_price:.4f} → Current: ${current_price:.4f} ({profit_pct:+.1f}%)")
                
                # Check sell conditions using existing function
                pos['current_price'] = current_price  # Add current price to position dict
                should_sell, reason = should_exit_position(pos)
                
                logger.info(f"    Status: {reason}")
                
                if should_sell:
                    logger.info(f"    🚨 SELL SIGNAL: {reason}")
                    # Execute sell logic here
                    # execute_sell(client, pos, current_price)
                
                time.sleep(0.5)  # Rate limiting between positions
            
            logger.info(f"Next check in {CHECK_INTERVAL // 60} minutes...")
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            time.sleep(60)  # Wait a minute before retrying


if __name__ == "__main__":
    monitor_positions()