import time
import json
import os
from datetime import datetime, timedelta
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import SELL
from shared.polymarket_client import get_client
from shared.db import get_open_positions, update_position_exit, save_position_snapshot, init_db
from shared.logger import setup_logger


# Setup logger
logger = setup_logger('position_manager')

# Configuration
CHECK_INTERVAL = 300  # Check every 5 minutes
PROFIT_TARGET_5X = 5.0
PROFIT_TARGET_10X = 10.0
MAX_HOLD_DAYS = 30
MIN_HOLD_DAYS = 7  # Don't sell before 1 week unless 10x
POSITION_HISTORY_DIR = "data/position_history"

# Ensure directories exist
os.makedirs(POSITION_HISTORY_DIR, exist_ok=True)

def get_market_prices(client, token_id):
    """Fetch all market prices for a token (bid, ask, mid)"""
    try:
        order_book = client.get_order_book(token_id)
        
        best_bid = None
        best_ask = None
        bid_liquidity = 0
        
        if hasattr(order_book, 'bids') and order_book.bids:
            sorted_bids = sorted(order_book.bids, key=lambda x: float(x.price), reverse=True)
            best_bid = float(sorted_bids[0].price)
            bid_liquidity = sum(float(bid.size) for bid in order_book.bids)
        
        if hasattr(order_book, 'asks') and order_book.asks:
            sorted_asks = sorted(order_book.asks, key=lambda x: float(x.price))
            best_ask = float(sorted_asks[0].price)
        
        # Calculate mid-price
        mid_price = None
        if best_bid and best_ask:
            mid_price = (best_bid + best_ask) / 2
        
        # Calculate spread
        spread = None
        if best_bid and best_ask:
            spread = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 0
        
        return {
            'best_bid': best_bid,       # Realistic sell price
            'best_ask': best_ask,       # Price to buy more
            'mid_price': mid_price,     # What Polymarket shows
            'spread': spread,           # Bid-ask spread %
            'bid_liquidity': bid_liquidity  # Total shares in bids
        }
        
    except Exception as e:
        logger.error(f"Error fetching prices for {token_id[:20]}...: {e}")
        return None

def should_exit_position(position):
    """Determine if position should be closed (based on REALISTIC sell price)"""
    entry_price = position['entry_price']
    sell_price = position.get('sell_price')  # Use best bid, not mid
    entry_date = datetime.fromisoformat(position['entry_date'])
    days_held = (datetime.now() - entry_date).days
    
    if not sell_price:
        return False, "No sell price available"
    
    profit_multiple = sell_price / entry_price if entry_price > 0 else 0
    
    if profit_multiple >= PROFIT_TARGET_10X:
        return True, f"10x profit target hit ({profit_multiple:.1f}x)"
    
    if profit_multiple >= PROFIT_TARGET_5X and days_held >= MIN_HOLD_DAYS:
        return True, f"5x profit after {days_held} days ({profit_multiple:.1f}x)"
    
    if days_held >= MAX_HOLD_DAYS:
        return True, f"Max hold duration reached ({days_held} days, {profit_multiple:.1f}x)"
    
    return False, f"Holding ({days_held}d, {profit_multiple:.1f}x)"

def save_snapshot_to_json(snapshots, timestamp):
    """Save position snapshots to JSON file"""
    filename = f"{POSITION_HISTORY_DIR}/snapshot_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump({
            'timestamp': timestamp,
            'snapshot_count': len(snapshots),
            'positions': snapshots
        }, f, indent=2, default=str)
    
    logger.info(f"💾 Saved snapshot to {filename}")
    return filename

def monitor_positions():
    """Main monitoring loop"""
    # Initialize database
    init_db()
    
    logger.info("=" * 60)
    logger.info("Position Manager Started")
    logger.info("=" * 60)
    logger.info(f"Check Interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL // 60} minutes)")
    logger.info(f"Profit Targets: {PROFIT_TARGET_5X}x (after {MIN_HOLD_DAYS}d), {PROFIT_TARGET_10X}x (immediate)")
    logger.info(f"Max Hold: {MAX_HOLD_DAYS} days")
    logger.info(f"History Directory: {POSITION_HISTORY_DIR}/")
    logger.info("=" * 60)
    
    client = get_client("longshot")
    
    while True:
        try:
            positions = get_open_positions()
            
            if not positions:
                logger.info("No open positions to monitor.")
                time.sleep(CHECK_INTERVAL)
                continue
            
            logger.info(f"Monitoring {len(positions)} positions...")
            
            # Collect all snapshots for JSON export
            current_snapshots = []
            snapshot_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            for pos in positions:
                trade_id = pos.get('trade_id')
                token_id = pos['token_id']
                entry_price = pos['entry_price']
                shares = pos['shares']
                question = pos.get('market_question', 'Unknown')
                question_short = question[:50]
                entry_date = pos.get('entry_date')
                
                logger.info(f"  • {question_short}")
                
                # Get all market prices
                prices = get_market_prices(client, token_id)
                
                # Handle case where prices are unavailable
                if prices is None or prices['best_bid'] is None:
                    logger.warning(f"    ⚠️ No bids available - cannot sell!")
                    continue
                
                best_bid = prices['best_bid']
                best_ask = prices['best_ask']
                mid_price = prices['mid_price']
                spread = prices['spread']
                bid_liquidity = prices['bid_liquidity']
                
                # Calculate realistic P/L (based on what we can actually sell at)
                realistic_profit_pct = ((best_bid - entry_price) / entry_price) * 100
                realistic_multiplier = best_bid / entry_price if entry_price > 0 else 0
                
                # Calculate days held
                if entry_date:
                    days_held = (datetime.now() - datetime.fromisoformat(entry_date)).days
                else:
                    days_held = 0
                
                # Show both mid-price (what Polymarket shows) and realistic sell price
                logger.info(f"    Entry: ${entry_price:.4f}")
                logger.info(f"    Mid-Price (Polymarket shows): ${mid_price:.4f}" if mid_price else "    Mid-Price: N/A")
                logger.info(f"    Realistic Sell Price (Best Bid): ${best_bid:.4f} ({realistic_profit_pct:+.1f}%)")
                
                # Warn about wide spreads
                if spread and spread > 50:
                    logger.warning(f"    ⚠️ WIDE SPREAD: {spread:.0f}% - Low liquidity!")
                
                # Warn about low bid liquidity
                if bid_liquidity < shares:
                    logger.warning(f"    ⚠️ LOW LIQUIDITY: Only {bid_liquidity:.0f} shares in bids (you have {shares:.0f})")
                
                # Check sell conditions using REALISTIC price
                pos['sell_price'] = best_bid  # Use best bid for exit decisions
                should_sell, reason = should_exit_position(pos)
                
                logger.info(f"    Status: {reason}")
                
                if should_sell:
                    logger.info(f"    🚨 SELL SIGNAL: {reason}")
                    # Execute sell logic here
                    # execute_sell(client, pos, best_bid)
                
                # Create snapshot data
                snapshot_data = {
                    'trade_id': trade_id,
                    'token_id': token_id,
                    'market_question': question,
                    'snapshot_time': datetime.now().isoformat(),
                    'entry_price': entry_price,
                    'mid_price': mid_price,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'spread': spread,
                    'bid_liquidity': bid_liquidity,
                    'shares': shares,
                    'profit_pct': realistic_profit_pct,
                    'multiplier': realistic_multiplier,
                    'days_held': days_held,
                    'status': reason
                }
                
                # Save to database
                try:
                    save_position_snapshot(
                        trade_id=trade_id,
                        token_id=token_id,
                        market_question=question,
                        entry_price=entry_price,
                        mid_price=mid_price,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread=spread,
                        bid_liquidity=bid_liquidity,
                        shares=shares,
                        profit_pct=realistic_profit_pct,
                        multiplier=realistic_multiplier,
                        days_held=days_held,
                        status=reason
                    )
                except Exception as db_err:
                    logger.warning(f"    ⚠️ Could not save to DB: {db_err}")
                
                # Add to JSON export list
                current_snapshots.append(snapshot_data)
                
                time.sleep(0.5)  # Rate limiting between positions
            
            # Save all snapshots to JSON file
            if current_snapshots:
                save_snapshot_to_json(current_snapshots, snapshot_timestamp)
            
            logger.info(f"✅ Saved {len(current_snapshots)} position snapshots")
            logger.info(f"Next check in {CHECK_INTERVAL // 60} minutes...")
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            time.sleep(60)  # Wait a minute before retrying


if __name__ == "__main__":
    monitor_positions()