import sqlite3
from datetime import datetime

DB_FILE = "scanner_history.db"

def init_db():
    """Initialize the database schema"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scans (
        scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_markets INTEGER,
        opportunities_found INTEGER
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id INTEGER,
        market_id TEXT,
        question TEXT,
        outcome_id TEXT,
        outcome_name TEXT,
        price REAL,
        volume REAL,
        start_date TEXT,
        end_date TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
    )
    """)
    
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_market_outcome 
    ON opportunities(market_id, outcome_id)
    """)
    
    conn.commit()
    conn.close()

def save_scan_to_db(total_scanned, opportunities):
    """Save scan results to database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Insert scan record
    cursor.execute(
        "INSERT INTO scans (total_markets, opportunities_found) VALUES (?, ?)",
        (total_scanned, len(opportunities))
    )
    scan_id = cursor.lastrowid
    
    # Insert opportunities
    for opp in opportunities:
        cursor.execute("""
        INSERT INTO opportunities 
        (scan_id, market_id, question, outcome_id, outcome_name, price, volume, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_id,
            opp['market_id'],
            opp['question'],
            opp['outcome_id'],
            opp['outcome_name'],
            opp['price'],
            opp['volume'],
            opp['start_date'],
            opp['end_date']
        ))
    
    conn.commit()
    conn.close()
    return scan_id

def get_price_history(market_id, outcome_id):
    """Get price history for a specific market/outcome"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT s.scan_date, o.price, o.volume
    FROM opportunities o
    JOIN scans s ON o.scan_id = s.scan_id
    WHERE o.market_id = ? AND o.outcome_id = ?
    ORDER BY s.scan_date
    """, (market_id, outcome_id))
    
    results = cursor.fetchall()
    conn.close()
    return results