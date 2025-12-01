import sqlite3

DB_FILE = "scanner_history.db"

def analyze_llm_accuracy():
    """Check if LLM scores correlate with actual outcomes"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        AVG(a.score) as avg_score,
        a.conviction,
        COUNT(*) as count,
        SUM(CASE WHEN a.approved THEN 1 ELSE 0 END) as approved_count
    FROM analyses a
    GROUP BY a.conviction
    ORDER BY avg_score DESC
    """)
    
    print("\n📊 LLM Performance by Conviction Level:")
    print("=" * 60)
    for row in cursor.fetchall():
        conviction = row[1] or "unknown"
        avg_score = row[0]
        total = row[2]
        approved = row[3]
        approval_rate = (approved / total * 100) if total > 0 else 0
        print(f"  {conviction.upper()}: Avg Score={avg_score:.2f}, Total={total}, Approved={approved} ({approval_rate:.1f}%)")
    
    conn.close()

def analyze_score_distribution():
    """Show distribution of LLM scores"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        CASE 
            WHEN score <= 2 THEN '0-2 (Trash)'
            WHEN score <= 4 THEN '3-4 (Poor)'
            WHEN score <= 6 THEN '5-6 (Marginal)'
            WHEN score <= 8 THEN '7-8 (Good)'
            ELSE '9-10 (Excellent)'
        END as score_range,
        COUNT(*) as count,
        SUM(CASE WHEN approved THEN 1 ELSE 0 END) as approved_count
    FROM analyses
    GROUP BY score_range
    ORDER BY MIN(score)
    """)
    
    print("\n📈 Score Distribution:")
    print("=" * 60)
    for row in cursor.fetchall():
        score_range = row[0]
        total = row[1]
        approved = row[2]
        approval_rate = (approved / total * 100) if total > 0 else 0
        print(f"  {score_range}: Total={total}, Approved={approved} ({approval_rate:.1f}%)")
    
    conn.close()

def analyze_persistent_opportunities():
    """Find markets that remain cheap across multiple scans"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        o.question,
        o.outcome_name,
        COUNT(DISTINCT o.scan_id) as scan_appearances,
        COUNT(a.analysis_id) as times_analyzed,
        AVG(a.score) as avg_score,
        MAX(a.approved) as ever_approved
    FROM opportunities o
    LEFT JOIN analyses a ON o.id = a.opportunity_id
    GROUP BY o.market_id, o.outcome_id
    HAVING scan_appearances > 1
    ORDER BY scan_appearances DESC, times_analyzed DESC
    LIMIT 10
    """)
    
    print("\n🔁 Persistent Low-Price Opportunities:")
    print("=" * 60)
    results = cursor.fetchall()
    if results:
        for i, row in enumerate(results, 1):
            question = row[0][:60] + "..." if len(row[0]) > 60 else row[0]
            outcome = row[1]
            scans = row[2]
            analyzed = row[3]
            avg_score = row[4] if row[4] else 0
            approved = "✅ Yes" if row[5] else "❌ No"
            print(f"  {i}. {question}")
            print(f"     Outcome: {outcome}")
            print(f"     Scans: {scans} | Analyzed: {analyzed} | Avg Score: {avg_score:.1f} | Ever Approved: {approved}")
    else:
        print("  No markets found in multiple scans yet.")
    
    conn.close()

def analyze_approval_trends():
    """Show approval trends over time"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        DATE(a.analysis_date) as analysis_day,
        COUNT(*) as total_analyzed,
        SUM(CASE WHEN a.approved THEN 1 ELSE 0 END) as approved_count,
        AVG(a.score) as avg_score
    FROM analyses a
    GROUP BY analysis_day
    ORDER BY analysis_day DESC
    LIMIT 10
    """)
    
    print("\n📅 Daily Analysis Trends (Last 10 Days):")
    print("=" * 60)
    results = cursor.fetchall()
    if results:
        for row in results:
            day = row[0]
            total = row[1]
            approved = row[2]
            avg_score = row[3]
            approval_rate = (approved / total * 100) if total > 0 else 0
            print(f"  {day}: Analyzed={total}, Approved={approved} ({approval_rate:.1f}%), Avg Score={avg_score:.2f}")
    else:
        print("  No analysis data yet.")
    
    conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 Polymarket Bot - LLM Analysis Performance Report")
    print("=" * 60)
    
    analyze_llm_accuracy()
    analyze_score_distribution()
    analyze_most_analyzed_markets()
    analyze_approval_trends()
    
    print("\n" + "=" * 60)
    print("Report Complete!")
    print("=" * 60)