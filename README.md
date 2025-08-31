# Depom Trading Bot

A Python-based trading bot that implements automated trading strategies with simulated execution.

## Features

- **Moving Average Crossover Strategy**: Implements golden cross and death cross signals
- **Portfolio Management**: Tracks balance, positions, and trade history
- **Mock Data Provider**: Generates realistic market data for testing
- **Configurable Parameters**: Easy configuration through JSON file
- **Logging**: Comprehensive logging of all trading activities
- **Paper Trading**: Safe simulation mode without real money

## Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Trading Bot**:
   ```bash
   python main.py
   ```

The bot will run a demo with 5 iterations and show the results.

## Configuration

Edit `config.json` to customize the trading bot:

```json
{
  "trading": {
    "initial_balance": 10000,
    "symbol": "BTCUSDT", 
    "strategy": "moving_average_crossover",
    "short_window": 10,
    "long_window": 30,
    "trade_amount_percent": 0.1
  },
  "data": {
    "source": "mock",
    "interval": "1h"
  },
  "logging": {
    "level": "INFO",
    "file": "trading_bot.log"
  }
}
```

### Configuration Parameters

- `initial_balance`: Starting balance in USD
- `symbol`: Trading pair symbol
- `strategy`: Trading strategy to use
- `short_window`: Short-term moving average period
- `long_window`: Long-term moving average period  
- `trade_amount_percent`: Percentage of balance to use per trade
- `source`: Data source ("mock" for simulation)
- `interval`: Data interval ("1h" for hourly)
- `level`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `file`: Log file name

## Strategy

The bot uses a **Moving Average Crossover** strategy:

- **Golden Cross** (BUY): When short MA crosses above long MA
- **Death Cross** (SELL): When short MA crosses below long MA
- **Hold**: When no crossover occurs

## Architecture

- `main.py`: Main trading bot orchestrator
- `strategy.py`: Trading strategy implementations
- `portfolio.py`: Portfolio and trade management
- `data_provider.py`: Market data providers
- `config.json`: Configuration settings
- `requirements.txt`: Python dependencies

## Usage Examples

### Basic Usage
```python
from main import TradingBot

# Create bot with default config
bot = TradingBot()

# Run for 10 iterations with 60-second intervals
report = bot.run(iterations=10, delay=60)
```

### Custom Configuration
```python
# Use custom config file
bot = TradingBot("my_config.json")

# Run continuously (Ctrl+C to stop)
bot.run()
```

### Single Iteration
```python
bot = TradingBot()
result = bot.run_single_iteration()
print(result)
```

## Output

The bot provides detailed logging and final reports:

```
=== FINAL REPORT ===
Initial Balance: $10000.00
Final Value: $10150.25
Total Return: $150.25
Return %: 1.50%
Total Trades: 4
```

## Safety

This is a **simulation-only** trading bot using mock data. No real trades are executed. Always thoroughly test any trading strategy before considering live implementation.