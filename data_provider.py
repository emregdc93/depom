"""
Data provider module for fetching market data.
"""
import random
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict


class DataProvider:
    """Base class for data providers."""
    
    def get_price_data(self, symbol: str, interval: str = "1h", limit: int = 100) -> pd.DataFrame:
        """Get historical price data."""
        raise NotImplementedError


class MockDataProvider(DataProvider):
    """Mock data provider for testing and simulation."""
    
    def __init__(self):
        """Initialize mock data provider."""
        self.current_price = 50000  # Starting price for BTC
        
    def get_price_data(self, symbol: str, interval: str = "1h", limit: int = 100) -> pd.DataFrame:
        """Generate mock price data with realistic patterns."""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=limit)
        
        # Generate timestamps
        timestamps = pd.date_range(start=start_time, end=end_time, periods=limit)
        
        # Generate realistic price data with trend and volatility
        prices = []
        price = self.current_price
        
        for i in range(limit):
            # Add some trend and random volatility
            trend = 0.0001 * random.normalvariate(0, 1)  # Small trend component
            volatility = 0.02 * random.normalvariate(0, 1)  # 2% volatility
            
            price_change = price * (trend + volatility)
            price = max(price + price_change, 100)  # Minimum price of 100
            prices.append(price)
        
        # Update current price for next call
        self.current_price = prices[-1]
        
        # Create OHLC data
        data = []
        for i, (timestamp, close_price) in enumerate(zip(timestamps, prices)):
            # Generate realistic OHLC from close price
            volatility = close_price * 0.01 * random.random()  # 1% intrabar volatility
            
            high = close_price + random.uniform(0, volatility)
            low = close_price - random.uniform(0, volatility)
            open_price = low + random.uniform(0, high - low)
            
            # Ensure OHLC relationships are maintained
            high = max(high, open_price, close_price)
            low = min(low, open_price, close_price)
            
            volume = random.uniform(100, 1000)
            
            data.append({
                'timestamp': timestamp,
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(close_price, 2),
                'volume': round(volume, 2)
            })
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        return df
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for symbol."""
        return round(self.current_price, 2)


def create_data_provider(provider_type: str = "mock") -> DataProvider:
    """Factory function to create data provider."""
    if provider_type == "mock":
        return MockDataProvider()
    else:
        raise ValueError(f"Unknown data provider type: {provider_type}")