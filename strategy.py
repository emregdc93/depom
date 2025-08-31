"""
Trading strategies module.
"""
import pandas as pd
from typing import Dict, Optional, Tuple
from enum import Enum


class Signal(Enum):
    """Trading signals."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Strategy:
    """Base class for trading strategies."""
    
    def __init__(self, config: Dict):
        """Initialize strategy with configuration."""
        self.config = config
        
    def generate_signal(self, data: pd.DataFrame) -> Tuple[Signal, str]:
        """Generate trading signal based on data."""
        raise NotImplementedError
        
    def get_position_size(self, balance: float, price: float) -> float:
        """Calculate position size based on balance and price."""
        trade_amount = balance * self.config.get('trade_amount_percent', 0.1)
        return trade_amount / price


class MovingAverageCrossoverStrategy(Strategy):
    """Moving Average Crossover Strategy."""
    
    def __init__(self, config: Dict):
        """Initialize MA crossover strategy."""
        super().__init__(config)
        self.short_window = config.get('short_window', 10)
        self.long_window = config.get('long_window', 30)
        self.last_signal = Signal.HOLD
        
    def generate_signal(self, data: pd.DataFrame) -> Tuple[Signal, str]:
        """Generate signal based on moving average crossover."""
        if len(data) < max(self.short_window, self.long_window):
            return Signal.HOLD, "Insufficient data for MA calculation"
            
        # Calculate moving averages
        data = data.copy()
        data[f'MA_{self.short_window}'] = data['close'].rolling(window=self.short_window).mean()
        data[f'MA_{self.long_window}'] = data['close'].rolling(window=self.long_window).mean()
        
        # Get latest values
        latest = data.iloc[-1]
        previous = data.iloc[-2] if len(data) >= 2 else data.iloc[-1]
        
        short_ma = latest[f'MA_{self.short_window}']
        long_ma = latest[f'MA_{self.long_window}']
        prev_short_ma = previous[f'MA_{self.short_window}']
        prev_long_ma = previous[f'MA_{self.long_window}']
        
        # Check for crossover
        if pd.isna(short_ma) or pd.isna(long_ma):
            return Signal.HOLD, "MA values not available"
            
        # Golden cross (short MA crosses above long MA) - BUY signal
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            signal = Signal.BUY
            reason = f"Golden cross: MA{self.short_window} ({short_ma:.2f}) > MA{self.long_window} ({long_ma:.2f})"
            
        # Death cross (short MA crosses below long MA) - SELL signal  
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            signal = Signal.SELL
            reason = f"Death cross: MA{self.short_window} ({short_ma:.2f}) < MA{self.long_window} ({long_ma:.2f})"
            
        else:
            signal = Signal.HOLD
            if short_ma > long_ma:
                reason = f"Short MA above long MA: MA{self.short_window} ({short_ma:.2f}) > MA{self.long_window} ({long_ma:.2f})"
            else:
                reason = f"Short MA below long MA: MA{self.short_window} ({short_ma:.2f}) < MA{self.long_window} ({long_ma:.2f})"
        
        self.last_signal = signal
        return signal, reason


def create_strategy(strategy_type: str, config: Dict) -> Strategy:
    """Factory function to create trading strategy."""
    if strategy_type == "moving_average_crossover":
        return MovingAverageCrossoverStrategy(config)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")