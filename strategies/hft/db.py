import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

DB_FILE = "hft_data.db"

# ✅ Use absolute path to avoid confusion
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "hft_data.db")

def init_hft_db():
    """Initialize the HFT database schema"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Ticks table: Stores high-frequency price updates
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        token_id TEXT,
        strike_price REAL, -- ✅ ADDED
        best_bid REAL,
        best_ask REAL,
        mid_price REAL,
        oracle_price REAL,
        minutes_until_close REAL
    )
    """)
    
    # Trades table: Stores executed trades (optional but good to have)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hft_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        token_id TEXT,
        side TEXT,  -- BUY/SELL
        outcome TEXT,  -- YES/NO
        price REAL,
        size REAL,  -- In dollars
        shares REAL,  -- Actual shares filled
        pnl REAL,  -- Realized P&L (0 for entries)
        strategy_reason TEXT,  -- Why the trade was made
        
        -- ✅ NEW: Add these for ML backtesting
        oracle_price_at_entry REAL,
        strike_price REAL,
        minutes_until_close REAL,
        spread_pct REAL,
        bid_liquidity REAL,
        ask_liquidity REAL
    )
    """)

     # Positions table: For persistence across restarts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hft_positions (
        token_id TEXT PRIMARY KEY,
        outcome TEXT,
        shares REAL,
        entry_price REAL,
        entry_time TIMESTAMP
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_token ON market_ticks(token_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_time ON market_ticks(timestamp)")
    
    conn.commit()
    conn.close()

def get_open_positions():
    """Fetch all open positions from DB"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hft_positions")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_position(token_id, outcome, shares, entry_price, entry_time):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO hft_positions (token_id, outcome, shares, entry_price, entry_time)
        VALUES (?, ?, ?, ?, ?)
    """, (token_id, outcome, shares, entry_price, entry_time.isoformat()))
    conn.commit()
    conn.close()

def remove_position(token_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hft_positions WHERE token_id = ?", (token_id,))
    conn.commit()
    conn.close()

def save_trade(
    token_id: str,
    side: str,
    outcome: str,
    price: float,
    size: float,
    shares: float,
    pnl: float = 0.0,
    strategy_reason: str = "",
    oracle_price: float = 0.0,
    strike_price: float = 0.0,
    minutes_until_close: float = 0.0,
    spread_pct: float = 0.0,
    bid_liquidity: float = 0.0,
    ask_liquidity: float = 0.0
):
    """Save trade execution with full context for backtesting"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO hft_trades (
            token_id, side, outcome, price, size, shares, pnl, strategy_reason,
            oracle_price_at_entry, strike_price, minutes_until_close,
            spread_pct, bid_liquidity, ask_liquidity
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        token_id, side, outcome, price, size, shares, pnl, strategy_reason,
        oracle_price, strike_price, minutes_until_close,
        spread_pct, bid_liquidity, ask_liquidity
    ))
    conn.commit()
    conn.close()

def save_market_tick(token_id, strike_price, best_bid, best_ask, mid_price, oracle_price, minutes_until_close):
    try: # ✅ ADDED: Missing try block
        conn = sqlite3.connect(DB_FILE) # ✅ FIXED: DB_PATH -> DB_FILE
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO market_ticks ( -- ✅ FIXED: ticks -> market_ticks
                timestamp, token_id, strike_price, best_bid, best_ask, mid_price, oracle_price, minutes_until_close
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            token_id,
            strike_price,
            best_bid,
            best_ask,
            mid_price,
            oracle_price,
            minutes_until_close
        ))
        conn.commit()
        conn.close()
    except Exception as e: # ✅ FIXED: Now inside try/except
        print(f"DATABASE_ERROR: {e}")
        raise e

def get_recent_ticks(token_id: str, limit: int = 100):
    """Fetch recent ticks for analysis"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT * FROM market_ticks 
    WHERE token_id = ? 
    ORDER BY timestamp DESC 
    LIMIT ?
    """, (token_id, limit))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]