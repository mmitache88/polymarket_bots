import sys
import os
# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Updated imports - use shared utilities
from shared.db import init_db, save_analysis_to_db, get_opportunity_id, is_opportunity_analyzed
from shared.logger import setup_logger

# Setup
load_dotenv()
logger = setup_logger('analyst')

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# Updated file paths - use data/ directory
INPUT_FILE = "data/opportunities.json"
OUTPUT_FILE = "data/approved_trades.json"

# Config
MIN_SCORE_THRESHOLD = 6  # 0-10 score threshold for approval
BATCH_SIZE = 20          # Process 20 opportunities simultaneously
MAX_OPPORTUNITIES = None # Set to a number like 100 for testing, None for all

async def analyze_opportunity(market, semaphore):
    """
    Analyze a single opportunity using LLM with rate limiting
    """
    async with semaphore:
        question = market.get('question', 'Unknown')
        outcome = market.get('outcome_name', 'Unknown')
        price = market.get('price', 0)
        end_date = market.get('end_date', 'Unknown')
        volume = market.get('volume', 0)
        category = market.get('category', 'Unknown')
        
        # Calculate implied probability from price
        implied_prob = price * 100  # e.g., $0.02 = 2%

        system_prompt = f"""
You are an ultra-skeptical, risk-aware prediction market analyst for a high-stakes fund.
Your job is to identify "Asymmetric Opportunities" where the market price is significantly lower than the true probability.

**Current Date: {datetime.now().strftime("%Y-%m-%d")}**

---

### YOUR ANALYSIS PROCESS:
1. **ESTIMATE TRUE PROBABILITY**: Based on real-world knowledge, what is the % chance this event happens?
2. **COMPARE TO MARKET**: Is True Probability > (Implied Probability × 3)? If yes, it's asymmetric.
3. **CHECK FOR CATALYSTS**: Is there a scheduled event (election, game, earnings, ruling) that could trigger resolution?

---

### TRASH MARKETS (Score 0-2):
- Structurally impossible (past dates, already resolved)
- Meme/joke/fantasy scenarios (e.g., "Will Elon become King of Mars?")
- Unresolvable or undefined outcomes
- No plausible mechanism or catalyst
- Nonsense correlations

### WEAK MARKETS (Score 3-4):
- Unlikely with no variance driver
- Too far out with no near-term catalyst
- Low information quality

### SPECULATIVE (Score 5-6):
- Longshot with a "puncher's chance"
- Some catalyst exists but uncertain
- Reasonable but not compelling

### ALPHA OPPORTUNITIES (Score 7-10):
- **Asymmetric**: Market says {implied_prob:.1f}%, but true probability is 3x+ higher
- Sports underdogs with real upset potential
- Political edge cases (health, scandal, dropout)
- Crypto volatility plays
- Scheduled binary events (earnings, votes, matches)
- Clear catalyst before expiry

---

### OUTPUT FORMAT (JSON ONLY):
{{
    "score": 0-10,
    "reason": "Concise explanation of the edge or rejection",
    "true_probability_estimate": "e.g., 5%",
    "conviction": "low | medium | high",
    "catalyst_date": "YYYY-MM-DD | null"
}}
"""

        user_prompt = f"""
Evaluate this market for asymmetric opportunity:

**Market:** "{question}"
**Outcome:** {outcome}
**Current Price:** ${price:.4f} (Implied Probability: {implied_prob:.1f}%)
**Volume:** ${volume:,.0f}
**Category:** {category}
**Expires:** {end_date}

Is the TRUE probability significantly higher than {implied_prob:.1f}%? 
Is there a catalyst before expiry?
"""

        try:
            response = await client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://github.com/mmitache88/polymarket_bots",
                    "X-Title": "Polymarket Longshot Bot",
                },
                model="openai/gpt-4o-mini",
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
            logger.error(f"Error analyzing market '{question[:50]}...': {e}")
            return {"score": 0, "reason": f"Error: {str(e)}", "conviction": "low", "catalyst_date": None, "true_probability_estimate": "0%"}



async def process_batch(batch, batch_num, total_batches):
    """
    Process a batch of opportunities concurrently
    """
    semaphore = asyncio.Semaphore(BATCH_SIZE)  # Limit concurrent API calls
    
    logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} opportunities)")
    
    # Create tasks for all opportunities in batch
    tasks = [analyze_opportunity(market, semaphore) for market in batch]
    
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)
    
    return results

async def main_async():
    logger.info("=" * 60)
    logger.info("🤖 AI Analyst Initialized (Async Batch Mode)")
    logger.info("=" * 60)
    logger.info(f"Batch Size: {BATCH_SIZE} concurrent requests")
    logger.info(f"Min Score: {MIN_SCORE_THRESHOLD}/10 for approval")
    
    # Initialize database
    init_db()
    
    # Load opportunities
    if not os.path.exists(INPUT_FILE):
        logger.error(f"❌ File {INPUT_FILE} not found. Run scanner.py first.")
        return

    with open(INPUT_FILE, "r") as f:
        all_opportunities = json.load(f)

    # Limit for testing if configured
    if MAX_OPPORTUNITIES:
        all_opportunities = all_opportunities[:MAX_OPPORTUNITIES]
        logger.info(f"⚠️  Limited to {MAX_OPPORTUNITIES} opportunities for testing")

    logger.info(f"📊 Loaded {len(all_opportunities)} opportunities from scanner")
    
    # Filter out already-analyzed opportunities
    opportunities_to_analyze = []
    skipped_count = 0
    
    for opp in all_opportunities:
        opportunity_id = get_opportunity_id(opp['market_id'], opp['outcome_id'])
        if opportunity_id and is_opportunity_analyzed(opportunity_id):
            skipped_count += 1
            continue
        opportunities_to_analyze.append(opp)
    
    if skipped_count > 0:
        logger.info(f"⏭️  Skipped {skipped_count} already-analyzed opportunities")
    
    logger.info(f"🆕 New opportunities to analyze: {len(opportunities_to_analyze)}")
    
    if not opportunities_to_analyze:
        logger.warning("⚠️  No new opportunities to analyze!")
        return
    
    # Split into batches
    batches = [opportunities_to_analyze[i:i + BATCH_SIZE] 
               for i in range(0, len(opportunities_to_analyze), BATCH_SIZE)]
    
    total_batches = len(batches)
    approved_trades = []
    total_processed = 0
    
    logger.info("=" * 60)
    
    # Process batches
    for batch_num, batch in enumerate(batches, 1):
        try:
            # Analyze batch concurrently
            results = await process_batch(batch, batch_num, total_batches)
            
            # Save results
            for market, analysis in zip(batch, results):
                total_processed += 1
                score = analysis.get('score', 0)
                reason = analysis.get('reason', 'No reason provided')
                conviction = analysis.get('conviction', 'low')
                catalyst_date = analysis.get('catalyst_date', None)
                
                # Determine if approved
                approved = score >= MIN_SCORE_THRESHOLD
                
                # Save to database
                try:
                    opportunity_id = get_opportunity_id(market['market_id'], market['outcome_id'])
                    if opportunity_id:
                        save_analysis_to_db(opportunity_id, analysis, approved)
                except Exception as e:
                    logger.warning(f"⚠️  Could not save analysis to DB: {e}")
                
                # Truncate question for logging
                question_short = market['question'][:60] + "..." if len(market['question']) > 60 else market['question']
                
                if approved:
                    logger.info(f"✅ [{total_processed}/{len(opportunities_to_analyze)}] APPROVED (Score: {score}/10, Conviction: {conviction.upper()})")
                    logger.info(f"   📊 {question_short}")
                    logger.info(f"   💰 {market['outcome_name']} @ ${market['price']}")
                    logger.info(f"   💡 {reason}")
                    if catalyst_date:
                        logger.info(f"   📅 Catalyst: {catalyst_date}")
                    
                    # Attach analysis for trader
                    market['analysis'] = analysis
                    approved_trades.append(market)
                else:
                    logger.debug(f"❌ [{total_processed}/{len(opportunities_to_analyze)}] REJECTED (Score: {score}/10)")
                    logger.debug(f"   {question_short}")
                    logger.debug(f"   Reason: {reason}")
            
            # Small delay between batches to avoid rate limits
            if batch_num < total_batches:
                await asyncio.sleep(0.5)
                
        except KeyboardInterrupt:
            logger.warning("\n⚠️  Analysis interrupted by user")
            logger.info(f"Processed {total_processed}/{len(opportunities_to_analyze)} opportunities before interruption")
            break
        except Exception as e:
            logger.error(f"❌ Error processing batch {batch_num}: {e}")
            continue
    
    # Save approved trades to JSON file
    with open(OUTPUT_FILE, "w") as f:
        json.dump(approved_trades, f, indent=2)

    logger.info("=" * 60)
    logger.info("✅ ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"📊 Opportunities Analyzed: {total_processed}")
    logger.info(f"✅ Approved Trades: {len(approved_trades)}")
    logger.info(f"📈 Approval Rate: {len(approved_trades)/total_processed*100:.1f}%" if total_processed > 0 else "📈 Approval Rate: 0.0%")
    logger.info(f"💾 Saved to: {OUTPUT_FILE}")
    logger.info("=" * 60)

def main():
    """Wrapper to run async main"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Analysis interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()