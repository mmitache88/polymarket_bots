import asyncio
import json
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

async def fetch_btc_hourly_markets():
    """
    Fetch Bitcoin hourly markets.
    Targets the CURRENT active hour (e.g., at 2:45 PM, it fetches the 2-3 PM market).
    """
    now = datetime.utcnow()
    # Adjust for ET timezone (UTC-5)
    et_time = now - timedelta(hours=5)
    
    # We want the market that STARTED at the top of the current hour.
    target_hour = et_time.hour
    am_pm = "am" if target_hour < 12 else "pm"
    
    display_hour = target_hour if target_hour <= 12 else target_hour - 12
    if display_hour == 0: display_hour = 12
    
    month = et_time.strftime("%B").lower()
    day = et_time.day
    
    # Construct slug based on the CURRENT hour
    slug = f"bitcoin-up-or-down-{month}-{day}-{display_hour}{am_pm}-et"
    
    print(f"🕒 Current Time: {et_time.strftime('%I:%M %p')} ET")
    print(f"🎯 Target Slug:  {slug} (The active market)")
    
    return await fetch_with_known_slug(slug)

async def fetch_with_known_slug(slug: str):
    """
    Fetch markets for a specific known slug.
    Strategy:
    1. Listen for Network Requests (GraphQL)
    2. Fallback: Read hidden Next.js data blob (SSR data)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = await context.new_page()
        
        # Container for our data
        captured_data = []
        
        # Strategy 1: Network Listener
        async def handle_response(response):
            if "graphql" in response.url and response.request.method == "POST":
                try:
                    data = await response.json()
                    if data.get("data", {}).get("market"):
                         captured_data.append(data["data"]["market"])
                    elif data.get("data", {}).get("series", {}).get("markets"):
                        captured_data.extend(data["data"]["series"]["markets"])
                except:
                    pass
        
        page.on("response", handle_response)
        
        url = f"https://polymarket.com/event/{slug}"
        print(f"🔍 Fetching: {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # --- NEW: Capture Screenshot for Verification ---
            screenshot_filename = "market_verification.png"
            await page.screenshot(path=screenshot_filename)
            print(f"📸 Screenshot saved to: {screenshot_filename}")
            # ------------------------------------------------
            
            await page.wait_for_timeout(3000) # Give network requests a moment
            
            # Strategy 2: "God Mode" - Extract Next.js Data Blob
            if not captured_data:
                print("⚠️  No network data found. Attempting to read page source...")
                try:
                    # Execute JavaScript to find the Next.js data structure
                    next_data = await page.evaluate("""() => {
                        try {
                            return window.__NEXT_DATA__.props.pageProps.dehydratedState.queries;
                        } catch (e) {
                            return null;
                        }
                    }""")
                    
                    if next_data:
                        # Parse through the complex Next.js structure
                        import json
                        raw_dump = json.dumps(next_data)
                        
                        def find_market_with_tokens(obj):
                            found = []
                            if isinstance(obj, dict):
                                if "clobTokenIds" in obj and "question" in obj:
                                    found.append(obj)
                                for k, v in obj.items():
                                    found.extend(find_market_with_tokens(v))
                            elif isinstance(obj, list):
                                for item in obj:
                                    found.extend(find_market_with_tokens(item))
                            return found

                        extracted_markets = find_market_with_tokens(next_data)
                        if extracted_markets:
                            print(f"✅ Recovered {len(extracted_markets)} markets from Page Source!")
                            captured_data.extend(extracted_markets)
                except Exception as e:
                    print(f"Error reading page source: {e}")

        except Exception as e:
            print(f"⚠️  Error loading page: {e}")
        
        await browser.close()
        
        # --- Processing Results ---
        results = []
        seen_ids = set()
        
        if captured_data:
            for m in captured_data:
                question = m.get("question", "N/A")
                if question in seen_ids: continue
                seen_ids.add(question)
                
                end_date = m.get("endDate", "N/A")
                clob_raw = m.get("clobTokenIds", "[]")
                clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                
                if clob_ids and len(clob_ids) >= 2:
                    result = {
                        "question": question,
                        "end_date": end_date,
                        "yes_token": clob_ids[0],
                        "no_token": clob_ids[1],
                    }
                    results.append(result)

        return results

if __name__ == "__main__":
    print("=" * 70)
    print("🔍 POLYMARKET - Bitcoin Hourly Market Fetcher (GraphQL)")
    print("=" * 70)
    
    results = asyncio.run(fetch_btc_hourly_markets())
    
    if results:
        print("\n" + "=" * 70)
        print("📋 TOKEN IDS FOR TRADING")
        print("=" * 70)
        for r in results:
            print(f"\n{r['question']}")
            print(f"  YES: {r['yes_token']}")
            print(f"  NO:  {r['no_token']}")
    else:
        print("\n❌ No markets found.")