import time
from datetime import datetime, timedelta
from trader import get_client
from utils.db import get_open_positions, update_position_exit
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import SELL

# Configuration
CHECK_INTERVAL = 300  # Check every 5 minutes
PROFIT_TARGET_5X = 5.0
PROFIT_TARGET_10X = 10.0
MAX_HOLD_DAYS = 30
MIN_HOLD_DAYS = 7  # Don't sell before 1 week unless 10x

def get_current_price(client, token_id):
    """Fetch current market price for a token"""
    try:
        # Check py_clob_client docs for exact method
        market = client.get_market(token_id=token_id)
        # This depends on API structure - adjust as needed
        return market.get('price', None)
    except Exception as e:
        print(f"Error fetching price for {token_id}: {e}")
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
    
    # Exit conditions
    if profit_multiple >= PROFIT_TARGET_10X:
        return True, f"10x profit target hit ({profit_multiple:.1f}x)"
    
    if profit_multiple >= PROFIT_TARGET_5X and days_held >= MIN_HOLD_DAYS:
        return True, f"5x profit after {days_held} days ({profit_multiple:.1f}x)"
    
    if days_held >= MAX_HOLD_DAYS:
        return True, f"Max hold duration reached ({days_held} days, {profit_multiple:.1f}x)"
    
    return False, f"Holding ({days_held}d, {profit_multiple:.1f}x)"

def monitor_positions():
    """Main monitoring loop"""
    print("="*60)
    print("🔍 Position Manager Started")
    print("="*60)
    print(f"Check Interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL//60} minutes)")
    print(f"Profit Targets: 5x (after {MIN_HOLD_DAYS}d), 10x (immediate)")
    print(f"Max Hold: {MAX_HOLD_DAYS} days")
    print("="*60)
    
    client = get_client()
    
    while True:
        try:
            positions = get_open_positions()
            
            if not positions:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No open positions to monitor.")
            else:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Monitoring {len(positions)} positions...")
                
                for pos in positions:
                    token_id = pos['token_id']
                    question = pos['market_question'][:50]
                    
                    # Fetch current price
                    current_price = get_current_price(client, token_id)
                    pos['current_price'] = current_price
                    
                    # Check exit conditions
                    should_sell, reason = should_exit_position(pos)
                    
                    entry_price = pos['entry_price']
                    profit_pct = ((current_price / entry_price - 1) * 100) if current_price and entry_price > 0 else 0
                    
                    print(f"  • {question}")
                    print(f"    Entry: ${entry_price:.4f} → Current: ${current_price:.4f} ({profit_pct:+.1f}%)")
                    print(f"    Status: {reason}")
                    
                    if should_sell:
                        print(f"    🎯 SELLING {pos['shares']} shares...")
                        
                        try:
                            # Place sell order
                            resp = client.create_and_post_order(
                                OrderArgs(
                                    price=current_price,
                                    size=pos['shares'],
                                    side=SELL,
                                    token_id=token_id
                                )
                            )
                            
                            if resp and resp.get('success'):
                                print(f"    ✅ SOLD: Order ID {resp.get('orderID')}")
                                update_position_exit(pos['trade_id'], current_price)
                            else:
                                print(f"    ❌ SELL FAILED: {resp}")
                        
                        except Exception as e:
                            print(f"    ❌ ERROR: {e}")
            
            # Wait before next check
            time.sleep(CHECK_INTERVAL)
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Position Manager Stopped by User")
            break
        except Exception as e:
            print(f"\n❌ Error in monitoring loop: {e}")
            time.sleep(60)  # Wait 1 minute before retrying

if __name__ == "__main__":
    monitor_positions()