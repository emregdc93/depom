"""
Simple test script to verify trading bot functionality.
"""
from main import TradingBot
import json

def test_trading_bot():
    """Test the trading bot with more sensitive parameters."""
    
    # Create a more sensitive configuration for testing
    test_config = {
        "trading": {
            "initial_balance": 10000,
            "symbol": "BTCUSDT",
            "strategy": "moving_average_crossover",
            "short_window": 3,  # Very short window for more signals
            "long_window": 7,   # Short long window for more signals
            "trade_amount_percent": 0.2
        },
        "data": {
            "source": "mock",
            "interval": "1h"
        },
        "logging": {
            "level": "INFO",
            "file": "test_trading_bot.log"
        }
    }
    
    # Save test config
    with open('test_config.json', 'w') as f:
        json.dump(test_config, f, indent=2)
    
    print("=== Trading Bot Test ===")
    print("Testing with sensitive MA parameters (MA3/MA7) to generate signals...")
    
    # Create bot with test config
    bot = TradingBot('test_config.json')
    
    # Run for more iterations to increase chance of crossovers
    report = bot.run(iterations=10, delay=2)
    
    print("\n=== Test Results ===")
    print(f"Initial Balance: ${report['performance']['initial_balance']:.2f}")
    print(f"Final Value: ${report['performance']['final_value']:.2f}")
    print(f"Total Return: ${report['performance']['total_return']:.2f}")
    print(f"Return %: {report['performance']['return_percentage']:.2f}%")
    print(f"Total Trades: {report['performance']['total_trades']}")
    
    if report['performance']['total_trades'] > 0:
        print("\nTrades executed:")
        for i, trade in enumerate(report['trades'], 1):
            print(f"  {i}. {trade['action']} {trade['quantity']:.6f} {trade['symbol']} "
                  f"at ${trade['price']:.2f} on {trade['timestamp'][:19]}")
        print("\nTest PASSED: Trading bot executed trades successfully!")
    else:
        print("\nTest INFO: No trades executed (market conditions didn't trigger crossovers)")
    
    # Clean up
    import os
    try:
        os.remove('test_config.json')
        os.remove('test_trading_bot.log')
    except FileNotFoundError:
        pass

if __name__ == "__main__":
    test_trading_bot()