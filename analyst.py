import json
import os
import time
from dotenv import load_dotenv
from openai import OpenAI

# 1. Setup
load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

INPUT_FILE = "opportunities.json"
OUTPUT_FILE = "approved_trades.json"

# Config
# 0 = Garbage/Impossible, 10 = Great Value
MIN_SCORE_THRESHOLD = 6 

def analyze_opportunity(market):
    """
    Sends the market data to an LLM to determine if it's a 'Trash' bet or a 'Valid Longshot'.
    """
    question = market.get('question', 'Unknown')
    outcome = market.get('outcome_name', 'Unknown')
    price = market.get('price', 0)
    end_date = market.get('end_date', 'Unknown')
    volume = market.get('volume', 0)  # Add volume
    category = market.get('category', 'Unknown')  # Add category if scanner provides it

    system_prompt = """
    You are a skeptical, high-stakes prediction market analyst. Your goal is to filter out "Trash" markets so we don't waste capital.
    
    A "Trash" market is:
    1. Structurally impossible (e.g., asking if a past event will happen).
    2. Internet Meme/Nonsense (e.g., "Will Elon Musk become King of Mars in 2024?").
    3. Highly specific correlations that make no sense.

    A "Valid Longshot" is:
    1. A sports underdog (e.g., Pistons winning a game).
    2. A political edge case (e.g., A candidate dropping out due to health).
    3. A crypto price crash/pump (Volatility is real).
    4. Markets with upcoming catalysts (earnings, elections, games, etc.).
    5. Markets with abnormally wide spreads indicating inefficiency.

    Return JSON ONLY: {
        "score": 0-10, 
        "reason": "short explanation",
        "conviction": "low/medium/high",
        "catalyst_date": "YYYY-MM-DD or null"
    }
    """

    user_prompt = f"""
    Evaluate this market for a "Dust Betting" strategy (buying cheap options < 5 cents).
    
    Market: "{question}"
    Outcome: "{outcome}"
    Price: ${price}
    Volume: ${volume}
    Category: {category}
    Expires: {end_date}
    
    Consider:
    - Is there a potential news catalyst before expiry?
    - Could volatility spike due to external events?
    - Is this market underpriced due to low liquidity/attention?
    
    Is this a valid longshot (High Score) or just burning money (Low Score)?
    """

    try:
        response = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://github.com/mmitache88/polymarket_bots",  # Optional
                "X-Title": "Polymarket Longshot Bot",  # Optional
            },
            model="openai/gpt-4o-mini",  # Use OpenRouter model syntax
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        
        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        print(f"Error analyzing market: {e}")
        return {"score": 0, "reason": "Error"}


def main():
    print("--- AI Analyst Initialized ---")
    
    # 1. Load Opportunities
    if not os.path.exists(INPUT_FILE):
        print(f"File {INPUT_FILE} not found. Run scanner.py first.")
        return

    with open(INPUT_FILE, "r") as f:
        candidates = json.load(f)

    print(f"Loaded {len(candidates)} candidates for analysis.")
    
    approved_trades = []
    costs = 0.0

    # 2. Analyze Loop
    # We use a simple loop. For 500+ items, you might want to use asyncio later, 
    # but for a start, this is easier to debug.
    for i, market in enumerate(candidates):
        print(f"[{i+1}/{len(candidates)}] Analyzing: {market['question'][:40]}... ({market['outcome_name']})")
        
        analysis = analyze_opportunity(market)
        score = analysis.get('score', 0)
        reason = analysis.get('reason', 'No reason provided')
        
        # Log the result
        if score >= MIN_SCORE_THRESHOLD:
            print(f"   >>> APPROVED (Score {score}): {reason}")
            # Attach analysis to the record for the trader to see
            market['analysis'] = analysis
            approved_trades.append(market)
        else:
            print(f"   [REJECTED] (Score {score}): {reason}")

        # Sleep briefly to avoid OpenAI rate limits if you're on a lower tier
        time.sleep(0.3)

    # 3. Save Approved List
    with open(OUTPUT_FILE, "w") as f:
        json.dump(approved_trades, f, indent=2)

    print("\n" + "="*30)
    print(f"ANALYSIS COMPLETE")
    print(f"Input Candidates: {len(candidates)}")
    print(f"Approved Trades:  {len(approved_trades)}")
    print(f"Saved to: {OUTPUT_FILE}")
    print("="*30)

if __name__ == "__main__":
    main()