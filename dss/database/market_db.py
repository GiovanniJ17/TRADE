"""DuckDB market data database"""
import duckdb
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import pandas as pd
from loguru import logger

from ..utils.config import config


class MarketDatabase:
    """DuckDB database for market data (OLAP)"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or config.get_env("DUCKDB_PATH", "./data/market_data.duckdb"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir = Path(config.get_env("DATA_DIR", "./data/parquet"))
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        
        self.conn = duckdb.connect(str(self.db_path))
        self._initialize_schema()
    
    def _initialize_schema(self):
        """Initialize database schema"""
        # Create main table for market data
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                timestamp TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                PRIMARY KEY (timestamp, symbol)
            )
        """)
        
        # Create indexes for faster queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_timestamp 
            ON market_data(symbol, timestamp)
        """)
        
        # Additional index for date range queries (useful with more historical data)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON market_data(timestamp)
        """)
        
        logger.info("Market database schema initialized")
    
    def insert_data(self, df: pd.DataFrame):
        """Insert or update data (upsert)"""
        if df.empty:
            return
        
        # Ensure required columns
        required_cols = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"Missing required columns. Got: {df.columns.tolist()}")
        
        # Convert timestamp to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # DuckDB upsert: Delete existing records first, then insert
        # Wrapped in transaction to prevent data loss on interruption
        self.conn.register('temp_data', df)
        
        try:
            self.conn.execute("BEGIN TRANSACTION")
            
            # Delete existing records for these timestamps/symbols
            self.conn.execute("""
                DELETE FROM market_data
                WHERE (timestamp, symbol) IN (
                    SELECT timestamp, symbol FROM temp_data
                )
            """)
            
            # Insert new data
            self.conn.execute("""
                INSERT INTO market_data 
                SELECT timestamp, symbol, open, high, low, close, volume
                FROM temp_data
            """)
            
            self.conn.execute("COMMIT")
        except Exception as e:
            self.conn.execute("ROLLBACK")
            raise e
        finally:
            self.conn.unregister('temp_data')
    
    def get_data(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Query market data"""
        query = "SELECT * FROM market_data WHERE symbol = ?"
        params = [symbol]
        
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        
        query += " ORDER BY timestamp"
        
        return self.conn.execute(query, params).df()
    
    def get_last_timestamp(self, symbol: str) -> Optional[datetime]:
        """Get the last timestamp for a symbol"""
        result = self.conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM market_data WHERE symbol = ?",
            [symbol]
        ).fetchone()
        
        if result and result[0]:
            return result[0]
        return None
    
    def get_latest_bars(self, symbols: List[str], lookback_days: int = 252) -> pd.DataFrame:
        """Get latest N days of data for multiple symbols"""
        placeholders = ','.join(['?' for _ in symbols])
        cutoff_date = datetime.now() - pd.Timedelta(days=lookback_days)
        
        query = f"""
            SELECT * FROM market_data 
            WHERE symbol IN ({placeholders}) 
            AND timestamp >= ?
            ORDER BY symbol, timestamp
        """
        
        params = symbols + [cutoff_date]
        return self.conn.execute(query, params).df()

    def get_bars_until(
        self,
        symbols: List[str],
        end_date_inclusive: datetime,
        lookback_days: int = 252
    ) -> pd.DataFrame:
        """Get bars for symbols up to and including end_date (for backtest / as-of date)."""
        if not symbols:
            return pd.DataFrame()
        placeholders = ','.join(['?' for _ in symbols])
        cutoff = end_date_inclusive - pd.Timedelta(days=lookback_days)
        # end_date_inclusive: include that day (timestamp <= end of day)
        end_next = end_date_inclusive + pd.Timedelta(days=1)
        query = f"""
            SELECT * FROM market_data
            WHERE symbol IN ({placeholders})
            AND timestamp >= ?
            AND timestamp < ?
            ORDER BY symbol, timestamp
        """
        params = symbols + [cutoff, end_next]
        return self.conn.execute(query, params).df()

    def get_data_for_date(self, symbol: str, date: datetime) -> pd.DataFrame:
        """Get single day OHLCV for a symbol (for backtest outcome check)."""
        start = pd.Timestamp(date).normalize()
        end = start + pd.Timedelta(days=1)
        return self.get_data(symbol, start, end)
    
    def get_all_symbols(self) -> List[str]:
        """Get list of all symbols in database"""
        result = self.conn.execute("SELECT DISTINCT symbol FROM market_data").fetchall()
        return [row[0] for row in result]
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures connection is closed"""
        self.close()
        return False  # Don't suppress exceptions
