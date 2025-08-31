"""
Main trading bot implementation.
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional

from portfolio import Portfolio
from data_provider import create_data_provider
from strategy import create_strategy, Signal


class TradingBot:
    """Main trading bot class."""
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize trading bot with configuration."""
        self.config = self._load_config(config_path)
        self.portfolio = Portfolio(self.config['trading']['initial_balance'])
        self.data_provider = create_data_provider(self.config['data']['source'])
        self.strategy = create_strategy(
            self.config['trading']['strategy'],
            self.config['trading']
        )
        self.symbol = self.config['trading']['symbol']
        self.running = False
        
        # Setup logging
        self._setup_logging()
        self.logger.info("Trading bot initialized")
        
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from file."""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file {config_path} not found")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")
            
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config['logging']['level'], logging.INFO)
        log_file = self.config['logging']['file']
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def run_single_iteration(self) -> Dict:
        """Run a single trading iteration."""
        try:
            # Get market data
            data = self.data_provider.get_price_data(
                self.symbol,
                self.config['data']['interval'],
                100
            )
            
            if data.empty:
                self.logger.warning("No data received")
                return {'status': 'no_data'}
                
            current_price = data['close'].iloc[-1]
            
            # Generate trading signal
            signal, reason = self.strategy.generate_signal(data)
            
            self.logger.info(f"Signal: {signal.value}, Reason: {reason}, Price: ${current_price:.2f}")
            
            # Execute trades based on signal
            trade_executed = False
            if signal == Signal.BUY and self.portfolio.balance > 0:
                position_size = self.strategy.get_position_size(self.portfolio.balance, current_price)
                if self.portfolio.buy(self.symbol, position_size, current_price):
                    self.logger.info(f"BUY executed: {position_size:.6f} {self.symbol} at ${current_price:.2f}")
                    trade_executed = True
                else:
                    self.logger.warning("BUY order failed - insufficient balance")
                    
            elif signal == Signal.SELL and self.portfolio.positions.get(self.symbol, 0) > 0:
                position_size = self.portfolio.positions[self.symbol]
                if self.portfolio.sell(self.symbol, position_size, current_price):
                    self.logger.info(f"SELL executed: {position_size:.6f} {self.symbol} at ${current_price:.2f}")
                    trade_executed = True
                else:
                    self.logger.warning("SELL order failed - no position to sell")
            
            # Get portfolio summary
            portfolio_summary = self.portfolio.get_summary({self.symbol: current_price})
            
            return {
                'status': 'success',
                'timestamp': datetime.now().isoformat(),
                'price': current_price,
                'signal': signal.value,
                'reason': reason,
                'trade_executed': trade_executed,
                'portfolio': portfolio_summary
            }
            
        except Exception as e:
            self.logger.error(f"Error in trading iteration: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def run(self, iterations: Optional[int] = None, delay: int = 3600):
        """Run the trading bot."""
        self.logger.info("Starting trading bot...")
        self.running = True
        
        iteration_count = 0
        try:
            while self.running:
                iteration_count += 1
                self.logger.info(f"=== Iteration {iteration_count} ===")
                
                result = self.run_single_iteration()
                
                # Log portfolio status
                if result['status'] == 'success':
                    portfolio = result['portfolio']
                    self.logger.info(f"Portfolio - Balance: ${portfolio['balance']:.2f}, "
                                   f"Total Value: ${portfolio['total_value']:.2f}, "
                                   f"P&L: ${portfolio['profit_loss']:.2f} "
                                   f"({portfolio['profit_loss_percent']:.2f}%)")
                
                # Check if we should stop
                if iterations and iteration_count >= iterations:
                    break
                    
                # Wait before next iteration (unless it's the last one)
                if not iterations or iteration_count < iterations:
                    self.logger.info(f"Waiting {delay} seconds until next iteration...")
                    time.sleep(delay)
                    
        except KeyboardInterrupt:
            self.logger.info("Trading bot stopped by user")
        finally:
            self.running = False
            self.logger.info("Trading bot stopped")
            
        return self.get_final_report()
    
    def get_final_report(self) -> Dict:
        """Generate final trading report."""
        current_price = self.data_provider.get_current_price(self.symbol)
        portfolio_summary = self.portfolio.get_summary({self.symbol: current_price})
        
        report = {
            'final_portfolio': portfolio_summary,
            'trades': self.portfolio.trades,
            'performance': {
                'initial_balance': self.portfolio.initial_balance,
                'final_value': portfolio_summary['total_value'],
                'total_return': portfolio_summary['profit_loss'],
                'return_percentage': portfolio_summary['profit_loss_percent'],
                'total_trades': len(self.portfolio.trades)
            }
        }
        
        self.logger.info("=== FINAL REPORT ===")
        self.logger.info(f"Initial Balance: ${report['performance']['initial_balance']:.2f}")
        self.logger.info(f"Final Value: ${report['performance']['final_value']:.2f}")
        self.logger.info(f"Total Return: ${report['performance']['total_return']:.2f}")
        self.logger.info(f"Return %: {report['performance']['return_percentage']:.2f}%")
        self.logger.info(f"Total Trades: {report['performance']['total_trades']}")
        
        return report


if __name__ == "__main__":
    # Demo run
    bot = TradingBot()
    
    print("=== Trading Bot Demo ===")
    print("Running 5 iterations with 5-second intervals...")
    
    # Run for 5 iterations with 5-second delay for demo
    final_report = bot.run(iterations=5, delay=5)
    
    print("\n=== Demo Complete ===")
    print(f"Final Portfolio Value: ${final_report['performance']['final_value']:.2f}")
    print(f"Total Return: ${final_report['performance']['return_percentage']:.2f}%")
    print(f"Total Trades: {final_report['performance']['total_trades']}")