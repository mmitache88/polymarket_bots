import asyncio
import os
import sys
from typing import List

# Ensure Python can find your modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import your Scraper and Config modules
# (Adjust these import paths if your file names differ)
from shared.playwright_fetch_hourly_markets import fetch_btc_hourly_markets
from strategies.hft.config import load_config, save_config, HFTConfig

async def main():
    print("🚀 Starting Market Update...")

    # 1. Fetch the fresh market data
    markets = await fetch_btc_hourly_markets()

    if not markets:
        print("❌ No markets found. Config will NOT be updated.")
        return

    # 2. Extract the Token IDs
    # We collect BOTH Yes and No tokens so the bot can choose which side to trade
    new_token_ids = []
    market_names = []

    for market in markets:
        new_token_ids.append(market['yes_token'])
        new_token_ids.append(market['no_token'])
        market_names.append(market['question'])

    print(f"✅ Captured {len(new_token_ids)} tokens from {len(market_names)} market(s).")

    # 2.5. Validate tokens before updating config
    print("\n🔍 Validating token IDs...")
    if not await validate_token_ids(new_token_ids):
        print("❌ Token validation failed. Config will NOT be updated.")
        return
    
    print("✅ All tokens validated successfully")

    # 3. Load the existing configuration
    config_path = "strategies/hft/config.json"
    
    # Create the directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    # Load current config (or defaults if file doesn't exist)
    current_config = load_config(config_path)

    # 4. Update the 'market' section
    # We overwrite the old list because hourly markets expire quickly
    current_config.market.token_ids = new_token_ids
    
    # Optional: Enable live mode automatically if we found valid markets?
    # current_config.execution.dry_run = False 

    # 5. Save the updated config to disk
    save_config(current_config, config_path)

    print("\n" + "="*50)
    print(f"💾 CONFIG UPDATED: {config_path}")
    print("="*50)
    print(f"Active Market: {market_names[0]}")
    print(f"Token IDs set: {len(current_config.market.token_ids)}")
    print("You can now restart your trading bot to pick up the new ID.")

async def validate_token_ids(token_ids: List[str]) -> bool:
    """Verify tokens exist on CLOB before updating config"""
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON
    
    # Initialize client (no authentication needed for read-only operations)
    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=POLYGON
    )
    
    for token_id in token_ids:
        try:
            book = client.get_order_book(token_id)
            if not book or (not book.bids and not book.asks):
                print(f"❌ No liquidity for {token_id}")
                return False
            print(f"✅ Token {token_id} validated (has orderbook)")
        except Exception as e:
            print(f"❌ Token {token_id} invalid: {e}")
            return False
    
    return True

if __name__ == "__main__":
    asyncio.run(main())