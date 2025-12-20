import requests
import json
from datetime import datetime, timedelta


def search_short_duration_markets():
    """
    Find ALL markets that close within the next 24 hours.
    These are likely the hourly/short-term markets.
    """
    url = "https://gamma-api.polymarket.com/markets"
    
    now = datetime.utcnow()
    tomorrow = now + timedelta(hours=24)
    
    params = {
        "closed": "false",
        "active": "true",
        "limit": 200,
        "end_date_min": now.isoformat() + "Z",
        "end_date_max": tomorrow.isoformat() + "Z",
    }
    
    print(f"🔍 Searching for markets ending between:")
    print(f"   Now: {now.isoformat()}Z")
    print(f"   +24h: {tomorrow.isoformat()}Z")
    
    response = requests.get(url, params=params)
    markets = response.json()
    
    print(f"\n📊 Found {len(markets)} markets ending in next 24 hours:\n")
    
    for market in markets:
        question = market.get('question', 'N/A')
        end_date = market.get('endDate', 'N/A')
        clob_raw = market.get('clobTokenIds')
        
        print(f"• {question}")
        print(f"  Ends: {end_date}")
        
        if clob_raw:
            clob = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
            if len(clob) >= 2:
                print(f"  YES: {clob[0]}")
                print(f"  NO:  {clob[1]}")
        print()
    
    return markets


def search_all_events_paginated():
    """
    Paginate through ALL events to find the hourly BTC event.
    """
    url = "https://gamma-api.polymarket.com/events"
    offset = 0
    limit = 50
    
    print("🔍 Scanning ALL events for hourly/short-term Bitcoin markets...\n")
    
    keywords = ['hourly', 'hour', 'up or down', 'up-or-down', 'price:', 
                'am', 'pm', '12:', '1:', '2:', '3:', '4:', '5:', '6:', 
                '7:', '8:', '9:', '10:', '11:']
    
    found_events = []
    
    while offset < 500:
        params = {
            "closed": "false",
            "active": "true",
            "limit": limit,
            "offset": offset,
        }
        
        response = requests.get(url, params=params)
        events = response.json()
        
        if not events:
            break
        
        for event in events:
            title = event.get('title', '').lower()
            slug = event.get('slug', '').lower()
            
            # Check if title or slug contains time-related keywords
            if any(kw in title or kw in slug for kw in keywords):
                found_events.append(event)
                print(f"✅ POTENTIAL: {event.get('title')}")
                print(f"   Slug: {event.get('slug')}")
                print(f"   Markets: {len(event.get('markets', []))}")
                print()
            
            # Also check if it's Bitcoin-related with short duration markets
            if 'bitcoin' in title or 'btc' in title:
                markets = event.get('markets', [])
                for m in markets:
                    end_str = m.get('endDate', '')
                    if end_str:
                        try:
                            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                            hours_until = (end_dt - datetime.now(end_dt.tzinfo)).total_seconds() / 3600
                            if 0 < hours_until < 24:
                                print(f"⏰ SHORT-TERM BTC MARKET:")
                                print(f"   Event: {event.get('title')}")
                                print(f"   Market: {m.get('question')}")
                                print(f"   Ends in: {hours_until:.1f} hours")
                                clob = m.get('clobTokenIds')
                                if clob:
                                    ids = json.loads(clob) if isinstance(clob, str) else clob
                                    print(f"   Token IDs: {ids}")
                                print()
                        except:
                            pass
        
        offset += limit
        print(f"   Scanned {offset} events...")
    
    return found_events


def find_by_specific_slugs():
    """
    Try known slug patterns for hourly markets.
    """
    url = "https://gamma-api.polymarket.com/events"
    
    # Common slug patterns for hourly markets
    slug_patterns = [
        "bitcoin-up-or-down",
        "btc-up-or-down", 
        "bitcoin-hourly",
        "btc-hourly",
        "bitcoin-price-hourly",
        "crypto-hourly",
        "bitcoin-price",
    ]
    
    print("🔍 Trying specific slug patterns...\n")
    
    for slug in slug_patterns:
        try:
            # Try fetching event directly by slug
            event_url = f"https://gamma-api.polymarket.com/events/{slug}"
            response = requests.get(event_url)
            
            if response.status_code == 200:
                event = response.json()
                print(f"✅ FOUND: {slug}")
                print(f"   Title: {event.get('title')}")
                print(f"   Markets: {len(event.get('markets', []))}")
                
                for m in event.get('markets', [])[:5]:
                    print(f"      - {m.get('question')}")
                print()
            else:
                print(f"❌ {slug}: Not found")
                
        except Exception as e:
            print(f"❌ {slug}: Error - {e}")


def check_polymarket_website_slug():
    """
    If you know the URL from the Polymarket website, extract the slug.
    """
    print("\n" + "=" * 60)
    print("💡 TIP: If you can see these markets on polymarket.com:")
    print("=" * 60)
    print("""
1. Go to https://polymarket.com
2. Find a "Bitcoin Up or Down" hourly market
3. Look at the URL, e.g.: https://polymarket.com/event/SOME-SLUG
4. The slug is 'SOME-SLUG'
5. Run: get_event_by_slug('SOME-SLUG')

Or share the URL here and I'll help extract the token IDs!
""")


if __name__ == "__main__":
    print("=" * 80)
    print("🔍 POLYMARKET - Finding Hourly Markets")
    print("=" * 80)
    
    # Method 1: Find markets ending soon
    print("\n" + "=" * 40)
    print("METHOD 1: Markets ending in 24 hours")
    print("=" * 40)
    search_short_duration_markets()
    
    # Method 2: Try specific slugs
    print("\n" + "=" * 40)
    print("METHOD 2: Try known slug patterns")
    print("=" * 40)
    find_by_specific_slugs()
    
    # Method 3: Paginate all events
    print("\n" + "=" * 40)
    print("METHOD 3: Scan all events")
    print("=" * 40)
    search_all_events_paginated()
    
    # Help
    check_polymarket_website_slug()