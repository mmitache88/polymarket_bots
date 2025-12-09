from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import ExtraDataToPOAMiddleware
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

rpc_url = os.getenv("RPC_URL") # Polygon rpc url 
priv_key = os.getenv("POLYGON_PRIVATE_KEY") # Polygon account private key (needs some MATIC)
pub_key_raw = os.getenv("PUBLIC_KEY") # Polygon account public key corresponding to private key

# Validate credentials
if not rpc_url or not priv_key or not pub_key_raw:
    raise ValueError("Missing credentials in .env file")

# Convert to checksum address (proper capitalization)
web3_temp = Web3()
pub_key = web3_temp.to_checksum_address(pub_key_raw)

print(f"Using RPC: {rpc_url}")
print(f"Using wallet: {pub_key}")

chain_id = 137

erc20_approve = """[{"constant": false,"inputs": [{"name": "_spender","type": "address" },{ "name": "_value", "type": "uint256" }],"name": "approve","outputs": [{ "name": "", "type": "bool" }],"payable": false,"stateMutability": "nonpayable","type": "function"}]"""
erc1155_set_approval = """[{"inputs": [{ "internalType": "address", "name": "operator", "type": "address" },{ "internalType": "bool", "name": "approved", "type": "bool" }],"name": "setApprovalForAll","outputs": [],"stateMutability": "nonpayable","type": "function"}]"""

usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ctf_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

web3 = Web3(Web3.HTTPProvider(rpc_url))
web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

# Check connection
if not web3.is_connected():
    raise ConnectionError(f"Failed to connect to Polygon RPC at {rpc_url}")

print("✅ Connected to Polygon network")

# Check balance
balance = web3.eth.get_balance(pub_key)
balance_matic = web3.from_wei(balance, 'ether')
print(f"Wallet MATIC balance: {balance_matic:.4f} MATIC")

if balance_matic < 0.01:
    print("⚠️  WARNING: Low MATIC balance. You need ~0.1 MATIC for gas fees.")

nonce = web3.eth.get_transaction_count(pub_key)

usdc = web3.eth.contract(address=usdc_address, abi=erc20_approve)
ctf = web3.eth.contract(address=ctf_address, abi=erc1155_set_approval)

# CTF Exchange
raw_usdc_approve_txn = usdc.functions.approve("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", int(MAX_INT, 0)
).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
print(usdc_approve_tx_receipt)

nonce = web3.eth.get_transaction_count(pub_key)

raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", True).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
print(ctf_approval_tx_receipt)

nonce = web3.eth.get_transaction_count(pub_key)

# Neg Risk CTF Exchange
raw_usdc_approve_txn = usdc.functions.approve("0xC5d563A36AE78145C45a50134d48A1215220f80a", int(MAX_INT, 0)
).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
print(usdc_approve_tx_receipt)

nonce = web3.eth.get_transaction_count(pub_key)

raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0xC5d563A36AE78145C45a50134d48A1215220f80a", True).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
print(ctf_approval_tx_receipt)

nonce = web3.eth.get_transaction_count(pub_key)

# Neg Risk Adapter
raw_usdc_approve_txn = usdc.functions.approve("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", int(MAX_INT, 0)
).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
print(usdc_approve_tx_receipt)

nonce = web3.eth.get_transaction_count(pub_key)

raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", True).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
print(ctf_approval_tx_receipt)