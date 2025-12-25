import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_FILE = "hft_data.db"

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
        side TEXT,
        price REAL,
        size REAL,
        pnl REAL
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_token ON market_ticks(token_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_time ON market_ticks(timestamp)")
    
    conn.commit()
    conn.close()

def save_market_tick(token_id: str, best_bid: float, best_ask: float, 
                     mid_price: float, oracle_price: float, minutes_until_close: float):
    """Save a single market snapshot to the DB"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO market_ticks 
    (token_id, best_bid, best_ask, mid_price, oracle_price, minutes_until_close)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (token_id, best_bid, best_ask, mid_price, oracle_price, minutes_until_close))
    
    conn.commit()
    conn.close()

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