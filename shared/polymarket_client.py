"""Shared Polymarket client wrapper for all strategies"""

import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

load_dotenv()

# Cache clients by strategy name
_clients = {}

def get_client(strategy: str = "default"):
    """
    Get or create a Polymarket client for a specific strategy.
    
    Each strategy can have its own wallet by setting environment variables:
    - POLYGON_PRIVATE_KEY_<STRATEGY> (e.g., POLYGON_PRIVATE_KEY_LONGSHOT)
    - POLYMARKET_PROXY_ADDRESS_<STRATEGY>
    
    Falls back to default credentials if strategy-specific ones don't exist.
    
    Args:
        strategy: Strategy name (e.g., "longshot", "timing_arb")
    
    Returns:
        ClobClient configured for the strategy's wallet
    """
    global _clients
    
    strategy_upper = strategy.upper()
    
    if strategy not in _clients:
        # Try strategy-specific credentials first, fall back to default
        private_key = (
            os.getenv(f"POLYGON_PRIVATE_KEY_{strategy_upper}") or 
            os.getenv("POLYGON_PRIVATE_KEY")
        )
        proxy_address = (
            os.getenv(f"POLYMARKET_PROXY_ADDRESS_{strategy_upper}") or 
            os.getenv("POLYMARKET_PROXY_ADDRESS")
        )
        
        if not private_key or not proxy_address:
            raise ValueError(
                f"Missing credentials for strategy '{strategy}'. "
                f"Set POLYGON_PRIVATE_KEY_{strategy_upper} and "
                f"POLYMARKET_PROXY_ADDRESS_{strategy_upper} in .env"
            )
        
        client = ClobClient(
            host=os.getenv("HOST"),
            key=private_key,
            chain_id=int(os.getenv("CHAIN_ID")),
            signature_type=2,
            funder=proxy_address
        )
        creds = client.derive_api_key()
        client.set_api_creds(creds)
        
        _clients[strategy] = client
    
    return _clients[strategy]


def get_wallet_info(strategy: str = "default"):
    """Get wallet address for a strategy (for logging/debugging)"""
    strategy_upper = strategy.upper()
    
    proxy_address = (
        os.getenv(f"POLYMARKET_PROXY_ADDRESS_{strategy_upper}") or 
        os.getenv("POLYMARKET_PROXY_ADDRESS")
    )
    
    return {
        'strategy': strategy,
        'proxy_address': proxy_address,
        'is_strategy_specific': os.getenv(f"POLYMARKET_PROXY_ADDRESS_{strategy_upper}") is not None
    }