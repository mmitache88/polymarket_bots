import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

def get_hourly_slug() -> str:
    """
    Constructs the slug for the current Bitcoin hourly market.
    Example: bitcoin-up-or-down-december-24-4pm-et
    """
    now = datetime.utcnow()
    et_time = now - timedelta(hours=5)
    
    target_hour = et_time.hour
    am_pm = "am" if target_hour < 12 else "pm"
    
    display_hour = target_hour if target_hour <= 12 else target_hour - 12
    if display_hour == 0: display_hour = 12
    
    month = et_time.strftime("%B").lower()
    day = et_time.day
    
    return f"bitcoin-up-or-down-{month}-{day}-{display_hour}{am_pm}-et"

def fetch_current_hourly_market() -> Optional[Dict[str, Any]]:
    """
    Fetches the active hourly market details from Polymarket Gamma API.
    Returns a dictionary with token_ids and market info.
    """
    slug = get_hourly_slug()
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print(f"⚠️ No event found for slug: {slug}")
            return None
            
        # The API returns a list of events (usually just one match)
        event = data[0]
        markets = event.get('markets', [])
        
        if not markets:
            print("⚠️ Event found but no markets inside.")
            return None
            
        # For hourly markets, there is usually only one market in the event
        market = markets[0]
        
        # Extract Token IDs (The "clobTokenIds" field is what the bot needs)
        # Format: ["TokenID_Outcome1", "TokenID_Outcome2"]
        clob_token_ids = market.get('clobTokenIds', [])
        outcomes = market.get('outcomes', [])
        
        return {
            "slug": slug,
            "question": market.get('question'),
            "end_date": market.get('endDate'), # Useful for your timer!
            "token_ids": clob_token_ids,
            "outcomes": outcomes,
            "raw_market": market
        }
        
    except Exception as e:
        print(f"❌ Error fetching market from Gamma API: {e}")
        return None

if __name__ == "__main__":
    # Test run
    print("Fetching current hourly market...")
    market = fetch_current_hourly_market()
    if market:
        print(f"✅ SUCCESS")
        print(f"Question: {market['question']}")
        print(f"End Date: {market['end_date']}")
        print(f"Outcomes: {market['outcomes']}")
        print(f"Token IDs: {market['token_ids']}")
        
        # Identify YES/NO tokens
        if len(market['token_ids']) == 2:
            print(f"👉 YES Token: {market['token_ids'][0]}")
            print(f"👉 NO  Token: {market['token_ids'][1]}")