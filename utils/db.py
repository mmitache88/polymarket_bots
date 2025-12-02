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
    
    # NEW: Analysis results table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
        opportunity_id INTEGER,
        analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        score INTEGER,
        reason TEXT,
        conviction TEXT,
        catalyst_date TEXT,
        approved BOOLEAN,
        FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
    )
    """)
    
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_opportunity_analysis
    ON analyses(opportunity_id)
    """)

    # NEW: Trades table to track executed positions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        opportunity_id INTEGER,
        order_id TEXT,
        token_id TEXT,
        market_question TEXT,
        outcome_name TEXT,
        shares REAL,
        entry_price REAL,
        entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        conviction TEXT,
        status TEXT DEFAULT 'open',
        exit_price REAL,
        exit_date TIMESTAMP,
        profit_loss REAL,
        FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
    )
    """)
    
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_trade_status
    ON trades(status)
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
    
    # Insert opportunities and return mapping of (market_id, outcome_id) -> opportunity_id
    opportunity_map = {}
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
        opportunity_id = cursor.lastrowid
        key = (opp['market_id'], opp['outcome_id'])
        opportunity_map[key] = opportunity_id
    
    conn.commit()
    conn.close()
    return scan_id, opportunity_map

def save_analysis_to_db(opportunity_id, analysis, approved):
    """Save analyst LLM results to database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO analyses 
    (opportunity_id, score, reason, conviction, catalyst_date, approved)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        opportunity_id,
        analysis.get('score', 0),
        analysis.get('reason', ''),
        analysis.get('conviction', ''),
        analysis.get('catalyst_date'),
        approved
    ))
    
    conn.commit()
    conn.close()

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

def get_opportunity_id(market_id, outcome_id):
    """Get the most recent opportunity_id for a market/outcome pair"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT id FROM opportunities
    WHERE market_id = ? AND outcome_id = ?
    ORDER BY first_seen DESC
    LIMIT 1
    """, (market_id, outcome_id))
    
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_analysis_history(market_id, outcome_id):
    """Get all LLM analysis history for a specific market/outcome"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT a.analysis_date, a.score, a.reason, a.conviction, a.approved
    FROM analyses a
    JOIN opportunities o ON a.opportunity_id = o.id
    WHERE o.market_id = ? AND o.outcome_id = ?
    ORDER BY a.analysis_date
    """, (market_id, outcome_id))
    
    results = cursor.fetchall()
    conn.close()
    return results

def save_trade_to_db(opportunity_id, order_id, token_id, question, outcome, shares, entry_price, conviction):
    """Save executed trade to database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO trades 
    (opportunity_id, order_id, token_id, market_question, outcome_name, shares, entry_price, conviction, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
    """, (opportunity_id, order_id, token_id, question, outcome, shares, entry_price, conviction))
    
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def get_open_positions():
    """Get all open positions that need monitoring"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        trade_id,
        token_id,
        market_question,
        outcome_name,
        shares,
        entry_price,
        entry_date,
        conviction
    FROM trades
    WHERE status = 'open'
    ORDER BY entry_date DESC
    """)
    
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return results

def update_position_exit(trade_id, exit_price):
    """Mark position as closed and calculate P&L"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get entry price to calculate P&L
    cursor.execute("SELECT shares, entry_price FROM trades WHERE trade_id = ?", (trade_id,))
    row = cursor.fetchone()
    if row:
        shares, entry_price = row
        profit_loss = shares * (exit_price - entry_price)
        
        cursor.execute("""
        UPDATE trades 
        SET status = 'closed', 
            exit_price = ?, 
            exit_date = CURRENT_TIMESTAMP,
            profit_loss = ?
        WHERE trade_id = ?
        """, (exit_price, profit_loss, trade_id))
    
    conn.commit()
    conn.close()

def is_opportunity_analyzed(opportunity_id):
    """Check if opportunity has already been analyzed"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT COUNT(*) FROM analyses
    WHERE opportunity_id = ?
    """, (opportunity_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    return count > 0

def get_approved_opportunities():
    """Get all opportunities with score >= 6 for export to JSON"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        o.market_id,
        o.outcome_id,
        o.question,
        o.outcome_name,
        o.price,
        o.end_date,
        a.score,
        a.reason,
        a.conviction,
        a.catalyst_date
    FROM opportunities o
    JOIN analyses a ON o.id = a.opportunity_id
    WHERE a.approved = 1
    ORDER BY a.score DESC, a.analysis_date DESC
    """)
    
    columns = [desc[0] for desc in cursor.description]
    results = []
    
    for row in cursor.fetchall():
        result = dict(zip(columns, row))
        
        # Restructure to match approved_trades.json format
        result['analysis'] = {
            'score': result.pop('score'),
            'reasoning': result.pop('reason'),  # Rename 'reason' to 'reasoning'
            'conviction': result.pop('conviction'),
            'catalyst_date': result.pop('catalyst_date')
        }
        results.append(result)
    
    conn.close()
    return results