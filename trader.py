import json
import os
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY

# 1. Configuration
load_dotenv()
INPUT_FILE = "approved_trades.json"
MAX_SPEND_PER_TRADE = 2.00  # $2.00 USD per bet
MAX_SLIPPAGE = 0.002        # If price moved up by more than 0.2 cents, skip it

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

def main():
    print("--- Polymarket Execution Engine Initialized ---")
    
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
    # We fetch all open orders to build a set of 'token_ids' we are already bidding on
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
    for i, trade in enumerate(trades):
        token_id = trade.get('outcome_id') # User's scanner calls this outcome_id
        price = trade.get('price')
        question = trade.get('question')[:50]
        
        print(f"\nProcessing [{i+1}/{len(trades)}]: {question}...")

        # Safety Checks
        if token_id in active_token_ids:
            print("   -> SKIPPING: Already have an active order for this token.")
            continue
        
        # Calculate Size (Shares) based on $2.00 spend
        # Example: $2.00 / $0.002 price = 1000 shares
        if price <= 0: price = 0.001 # Safety for div by zero
        size = MAX_SPEND_PER_TRADE / price
        
        # Round size to avoid API errors (usually integer shares are safest for dust)
        size = int(size)

        print(f"   -> Placing Limit Buy: {size} shares @ ${price}")
        
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
                print(f"   >>> SUCCESS: Order Placed (ID: {resp.get('orderID')})")
            else:
                print(f"   [!] FAILED: {resp}")
                
        except Exception as e:
            print(f"   [!] ERROR: {e}")
        
        # Sleep to be gentle on rate limits and gas
        time.sleep(1)

    print("\n--- Execution Complete ---")

if __name__ == "__main__":
    main()