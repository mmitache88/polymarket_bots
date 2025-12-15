# Market Selection
MARKETS = ["BTC", "ETH", "XRP"]  # Which assets to trade
MARKET_DURATION = 60  # 1-hour markets (in minutes)

# Entry
ENTRY_DELAY_MINUTES = 5  # Wait 5 min after market opens
MAX_ENTRY_PRICE = 0.50  # Don't buy YES/NO if price > $0.50

# Position Sizing
MAX_POSITION_SIZE = 50.00  # Max $ per position
MAX_TOTAL_EXPOSURE = 200.00  # Max $ across all positions
MAX_CONCURRENT_POSITIONS = 3  # Max simultaneous positions

# Exit
PROFIT_TARGET_PCT = 10.0  # Exit at +10%
STOP_LOSS_PCT = 20.0  # Exit at -20%
EXIT_BUFFER_MINUTES = 5  # Exit 5 min before resolution

# Risk
MAX_DRAWDOWN_PCT = 25.0  # Kill switch at -25% total
COOLDOWN_SECONDS = 10  # Wait between trades

# Kill Switch
KILL_SWITCH = False  # Set True to stop everything

# Mode
DRY_RUN = True  # Start in simulation mode
MOCK_MODE = True  # Use mock data instead of live feeds