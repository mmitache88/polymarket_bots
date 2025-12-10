#!/usr/bin/env python3
# filepath: /home/mmitache/Projects/polymarket_bot/check_portfolio.py
"""
Quick portfolio P/L check using realistic bid prices.
Run: 
# Basic summary
python check_portfolio.py

# Save to JSON
python check_portfolio.py --save

# Show top 20 gainers/losers
python check_portfolio.py --top 20

# Show all positions
python check_portfolio.py --detailed

# Combine options
python check_portfolio.py --save --detailed --top 15
"""

import sqlite3
from datetime import datetime

DB_FILE = 'scanner_history.db'

def get_portfolio_summary():
    """Get portfolio summary with realistic prices from latest snapshots"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT 
        t.trade_id, t.shares, t.entry_price, t.market_question,
        ps.best_bid, ps.mid_price, ps.spread, ps.bid_liquidity
    FROM trades t
    LEFT JOIN (
        SELECT trade_id, best_bid, mid_price, spread, bid_liquidity,
               ROW_NUMBER() OVER (PARTITION BY trade_id ORDER BY snapshot_date DESC) as rn
        FROM position_snapshots
    ) ps ON t.trade_id = ps.trade_id AND ps.rn = 1
    WHERE t.status = 'open'
    ''')

    rows = cursor.fetchall()
    conn.close()

    total_cost = total_value = 0
    with_price = without_price = 0
    positions = []

    for row in rows:
        trade_id, shares, entry_price, question, best_bid, mid_price, spread, liquidity = row
        cost = shares * entry_price
        total_cost += cost
        
        if best_bid:
            value = shares * best_bid
            total_value += value
            pnl = value - cost
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
            with_price += 1
            positions.append({
                'trade_id': trade_id,
                'question': question[:50] if question else 'Unknown',
                'shares': shares,
                'entry_price': entry_price,
                'best_bid': best_bid,
                'mid_price': mid_price,
                'spread': spread,
                'liquidity': liquidity,
                'cost': cost,
                'value': value,
                'pnl': pnl,
                'pnl_pct': pnl_pct
            })
        else:
            total_value += cost  # Use cost as placeholder
            without_price += 1

    pnl = total_value - total_cost
    mult = total_value / total_cost if total_cost > 0 else 0

    return {
        'timestamp': datetime.now().isoformat(),
        'total_positions': len(rows),
        'with_price': with_price,
        'without_price': without_price,
        'total_cost_basis': total_cost,
        'total_market_value': total_value,
        'unrealized_pnl': pnl,
        'portfolio_multiplier': mult,
        'positions': positions
    }


def print_summary(summary):
    """Print portfolio summary to console"""
    print("=" * 60)
    print("📊 PORTFOLIO SUMMARY (Realistic Prices)")
    print("=" * 60)
    print(f"Timestamp:             {summary['timestamp']}")
    print(f"Open Positions:        {summary['total_positions']}")
    print(f"  - With price data:   {summary['with_price']}")
    print(f"  - Missing price:     {summary['without_price']}")
    print(f"Total Cost Basis:      ${summary['total_cost_basis']:.2f}")
    print(f"Total Market Value:    ${summary['total_market_value']:.2f}")
    print(f"Unrealized P/L:        ${summary['unrealized_pnl']:+.2f}")
    print(f"Portfolio Multiplier:  {summary['portfolio_multiplier']:.2f}x")
    print("=" * 60)


def print_top_positions(summary, n=10):
    """Print top gainers and losers"""
    positions = summary['positions']
    
    if not positions:
        print("No positions with price data.")
        return
    
    # Sort by P/L %
    sorted_positions = sorted(positions, key=lambda x: x['pnl_pct'], reverse=True)
    
    print("\n🚀 TOP GAINERS:")
    print("-" * 60)
    for pos in sorted_positions[:n]:
        print(f"  {pos['pnl_pct']:+.1f}% | ${pos['pnl']:+.2f} | {pos['question']}")
    
    print("\n📉 TOP LOSERS:")
    print("-" * 60)
    for pos in sorted_positions[-n:]:
        print(f"  {pos['pnl_pct']:+.1f}% | ${pos['pnl']:+.2f} | {pos['question']}")


def save_summary(summary, filename=None):
    """Save summary to JSON file"""
    import json
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"portfolio_snapshots/portfolio_{timestamp}.json"
    
    import os
    os.makedirs("portfolio_snapshots", exist_ok=True)
    
    with open(filename, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"\n💾 Saved to: {filename}")
    return filename


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Check portfolio P/L")
    parser.add_argument('--save', action='store_true', help='Save summary to JSON')
    parser.add_argument('--top', type=int, default=10, help='Number of top gainers/losers to show')
    parser.add_argument('--detailed', action='store_true', help='Show all positions')
    args = parser.parse_args()
    
    summary = get_portfolio_summary()
    print_summary(summary)
    print_top_positions(summary, n=args.top)
    
    if args.detailed:
        print("\n📋 ALL POSITIONS:")
        print("-" * 60)
        for pos in summary['positions']:
            print(f"  {pos['pnl_pct']:+.1f}% | ${pos['pnl']:+.2f} | {pos['question']}")
    
    if args.save:
        save_summary(summary)