from web3 import Web3
from dotenv import load_dotenv
import os

load_dotenv()

# Connect to Polygon
web3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

# Convert address to checksum format
wallet_raw = os.getenv('POLYMARKET_PROXY_ADDRESS')
wallet = web3.to_checksum_address(wallet_raw)

print(f"Wallet: {wallet}\n")

# Check MATIC balance
matic_balance = web3.eth.get_balance(wallet)
matic_balance_formatted = web3.from_wei(matic_balance, 'ether')
print(f"💎 MATIC Balance: {matic_balance_formatted:.4f} MATIC")

# Check USDC balance
usdc_address = web3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
usdc_abi = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]'
usdc = web3.eth.contract(address=usdc_address, abi=usdc_abi)

usdc_balance = usdc.functions.balanceOf(wallet).call()
usdc_balance_formatted = usdc_balance / 1e6  # USDC has 6 decimals

print(f"💵 USDC Balance: ${usdc_balance_formatted:.2f}")

# Status check
print("\n" + "="*50)
if matic_balance_formatted < 0.1:
    print("⚠️  LOW MATIC - Need ~0.1 MATIC for gas fees")
    print("   Send MATIC to this wallet from an exchange")
    
if usdc_balance_formatted < 1:
    print("⚠️  LOW USDC - Need USDC to trade")
    print("   Send USDC (Polygon network) to this wallet")
    
if matic_balance_formatted >= 0.1 and usdc_balance_formatted >= 1:
    print("✅ Wallet funded! Ready to trade")
print("="*50)