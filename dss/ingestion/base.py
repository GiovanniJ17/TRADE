"""Abstract base class for data providers"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd


class DataProvider(ABC):
    """Abstract base class for market data providers"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.rate_limit_delay = 0.1  # Default delay between requests
    
    @abstractmethod
    async def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "1D"
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe (1D, 1H, 15min, etc.)
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        pass
    
    @abstractmethod
    async def get_latest_bar(self, symbol: str) -> pd.DataFrame:
        """Get the latest bar for a symbol"""
        pass
    
    @abstractmethod
    async def get_multiple_symbols(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "1D"
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple symbols efficiently"""
        pass
    
    def validate_data(self, df: pd.DataFrame) -> bool:
        """Validate data quality"""
        if df.empty:
            return False
        required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        return all(col in df.columns for col in required_cols)
