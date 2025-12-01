import json
import os
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.order_builder.constants import BUY
from utils.db import get_opportunity_id, save_trade_to_db
from utils.logger import setup_logger

# Setup logger
logger = setup_logger('trader')

# 1. Configuration
load_dotenv()
INPUT_FILE = "approved_trades.json"
MAX_TOTAL_EXPOSURE = 50.00  # Max $50 total capital deployed
MAX_POSITIONS = 20          # Max number of concurrent positions
MAX_PER_MARKET = 10.00      # Max $10 per market (prevent concentration)
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
        spend = base_spend * 2.5
    elif conviction == 'medium':
        spend = base_spend * 1.5
    else:
        spend = base_spend
    
    price = trade.get('price', 0.001)
    if price <= 0: 
        price = 0.001
    
    size = int(spend / price)
    MAX_SHARES = 5000
    return min(size, MAX_SHARES), spend

def check_price_slippage(client, token_id, expected_price):
    """Verify current price hasn't moved too much since scan"""
    try:
        current_data = client.get_price(token_id)
        current_price = current_data.get('price', expected_price)
        
        price_change = current_price - expected_price
        slippage_pct = (price_change / expected_price) * 100
        
        if abs(price_change) > MAX_SLIPPAGE:
            return False, f"Price moved {slippage_pct:+.1f}% (${expected_price:.4f} → ${current_price:.4f})"
        
        return True, current_price
    except Exception as e:
        logger.warning(f"Could not verify price: {e}")
        return False, f"API error: {e}"

def check_portfolio_limits():
    """Ensure we don't exceed risk limits"""
    from utils.db import get_open_positions
    
    positions = get_open_positions()
    
    if len(positions) >= MAX_POSITIONS:
        return False, f"Already at max positions ({MAX_POSITIONS})"
    
    total_exposure = sum(p['shares'] * p['entry_price'] for p in positions)
    
    if total_exposure >= MAX_TOTAL_EXPOSURE:
        return False, f"Total exposure ${total_exposure:.2f} exceeds limit ${MAX_TOTAL_EXPOSURE}"
    
    return True, total_exposure

def main():
    logger.info("=" * 60)
    logger.info("Polymarket Execution Engine Initialized")
    logger.info("=" * 60)
    
    if DRY_RUN:
        logger.warning("DRY RUN MODE - No real trades will be placed")
    
    # Load Approved Trades
    if not os.path.exists(INPUT_FILE):
        logger.error(f"File {INPUT_FILE} not found. Run analyst.py first.")
        return

    with open(INPUT_FILE, "r") as f:
        trades = json.load(f)

    if not trades:
        logger.warning("No approved trades found. Exiting.")
        return
    
    # Check portfolio limits
    limits_ok, current_exposure = check_portfolio_limits()
    if not limits_ok:
        logger.warning(f"PORTFOLIO LIMIT REACHED: {current_exposure}")
        logger.warning("Cannot place new trades. Wait for existing positions to close.")
        return
    
    logger.info(f"Current exposure: ${current_exposure:.2f} / ${MAX_TOTAL_EXPOSURE}")

    client = get_client()
    logger.info(f"Loaded {len(trades)} approved trades. Checking existing orders...")

    # Fetch Open Orders
    try:
        open_orders = client.get_orders()
        active_token_ids = set()
        for order in open_orders:
            active_token_ids.add(order.get('token_id'))
        logger.info(f"You currently have {len(active_token_ids)} active orders. Skipping these.")
    except Exception as e:
        logger.warning(f"Could not fetch open orders (continuing anyway): {e}")
        active_token_ids = set()

    # Execution Loop
    trades_placed = 0
    
    for i, trade in enumerate(trades):
        token_id = trade.get('outcome_id')
        price = trade.get('price')
        question = trade.get('question')
        outcome_name = trade.get('outcome_name')
        market_id = trade.get('market_id')
        conviction = trade.get('analysis', {}).get('conviction', 'low')
        
        question_short = question[:50] + "..." if len(question) > 50 else question
        logger.info(f"\n[{i+1}/{len(trades)}] {question_short}")
        logger.info(f"   Outcome: {outcome_name} | Price: ${price:.4f} | Conviction: {conviction.upper()}")

        # Safety Checks
        if token_id in active_token_ids:
            logger.info("   -> SKIPPING: Already have an active order for this token.")
            continue
        
        # Calculate Size
        size, spend = calculate_position_size(trade)
        logger.info(f"   -> Position: {size} shares (~${spend:.2f} spend)")

        # Check slippage (only in real mode)
        if not DRY_RUN:
            price_ok, result = check_price_slippage(client, token_id, price)
            if not price_ok:
                logger.warning(f"   -> SKIPPING: {result}")
                continue
        
            if isinstance(result, float):
                price = result
                logger.info(f"   -> Updated price to: ${price:.4f}")

        if DRY_RUN:
            logger.info(f"   [DRY RUN] Would place: BUY {size} shares @ ${price:.4f}")
            trades_placed += 1
            continue
        
        try:
            # Place Order
            resp = client.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=size,
                    side=BUY,
                    token_id=token_id
                )
            )
            
            if resp and resp.get('success'):
                order_id = resp.get('orderID')
                logger.info(f"   >>> SUCCESS: Order Placed (ID: {order_id})")
                
                # Save to database
                try:
                    opportunity_id = get_opportunity_id(market_id, token_id)
                    if opportunity_id:
                        save_trade_to_db(
                            opportunity_id, order_id, token_id, 
                            question, outcome_name, size, price, conviction
                        )
                        logger.info(f"   -> Saved to position tracking database")
                except Exception as db_err:
                    logger.warning(f"Could not save to DB: {db_err}")
                
                trades_placed += 1
            else:
                logger.error(f"   FAILED: {resp}")
                
        except Exception as e:
            logger.error(f"   ERROR placing order: {e}", exc_info=True)
        
        time.sleep(1)

    logger.info("=" * 60)
    logger.info(f"EXECUTION COMPLETE")
    logger.info(f"Trades Placed: {trades_placed}/{len(trades)}")
    if DRY_RUN:
        logger.warning("DRY RUN MODE - Set DRY_RUN=False to execute real trades")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()