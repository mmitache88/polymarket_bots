"""
HFT-specific database operations

Separate database from longshot strategy for clean separation.
"""

import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from .models import Position, OrderState, OrderStatus

DB_FILE = "data/hft_trades.db"


def get_connection() -> sqlite3.Connection:
    """Get database connection with row factory"""
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize HFT database tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Trades table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE,
        token_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        side TEXT NOT NULL,
        shares REAL NOT NULL,
        price REAL NOT NULL,
        total_cost REAL NOT NULL,
        status TEXT NOT NULL,
        strategy_name TEXT,
        entry_reason TEXT,
        created_at TEXT NOT NULL,
        filled_at TEXT,
        closed_at TEXT,
        exit_price REAL,
        exit_reason TEXT,
        pnl REAL,
        pnl_pct REAL
    )
    """)
    
    # Positions table (current open positions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_id TEXT UNIQUE NOT NULL,
        outcome TEXT NOT NULL,
        shares REAL NOT NULL,
        entry_price REAL NOT NULL,
        entry_time TEXT NOT NULL,
        cost_basis REAL NOT NULL,
        strategy_name TEXT
    )
    """)
    
    # Order history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        token_id TEXT NOT NULL,
        status TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        details TEXT
    )
    """)
    
    # Performance snapshots
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        total_pnl REAL NOT NULL,
        realized_pnl REAL NOT NULL,
        unrealized_pnl REAL NOT NULL,
        total_exposure REAL NOT NULL,
        win_count INTEGER NOT NULL,
        loss_count INTEGER NOT NULL,
        win_rate REAL
    )
    """)
    
    # Market data snapshots (for analysis)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        token_id TEXT NOT NULL,
        poly_bid REAL,
        poly_ask REAL,
        poly_mid REAL,
        oracle_price REAL,
        oracle_asset TEXT,
        minutes_until_close REAL
    )
    """)
    
    conn.commit()
    conn.close()


def save_trade(
    order_id: str,
    token_id: str,
    outcome: str,
    side: str,
    shares: float,
    price: float,
    status: str,
    strategy_name: str = "",
    entry_reason: str = ""
) -> int:
    """Save a new trade to database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO trades (
        order_id, token_id, outcome, side, shares, price, total_cost,
        status, strategy_name, entry_reason, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id, token_id, outcome, side, shares, price, shares * price,
        status, strategy_name, entry_reason, datetime.utcnow().isoformat()
    ))
    
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def update_trade_status(order_id: str, status: str, **kwargs):
    """Update trade status and optional fields"""
    conn = get_connection()
    cursor = conn.cursor()
    
    set_clauses = ["status = ?"]
    values = [status]
    
    if "filled_at" in kwargs:
        set_clauses.append("filled_at = ?")
        values.append(kwargs["filled_at"])
    
    if "exit_price" in kwargs:
        set_clauses.append("exit_price = ?")
        values.append(kwargs["exit_price"])
    
    if "exit_reason" in kwargs:
        set_clauses.append("exit_reason = ?")
        values.append(kwargs["exit_reason"])
    
    if "pnl" in kwargs:
        set_clauses.append("pnl = ?")
        values.append(kwargs["pnl"])
    
    if "pnl_pct" in kwargs:
        set_clauses.append("pnl_pct = ?")
        values.append(kwargs["pnl_pct"])
    
    if "closed_at" in kwargs:
        set_clauses.append("closed_at = ?")
        values.append(kwargs["closed_at"])
    
    values.append(order_id)
    
    cursor.execute(f"""
    UPDATE trades SET {', '.join(set_clauses)} WHERE order_id = ?
    """, values)
    
    conn.commit()
    conn.close()


def save_position(position: Position, strategy_name: str = ""):
    """Save or update a position"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT OR REPLACE INTO positions (
        token_id, outcome, shares, entry_price, entry_time, cost_basis, strategy_name
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        position.token_id,
        position.outcome.value,
        position.shares,
        position.entry_price,
        position.entry_time.isoformat(),
        position.cost_basis,
        strategy_name
    ))
    
    conn.commit()
    conn.close()


def remove_position(token_id: str):
    """Remove a closed position"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM positions WHERE token_id = ?", (token_id,))
    conn.commit()
    conn.close()


def get_open_positions() -> List[Dict[str, Any]]:
    """Get all open positions"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trade_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent trade history"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM trades ORDER BY created_at DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_performance_summary() -> Dict[str, Any]:
    """Get overall performance summary"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        COUNT(*) as total_trades,
        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN pnl = 0 OR pnl IS NULL THEN 1 ELSE 0 END) as breakeven,
        SUM(pnl) as total_pnl,
        AVG(pnl) as avg_pnl,
        MAX(pnl) as best_trade,
        MIN(pnl) as worst_trade
    FROM trades WHERE status = 'FILLED' AND pnl IS NOT NULL
    """)
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        result = dict(row)
        total = result['wins'] + result['losses']
        result['win_rate'] = (result['wins'] / total * 100) if total > 0 else 0
        return result
    
    return {
        'total_trades': 0, 'wins': 0, 'losses': 0, 'breakeven': 0,
        'total_pnl': 0, 'avg_pnl': 0, 'best_trade': 0, 'worst_trade': 0, 'win_rate': 0
    }


def save_market_snapshot(
    token_id: str,
    poly_bid: float,
    poly_ask: float,
    oracle_price: float,
    oracle_asset: str,
    minutes_until_close: float
):
    """Save market data snapshot for analysis"""
    conn = get_connection()
    cursor = conn.cursor()
    
    poly_mid = (poly_bid + poly_ask) / 2 if poly_bid and poly_ask else None
    
    cursor.execute("""
    INSERT INTO market_snapshots (
        timestamp, token_id, poly_bid, poly_ask, poly_mid,
        oracle_price, oracle_asset, minutes_until_close
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(), token_id, poly_bid, poly_ask, poly_mid,
        oracle_price, oracle_asset, minutes_until_close
    ))
    
    conn.commit()
    conn.close()