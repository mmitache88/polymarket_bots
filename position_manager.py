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
    """Fetch current market price for a token (best bid - what we can sell at)"""
    try:
        order_book = client.get_order_book(token_id)
        
        if hasattr(order_book, 'bids') and order_book.bids:
            # Sort bids descending to get HIGHEST bid (best price to sell at)
            sorted_bids = sorted(order_book.bids, key=lambda x: float(x.price), reverse=True)
            return float(sorted_bids[0].price)
        
        logger.warning(f"No bids available for {token_id[:20]}...")
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
    logger.info(f"Check Interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL//60} minutes)")
    logger.info(f"Profit Targets: 5x (after {MIN_HOLD_DAYS}d), 10x (immediate)")
    logger.info(f"Max Hold: {MAX_HOLD_DAYS} days")
    logger.info("=" * 60)
    
    client = get_client()
    
    while True:
        try:
            positions = get_open_positions()
            
            if not positions:
                logger.info(f"No open positions to monitor.")
            else:
                logger.info(f"Monitoring {len(positions)} positions...")
                
                for pos in positions:
                    token_id = pos['token_id']
                    question = pos['market_question'][:50]
                    
                    current_price = get_current_price(client, token_id)
                    pos['current_price'] = current_price
                    
                    should_sell, reason = should_exit_position(pos)
                    
                    entry_price = pos['entry_price']
                    profit_pct = ((current_price / entry_price - 1) * 100) if current_price and entry_price > 0 else 0
                    
                    logger.info(f"  • {question}")
                    logger.info(f"    Entry: ${entry_price:.4f} → Current: ${current_price:.4f} ({profit_pct:+.1f}%)")
                    logger.info(f"    Status: {reason}")
                    
                    if should_sell:
                        logger.info(f"    🎯 SELLING {pos['shares']} shares...")
                        
                        try:
                            resp = client.create_and_post_order(
                                OrderArgs(
                                    price=current_price,
                                    size=pos['shares'],
                                    side=SELL,
                                    token_id=token_id
                                )
                            )
                            
                            if resp and resp.get('success'):
                                logger.info(f"    ✅ SOLD: Order ID {resp.get('orderID')}")
                                update_position_exit(pos['trade_id'], current_price)
                            else:
                                logger.error(f"    ❌ SELL FAILED: {resp}")
                        
                        except Exception as e:
                            logger.error(f"    ❌ ERROR: {e}", exc_info=True)
            
            time.sleep(CHECK_INTERVAL)
        
        except KeyboardInterrupt:
            logger.info("Position Manager Stopped by User")
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    monitor_positions()