from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
from dotenv import load_dotenv
import os

load_dotenv()

host = os.getenv("HOST")
key = os.getenv("POLYGON_PRIVATE_KEY")
chain_id = 137
proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")

print(f"Direct wallet: {os.getenv('PUBLIC_KEY')}")
print(f"Proxy wallet: {proxy_address}")

# Initialize client
client = ClobClient(
    host, 
    key=key, 
    chain_id=chain_id, 
    signature_type=2,  # <-- CHANGED: Use 2 for MetaMask/browser wallet
    funder=proxy_address
)

# Derive credentials from private key
print("\nDeriving API credentials...")
creds = client.derive_api_key()
print(f"Derived API Key: {creds.api_key[:20]}...")
client.set_api_creds(creds)

# Create order
order_args = OrderArgs(
    price=0.006,
    size=5.0,
    side=BUY,
    token_id="89068243146428992803201061569744821856269870796387937227122631836385807464552",
)

print("\nCreating order...")
signed_order = client.create_order(order_args)

print("Posting order...")
resp = client.post_order(signed_order, OrderType.GTC)

print("\n✅ ORDER RESPONSE:")
print(resp)