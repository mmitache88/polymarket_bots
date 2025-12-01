import os
import time
import json
from dotenv import load_dotenv
from time import sleep
from datetime import datetime, timezone, timedelta
from utils.helpers import (
    safe_get_start_date,
    is_recent_market,
    market_age_days,
    safe_get_price,
    safe_get_outcome_id,
    safe_get_outcome_name,
    safe_get_market_id,
    parse_end_date,
    safe_get_volume
)
from utils.db import init_db, save_scan_to_db

load_dotenv()

# Config
MAX_PRICE = 0.05            # $0.05 = 5 cents
MIN_PRICE = 0.0001          # ignore zero/near-zero if you want to skip
MAX_PAGES = 100
PAGE_DELAY = 0.25           # seconds between page requests (be friendly to API)
MIN_VOLUME = 0.0            # set >0 to filter dead markets (depends on API field)
OUTPUT_FILE = "opportunities.json"
PAGE_SIZE = 100             # if your client supports page_size param
RECENT_DAYS = 90     # consider markets launched within the last N days "recent"
OUTPUT_FILE = "opportunities.json"  # Keep this for analyst.py
ARCHIVE_DIR = "scan_history"  # New: archive past scans

# Optional: tweak environment variable names below to match your .env
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")
HOST = os.getenv("HOST")
POLYGON_PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
CHAIN_ID = os.getenv("CHAIN_ID")


def exponential_backoff_request(func, *args, retries=4, base_delay=0.5, **kwargs):
    last_exc = None
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            sleep(base_delay * (2 ** i))
    raise last_exc


def build_client():
    """Construct your py_clob_client client. Adjust args to your client constructor."""
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    creds = ApiCreds(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE
    )

    client = ClobClient(
        host=HOST,
        key=POLYGON_PRIVATE_KEY,
        chain_id=int(CHAIN_ID) if CHAIN_ID else None,
        creds=creds
    )
    return client


def scan_markets():
    init_db()
    
    client = build_client()

    next_cursor = None
    page_count = 0
    total_scanned = 0
    opportunities = []
    seen_markets = set()

    print("--- Polymarket Deep Probe Initialized ---")

    while page_count < MAX_PAGES:
        page_count += 1
        try:
            # If your client accepts next_cursor param and page_size, adapt accordingly:
            if next_cursor:
                resp = exponential_backoff_request(client.get_markets, next_cursor=next_cursor)
            else:
                resp = exponential_backoff_request(client.get_markets)

        except Exception as e:
            print(f"[ERROR] Failed to fetch page {page_count}: {e}")
            break

        # Defensive unpacking
        markets = resp.get("data") or resp.get("markets") or resp.get("results") or []
        next_cursor = resp.get("next_cursor") or resp.get("cursor") or resp.get("next")

        if not markets:
            print(f"[INFO] No markets returned on page {page_count}, stopping.")
            break

        for market in markets:
            total_scanned += 1

            market_id = safe_get_market_id(market)
            if not market_id:
                continue
            if market_id in seen_markets:
                continue
            seen_markets.add(market_id)

            # Basic visibility filters
            active = market.get("active", True)
            closed = market.get("closed", False)
            if not active or closed:
                continue

            if not is_recent_market(market, days=RECENT_DAYS):
                continue

            # Volume / liveliness filter
            vol = safe_get_volume(market)
            if MIN_VOLUME and vol < MIN_VOLUME:
                continue

            # End date check (future)
            end_dt = parse_end_date(market)
            if end_dt and end_dt < datetime.now(timezone.utc):
                continue

            # Outcomes / tokens can be under different keys
            outcomes = market.get("tokens") or market.get("outcomes") or market.get("positions") or []
            if not outcomes:
                continue

            # iterate outcomes
            for outcome in outcomes:
                price = safe_get_price(outcome)
                if price is None:
                    continue

                # Filter price range
                if not (MIN_PRICE <= price < MAX_PRICE):
                    continue

                # Additional sanity: tiny dust prices like exactly 0.0 skip
                if price <= 0:
                    continue

                # Build op using start_dt which is now defined
                op = {
                    "market_id": market_id,
                    "question": market.get("question") or market.get("title") or market.get("description") or "UNKNOWN",
                    "outcome_id": safe_get_outcome_id(outcome),
                    "outcome_name": safe_get_outcome_name(outcome),
                    "price": price,
                    "volume": vol,
                    "start_date": safe_get_start_date(market).isoformat()
                                    if safe_get_start_date(market) else None,
                    "end_date": end_dt.isoformat() if end_dt else None,
                    "raw": {  # keep raw for debugging (trim or remove in production)
                        "market": {k: market.get(k) for k in ("id", "question", "active", "closed")},
                        "outcome": {k: outcome.get(k) for k in ("id", "price", "name", "token_id")}
                    }
                }
                opportunities.append(op)

        print(f"[PAGE {page_count}] Scanned so far: {total_scanned} | Found: {len(opportunities)}")
        # stop if API indicates no more pages
        if not next_cursor:
            break

        # Respect API rate limits
        time.sleep(PAGE_DELAY)

    # Sort cheapest first
    opportunities.sort(key=lambda x: x["price"])
    print(f"\n--- SCAN COMPLETE (pages={page_count}) ---")
    print(f"Total markets scanned: {total_scanned}")
    print(f"Opportunities found (< ${MAX_PRICE}): {len(opportunities)}")

    # Create archive directory if it doesn't exist
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_file = os.path.join(ARCHIVE_DIR, f"scan_{timestamp}.json")

    # Save to database (now returns opportunity_map)
    scan_id, opportunity_map = save_scan_to_db(total_scanned, opportunities)

    # Save to BOTH files
    # 1. Current file (for analyst.py to consume)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(opportunities, f, indent=2, ensure_ascii=False)
    
    # 2. Timestamped archive (for historical tracking)
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(opportunities, f, indent=2, ensure_ascii=False)
    
    print(f"Saved to: {OUTPUT_FILE}")
    print(f"Archived to: {archive_file}")
    print(f"Saved to database (scan_id: {scan_id})")

    # Print top N
    TOP_N = 20
    for i, op in enumerate(opportunities[:TOP_N], 1):
        print(f"{i:02d}. [{op['end_date']}] {op['question'][:80]}")
        print(f"    Outcome: {op['outcome_name']} | Price: ${op['price']:.5f} | Volume: {op['volume']}")
        print(f"    Market ID: {op['market_id']} | Outcome ID: {op['outcome_id']}")
        print("-" * 60)

    return opportunities, opportunity_map


if __name__ == "__main__":
    scan_markets()
