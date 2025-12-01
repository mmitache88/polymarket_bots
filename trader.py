import json
import os
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY
from utils.db import get_opportunity_id, save_trade_to_db

# 1. Configuration
load_dotenv()
INPUT_FILE = "approved_trades.json"
MAX_SPEND_PER_TRADE = 2.00  # $2.00 USD per bet
MAX_SLIPPAGE = 0.002        # If price moved up by more than 0.2 cents, skip it
DRY_RUN = True  # Set to False for real trading

def get_client():
    creds = ApiCreds(
        api_key=os.getenv("API_KEY"),
        api_secret=os.getenv("API_SECRET"),
        api_passphrase=os.getenv("API_PASSPHRASE")
    )
    return ClobClient(
        host=os.getenv("HOST"),
        key=os.getenv("POLYGON_PRIVATE_KEY"), 
        chain_id=int(os.getenv("CHAIN_ID")), 
        creds=creds
    )

def calculate_position_size(trade):
    """Scale position size based on LLM conviction"""
    conviction = trade.get('analysis', {}).get('conviction', 'low')
    base_spend = MAX_SPEND_PER_TRADE
    
    if conviction == 'high':
        spend = base_spend * 2.5  # $5.00 for high conviction
    elif conviction == 'medium':
        spend = base_spend * 1.5  # $3.00 for medium
    else:
        spend = base_spend         # $2.00 for low
    
    price = trade.get('price', 0.001)
    if price <= 0: 
        price = 0.001
    
    size = int(spend / price)
    
    # Cap at max shares to avoid huge positions
    MAX_SHARES = 5000
    return min(size, MAX_SHARES), spend

def check_price_slippage(client, token_id, expected_price):
    """Verify current price hasn't moved too much since scan"""
    try:
        # Fetch current price from API
        current_data = client.get_price(token_id)  # Check exact method in docs
        current_price = current_data.get('price', expected_price)
        
        price_change = current_price - expected_price
        slippage_pct = (price_change / expected_price) * 100
        
        if abs(price_change) > MAX_SLIPPAGE:
            return False, f"Price moved {slippage_pct:+.1f}% (${expected_price:.4f} → ${current_price:.4f})"
        
        return True, current_price
    except Exception as e:
        print(f"   [!] Could not verify price: {e}")
        return False, f"API error: {e}"

def main():
    print("--- Polymarket Execution Engine Initialized ---")
    
    if DRY_RUN:
        print("⚠️  DRY RUN MODE - No real trades will be placed")
    
    # 2. Load Approved Trades
    if not os.path.exists(INPUT_FILE):
        print(f"File {INPUT_FILE} not found. Run analyst.py first.")
        return

    with open(INPUT_FILE, "r") as f:
        trades = json.load(f)

    if not trades:
        print("No approved trades found. Exiting.")
        return

    client = get_client()
    print(f"Loaded {len(trades)} approved trades. Checking existing orders...")

    # 3. Fetch Open Orders (To prevent double-buying)
    try:
        open_orders = client.get_orders()
        active_token_ids = set()
        for order in open_orders:
            active_token_ids.add(order.get('token_id'))
        print(f"You currently have {len(active_token_ids)} active orders. Skipping these.")
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        active_token_ids = set()

    # 4. Execution Loop
    trades_placed = 0
    
    for i, trade in enumerate(trades):
        token_id = trade.get('outcome_id')
        price = trade.get('price')
        question = trade.get('question')
        outcome_name = trade.get('outcome_name')
        market_id = trade.get('market_id')
        conviction = trade.get('analysis', {}).get('conviction', 'low')
        
        question_short = question[:50] + "..." if len(question) > 50 else question
        print(f"\n[{i+1}/{len(trades)}] {question_short}")
        print(f"   Outcome: {outcome_name} | Price: ${price:.4f} | Conviction: {conviction.upper()}")

        # Safety Checks
        if token_id in active_token_ids:
            print("   -> SKIPPING: Already have an active order for this token.")
            continue
        
        # Calculate Size with conviction scaling
        size, spend = calculate_position_size(trade)
        print(f"   -> Position: {size} shares (~${spend:.2f} spend)")

        # ADD SLIPPAGE CHECK HERE (before DRY_RUN):
        # Verify price hasn't moved too much
        price_ok, result = check_price_slippage(client, token_id, price)
        if not price_ok:
            print(f"   -> SKIPPING: {result}")
            continue
        
        # Update price if it changed slightly but is still acceptable
        if isinstance(result, float):
            price = result
            print(f"   -> Updated price to: ${price:.4f}")

        if DRY_RUN:
            print(f"   [DRY RUN] Would place: BUY {size} shares @ ${price:.4f}")
            trades_placed += 1
            continue
        
        try:
            # Create and Post Order
            resp = client.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=size,
                    side=BUY,
                    token_id=token_id
                )
            )
            
            # Check response for success
            if resp and resp.get('success'):
                order_id = resp.get('orderID')
                print(f"   >>> SUCCESS: Order Placed (ID: {order_id})")
                
                # Save to database for position tracking
                try:
                    opportunity_id = get_opportunity_id(market_id, token_id)
                    if opportunity_id:
                        save_trade_to_db(
                            opportunity_id, order_id, token_id, 
                            question, outcome_name, size, price, conviction
                        )
                        print(f"   -> Saved to position tracking database")
                except Exception as db_err:
                    print(f"   [Warning] Could not save to DB: {db_err}")
                
                trades_placed += 1
            else:
                print(f"   [!] FAILED: {resp}")
                
        except Exception as e:
            print(f"   [!] ERROR: {e}")
        
        # Sleep to be gentle on rate limits and gas
        time.sleep(1)

    print("\n" + "="*60)
    print(f"EXECUTION COMPLETE")
    print(f"Trades Placed: {trades_placed}/{len(trades)}")
    if DRY_RUN:
        print("⚠️  DRY RUN MODE - Set DRY_RUN=False to execute real trades")
    print("="*60)

if __name__ == "__main__":
    main()