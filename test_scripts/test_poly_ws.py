import asyncio
import websockets
import json

async def test_polymarket_ws():
    # 1. USE THE BASE URL (Remove '/market')
    url = "wss://ws-subscriptions-clob.polymarket.com/ws/market" 
    
    # Note: Sometimes the /market endpoint works if you send NO payload, 
    # but the standard is to connect to root/market and send the config.
    # Let's try the specific documented structure for the CLOB.
    
    print(f"🔌 Connecting to {url}...")

    async with websockets.connect(url) as ws:
        print(f"✅ Connected!")

        # 2. THE CORRECT PAYLOAD
        # The key is "assets_ids" (PLURAL) and "type": "market"
        token_id = "67704255197116168826604911233626301865010283966205730455742704536521111535950"
        
        subscribe_payload = {
            "assets_ids": [token_id],
            "type": "market"
        }

        print(f"📤 Sending Subscription: {json.dumps(subscribe_payload)}")
        await ws.send(json.dumps(subscribe_payload))

        print("Create a loop to listen...")
        
        # 3. LISTEN LOOP
        # The first message might be a confirmation or immediate data
        try:
            while True:
                response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(response)
                
                # HANDLE BATCHES (LISTS) VS SINGLE EVENTS (DICTS)
                # The error you saw meant 'data' was a list, so we normalize it here.
                events = data if isinstance(data, list) else [data]

                for event in events:
                    # Check what kind of event we got
                    event_type = event.get("event_type", "unknown")
                    print(f"📩 Received [{event_type}]: {str(event)[:100]}...")
                    
                    # If we get an orderbook, it works!
                    if event_type == "book":
                        print("\n🎉 SUCCESS! Received Order Book Snapshot.")
                        print(f"   Bids: {len(event.get('bids', []))} | Asks: {len(event.get('asks', []))}")
                        return # Exit script on success
                    
        except asyncio.TimeoutError:
            print("⏱️ Timeout: No data received for 10 seconds.")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_polymarket_ws())