# HFT Bot - High-Frequency Trading for Polymarket

A production-grade, event-driven trading bot for Polymarket's live crypto price markets (BTC/ETH/XRP 1-hour Up/Down markets).

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              HFT Bot                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐     ┌──────────────────┐                          │
│  │ PolymarketGateway│     │  BinanceGateway  │                          │
│  │   (Order Book)   │     │   (BTC/ETH/XRP)  │                          │
│  └────────┬─────────┘     └────────┬─────────┘                          │
│           │                        │                                     │
│           │  MarketUpdate          │  OracleUpdate                       │
│           └───────────┬────────────┘                                     │
│                       ▼                                                  │
│           ┌──────────────────────┐                                       │
│           │   StateAggregator    │                                       │
│           │  (MarketSnapshot)    │                                       │
│           └──────────┬───────────┘                                       │
│                      ▼                                                   │
│           ┌──────────────────────┐                                       │
│           │   StrategyEngine     │                                       │
│           │   (TradeIntent)      │                                       │
│           └──────────┬───────────┘                                       │
│                      ▼                                                   │
│           ┌──────────────────────┐                                       │
│           │    RiskManager       │                                       │
│           │ (Approve/Reject)     │                                       │
│           └──────────┬───────────┘                                       │
│                      ▼                                                   │
│           ┌──────────────────────┐                                       │
│           │  ExecutionService    │                                       │
│           │  (Order Placement)   │                                       │
│           └──────────────────────┘                                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## 📁 Directory Structure

```
strategies/hft/
├── __init__.py
├── README.md                 # This file
├── config.py                 # All configurable parameters
├── models.py                 # Pydantic models (MarketSnapshot, TradeIntent, etc.)
├── db.py                     # HFT-specific database (hft_trades.db)
├── logger.py                 # Structured JSON logging
├── main.py                   # Async event loop entry point
├── gateways/
│   ├── __init__.py
│   ├── polymarket_ws.py      # Polymarket WebSocket (order book)
│   ├── binance_ws.py         # Binance WebSocket (BTC/ETH/XRP prices)
│   └── mock_gateway.py       # Mock data for testing
├── core/
│   ├── __init__.py
│   ├── state_aggregator.py   # Combines Poly + Binance into MarketSnapshot
│   ├── risk_manager.py       # Exposure, drawdown, cooldown checks
│   └── execution_service.py  # Order placement via py-clob-client
└── strategies/
    ├── __init__.py
    ├── base.py               # Abstract strategy interface
    └── early_entry.py        # "Buy low early" strategy
```

## 🚀 Quick Start

### Prerequisites

```bash
# Activate virtual environment
source polyenv/bin/activate

# Ensure you're in project root
cd ~/Projects/polymarket_bot
```

### Environment Variables

Add these to your `.env` file:

```bash
# HFT-specific wallet
POLYGON_PRIVATE_KEY_HFT=0x...
POLYMARKET_PROXY_ADDRESS_HFT=0x...

# Shared settings
HOST=https://clob.polymarket.com
CHAIN_ID=137
```

### Run in Mock Mode (Testing)

```bash
PYTHONPATH=. python strategies/hft/main.py --mock --dry-run
```

### Run in Dry-Run Mode (Live Data, No Real Trades)

```bash
PYTHONPATH=. python strategies/hft/main.py --dry-run --token-id YOUR_TOKEN_ID
```

### Run Live (Real Trading)

```bash
PYTHONPATH=. python strategies/hft/main.py --token-id YOUR_TOKEN_ID
```

## ⚙️ Configuration

Edit `strategies/hft/config.py`:

```python
# Market Selection
MARKETS = ["BTC", "ETH", "XRP"]  # Which assets to trade
TOKEN_IDS = []                   # Specific token IDs (from config)

# Entry Timing
ENTRY_DELAY_MINUTES = 5          # Wait after market opens
EXIT_BUFFER_MINUTES = 5          # Exit before resolution
MAX_ENTRY_PRICE = 0.50           # Don't buy if price > $0.50
MIN_ENTRY_PRICE = 0.05           # Don't buy if price < $0.05

# Position Sizing
MAX_POSITION_SIZE = 50.00        # Max $ per position
MAX_TOTAL_EXPOSURE = 200.00      # Max $ across all positions
MAX_CONCURRENT_POSITIONS = 3     # Max simultaneous positions

# Exit Targets
PROFIT_TARGET_PCT = 10.0         # Exit at +10%
STOP_LOSS_PCT = 20.0             # Exit at -20%
TIME_BASED_EXIT_MINUTES = 10     # Exit if X minutes until resolution

# Risk Management
MAX_DRAWDOWN_PCT = 25.0          # Kill switch at -25% total
COOLDOWN_SECONDS = 10            # Wait between trades
MAX_TRADES_PER_MINUTE = 6        # Rate limit
MAX_SLIPPAGE_PCT = 1.0           # Max acceptable slippage

# Modes
DRY_RUN = True                   # Simulate trades (no real orders)
MOCK_MODE = False                # Use mock data instead of live feeds
KILL_SWITCH = False              # Emergency stop
```

## 📊 Core Components

### 1. Gateways

**PolymarketGateway** - Connects to Polymarket WebSocket for real-time order book:
```python
from strategies.hft.gateways.polymarket_ws import PolymarketGateway

gateway = PolymarketGateway(token_id="0x...")
await gateway.connect()
# Emits MarketUpdate events
```

**BinanceGateway** - Streams live BTC/ETH/XRP prices:
```python
from strategies.hft.gateways.binance_ws import BinanceGateway

gateway = BinanceGateway(symbols=["BTCUSDT", "ETHUSDT"])
await gateway.connect()
# Emits OracleUpdate events
```

**MockGateway** - Simulates market data for testing:
```python
from strategies.hft.gateways.mock_gateway import MockPolymarketGateway

gateway = MockPolymarketGateway(token_id="mock_btc_yes")
await gateway.start()
# Emits simulated MarketUpdate events
```

### 2. State Aggregator

Combines data from both gateways into a single `MarketSnapshot`:

```python
from strategies.hft.core.state_aggregator import StateAggregator

aggregator = StateAggregator(market_info)
aggregator.on_market_update(market_update)
aggregator.on_oracle_update(oracle_update)

snapshot = aggregator.get_snapshot()
# MarketSnapshot with poly_mid_price, oracle_price, probability_edge, etc.
```

### 3. Strategy Engine

Pluggable strategy interface. Default strategy: **EarlyEntryStrategy**

```python
from strategies.hft.strategies.early_entry import EarlyEntryStrategy

strategy = EarlyEntryStrategy(config)
intent = strategy.evaluate(snapshot, inventory)
# Returns TradeIntent (ENTER/EXIT/HOLD)
```

**Strategy Logic:**
- **Entry**: Buy YES or NO when price is below threshold AND market is 5+ minutes old
- **Exit**: Sell when profit target hit OR stop-loss hit OR near resolution

### 4. Risk Manager

Validates all trades before execution:

```python
from strategies.hft.core.risk_manager import RiskManager

risk_manager = RiskManager(risk_config)
result = risk_manager.validate(intent, inventory, snapshot)

if isinstance(result, OrderRequest):
    # Trade approved - execute
elif isinstance(result, Rejection):
    # Trade rejected - log reason
```

**Risk Checks:**
| Check | Description |
|-------|-------------|
| Kill Switch | Blocks all trades when active |
| Cooldown | Enforces wait time between trades |
| Rate Limit | Max trades per minute |
| Max Exposure | Total portfolio limit |
| Max Position | Per-token limit |
| Max Drawdown | Triggers kill switch at threshold |
| Market Timing | Blocks entry near resolution |
| Price Slippage | Rejects if price moved too much |

### 5. Execution Service

Handles order lifecycle:

```python
from strategies.hft.core.execution_service import ExecutionService

executor = ExecutionService(client, config)
report = await executor.execute(order_request)
# ExecutionReport with status, fill price, etc.
```

**Order States:**
```
PENDING → SUBMITTED → ACKNOWLEDGED → FILLED
                   ↘ CANCELLED
                   ↘ REJECTED
```

## 📈 Data Models

### MarketSnapshot
```python
MarketSnapshot(
    token_id="0x...",
    asset="BTC",
    outcome=Outcome.YES,
    strike_price=104500.0,
    poly_best_bid=0.45,
    poly_best_ask=0.47,
    poly_mid_price=0.46,
    poly_spread=0.02,
    oracle_price=104523.50,
    minutes_until_resolution=45.5,
    minutes_since_open=14.5,
    implied_probability=0.46,
    fair_probability=0.52,
    probability_edge=0.06
)
```

### TradeIntent
```python
TradeIntent(
    token_id="0x...",
    action=TradeIntentAction.ENTER,
    side=Side.BUY,
    outcome=Outcome.YES,
    price=0.45,
    size=50.0,
    reason="Price below threshold, market 14min old"
)
```

### Inventory
```python
Inventory(
    positions=[Position(...)],
    total_exposure=150.0,
    realized_pnl=12.50,
    unrealized_pnl=-3.20
)
```

## 🛡️ Safety Features

### Kill Switch

Immediately stops all trading and cancels open orders:

```python
# Activate manually
risk_manager.activate_kill_switch(reason="manual")

# Or automatically on max drawdown
# (Triggers when drawdown >= MAX_DRAWDOWN_PCT)

# Deactivate
risk_manager.deactivate_kill_switch()
```

### Emergency Shutdown

```bash
# Create kill file to stop bot
touch data/hft/KILL_SWITCH

# Bot checks this file every loop iteration
```

### Graceful Shutdown

Press `Ctrl+C` to:
1. Cancel all pending orders
2. Save current state to database
3. Exit cleanly

## 📋 Logging

Structured JSON logs for real-time monitoring:

```json
{"ts": "2025-12-15T10:30:00.123", "level": "INFO", "event": "MARKET_UPDATE", "token": "BTC_YES", "bid": 0.45, "ask": 0.47}
{"ts": "2025-12-15T10:30:00.456", "level": "INFO", "event": "ORACLE_UPDATE", "asset": "BTC", "price": 104523.50}
{"ts": "2025-12-15T10:30:01.789", "level": "INFO", "event": "TRADE_INTENT", "action": "ENTER", "side": "BUY", "price": 0.45}
{"ts": "2025-12-15T10:30:02.012", "level": "INFO", "event": "ORDER_FILLED", "order_id": "abc123", "shares": 100}
```

**Log Locations:**
- Console: Real-time structured output
- File: `logs/hft_YYYYMMDD.log`

## 🗄️ Database

SQLite database at `data/hft/hft_trades.db`:

**Tables:**
- `positions` - Current open positions
- `trades` - Trade history
- `snapshots` - Market snapshots (for analysis)

```bash
# View database
sqlite3 data/hft/hft_trades.db ".tables"
sqlite3 data/hft/hft_trades.db "SELECT * FROM trades LIMIT 10"
```

## 🧪 Testing

### Run with Mock Data

```bash
PYTHONPATH=. python strategies/hft/main.py --mock --dry-run
```

### Test Individual Components

```bash
# Test strategy logic
PYTHONPATH=. python -c "
from strategies.hft.strategies.early_entry import EarlyEntryStrategy
from strategies.hft.models import MarketSnapshot, Inventory, Outcome
from strategies.hft.config import config

strategy = EarlyEntryStrategy(config.strategy)
snapshot = MarketSnapshot(
    token_id='test',
    asset='BTC',
    outcome=Outcome.YES,
    poly_mid_price=0.35,
    minutes_until_resolution=45,
    minutes_since_open=10
)
inventory = Inventory()

intent = strategy.evaluate(snapshot, inventory)
print(f'Intent: {intent}')
"
```

### Test Risk Manager

```bash
PYTHONPATH=. python -c "
from strategies.hft.core.risk_manager import RiskManager
from strategies.hft.config import config

rm = RiskManager(config.risk)
print(f'Stats: {rm.get_stats()}')
"
```

## 📊 Monitoring Commands

```bash
# Check current positions
PYTHONPATH=. python -c "
from strategies.hft.db import get_open_positions
positions = get_open_positions()
for p in positions:
    print(p)
"

# Check recent trades
PYTHONPATH=. python -c "
from strategies.hft.db import get_recent_trades
trades = get_recent_trades(limit=10)
for t in trades:
    print(t)
"

# Check execution stats
PYTHONPATH=. python -c "
from strategies.hft.core.execution_service import ExecutionService
# ... get stats
"
```

## 🔄 Workflow

1. **Market Opens**: Bot detects new 1-hour market
2. **Wait Period**: Waits 5 minutes for prices to stabilize
3. **Entry Signal**: Strategy identifies low-priced YES or NO
4. **Risk Check**: RiskManager validates the trade
5. **Execution**: Order placed on Polymarket
6. **Monitoring**: Tracks position P/L in real-time
7. **Exit Signal**: Profit target, stop-loss, or time-based exit
8. **Execution**: Sell order placed
9. **Repeat**: Move to next opportunity

## ⚠️ Risks & Disclaimers

- **Financial Risk**: Trading involves risk of loss
- **Technical Risk**: WebSocket disconnections, API failures
- **Liquidity Risk**: May not be able to exit at desired price
- **Timing Risk**: Markets resolve on schedule regardless of position

**This bot is for educational purposes. Use at your own risk.**

## 🛠️ Troubleshooting

### Module Not Found
```bash
# Always run with PYTHONPATH
PYTHONPATH=. python strategies/hft/main.py
```

### WebSocket Disconnection
- Bot auto-reconnects with exponential backoff
- Check logs for connection status

### Orders Not Filling
- Check spread - may be too wide
- Check liquidity - may be insufficient
- Check slippage settings

### Kill Switch Triggered
```bash
# Check why
PYTHONPATH=. python -c "
from strategies.hft.core.risk_manager import RiskManager
from strategies.hft.config import config
rm = RiskManager(config.risk)
print(rm.get_stats())
"

# Reset (careful!)
rm.deactivate_kill_switch()
```

## 📝 Future Enhancements

- [ ] Multiple concurrent markets
- [ ] More sophisticated strategies (momentum, mean reversion)
- [ ] Real-time dashboard
- [ ] Telegram/Discord alerts
- [ ] Backtesting framework
- [ ] Performance analytics