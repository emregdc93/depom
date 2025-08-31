"""
Portfolio management module for the trading bot.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional


class Portfolio:
    """Manages portfolio balance and positions."""
    
    def __init__(self, initial_balance: float = 10000):
        """Initialize portfolio with initial balance."""
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: Dict[str, float] = {}
        self.trades: List[Dict] = []
        
    def buy(self, symbol: str, quantity: float, price: float) -> bool:
        """Execute a buy order."""
        cost = quantity * price
        if cost <= self.balance:
            self.balance -= cost
            self.positions[symbol] = self.positions.get(symbol, 0) + quantity
            
            trade = {
                'timestamp': datetime.now().isoformat(),
                'action': 'BUY',
                'symbol': symbol,
                'quantity': quantity,
                'price': price,
                'value': cost
            }
            self.trades.append(trade)
            return True
        return False
    
    def sell(self, symbol: str, quantity: float, price: float) -> bool:
        """Execute a sell order."""
        if self.positions.get(symbol, 0) >= quantity:
            value = quantity * price
            self.balance += value
            self.positions[symbol] -= quantity
            
            if self.positions[symbol] == 0:
                del self.positions[symbol]
            
            trade = {
                'timestamp': datetime.now().isoformat(),
                'action': 'SELL',
                'symbol': symbol,
                'quantity': quantity,
                'price': price,
                'value': value
            }
            self.trades.append(trade)
            return True
        return False
    
    def get_position_value(self, symbol: str, current_price: float) -> float:
        """Get current value of position."""
        quantity = self.positions.get(symbol, 0)
        return quantity * current_price
    
    def get_total_value(self, current_prices: Dict[str, float]) -> float:
        """Get total portfolio value."""
        total_value = self.balance
        for symbol, quantity in self.positions.items():
            if symbol in current_prices:
                total_value += quantity * current_prices[symbol]
        return total_value
    
    def get_summary(self, current_prices: Dict[str, float] = None) -> Dict:
        """Get portfolio summary."""
        if current_prices is None:
            current_prices = {}
            
        total_value = self.get_total_value(current_prices)
        profit_loss = total_value - self.initial_balance
        profit_loss_percent = (profit_loss / self.initial_balance) * 100
        
        return {
            'balance': self.balance,
            'positions': self.positions.copy(),
            'total_value': total_value,
            'profit_loss': profit_loss,
            'profit_loss_percent': profit_loss_percent,
            'total_trades': len(self.trades)
        }