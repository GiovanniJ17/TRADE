"""Polygon.io data provider implementation"""
import aiohttp
import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
from loguru import logger

from .base import DataProvider
from .rate_limiter import TokenBucket
from ..utils.config import config


class PolygonProvider(DataProvider):
    """Polygon.io API implementation"""

    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or config.get_env("POLYGON_API_KEY"))
        if not self.api_key:
            raise ValueError("Polygon API key required")

        # Rate limiting via TokenBucket (safe for concurrent requests)
        plan = config.get("data_provider.plan", "free").lower()
        requests_per_minute = config.get("data_provider.requests_per_minute", None)

        if requests_per_minute:
            rpm = int(requests_per_minute)
        elif plan == "free":
            rpm = 5
        elif plan == "starter":
            rpm = 200
        elif plan == "developer":
            rpm = 1000
        elif plan == "advanced":
            rpm = 2000
        else:
            rpm = 5

        # TokenBucket: capacity = burst size (10% of RPM, min 1), refill = tokens/sec
        burst = max(1, rpm // 10)
        refill_rate = rpm / 60.0  # tokens per second
        self._rate_limiter = TokenBucket(capacity=burst, refill_rate=refill_rate)

        logger.info(f"Polygon provider initialized - Plan: {plan}, {rpm} req/min (burst: {burst})")
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _parse_timeframe(self, timeframe: str) -> str:
        """Convert timeframe to Polygon format"""
        mapping = {
            "1W": "week",  # Weekly data
            "1D": "day",
            "1H": "hour",
            "15min": "minute",
            "5min": "minute",
            "1min": "minute"
        }
        return mapping.get(timeframe, "day")
    
    async def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "1D"
    ) -> pd.DataFrame:
        """Fetch historical OHLCV data from Polygon"""
        session = await self._get_session()
        
        # For daily data: allow today after US market close (22:00 CET), else cap to yesterday
        if timeframe == "1D":
            now = datetime.now()
            cap = (now.replace(hour=23, minute=59, second=59, microsecond=999999)
                   if now.hour >= 22 else (now - timedelta(days=1)))
            end_date = min(end_date, cap)
        # For weekly data, use last week as end date
        elif timeframe == "1W":
            end_date = min(end_date, datetime.now() - timedelta(days=7))
        
        # Ensure end_date is not before start_date
        if end_date < start_date:
            logger.warning(f"End date {end_date.date()} is before start date {start_date.date()}")
            return pd.DataFrame()
        
        tf = self._parse_timeframe(timeframe)
        url = f"{self.BASE_URL}/v2/aggs/ticker/{symbol}/range/1/{tf}/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key
        }
        
        try:
            # TokenBucket rate limiting: safe for concurrent requests
            await self._rate_limiter.wait_for_token()
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                        df = pd.DataFrame(data["results"])
                        df = self._normalize_dataframe(df, symbol)
                        return df
                    else:
                        # Log more details for debugging
                        status_msg = data.get("status", "UNKNOWN")
                        results_count = data.get("resultsCount", 0)
                        logger.warning(f"No data for {symbol} from {start_date.date()} to {end_date.date()}. Status: {status_msg}, Results: {results_count}")
                        if "statusMessage" in data:
                            logger.debug(f"Polygon message: {data['statusMessage']}")
                        return pd.DataFrame()
                elif response.status == 429:
                    # Rate limit exceeded - wait longer and retry
                    error_text = await response.text()
                    logger.warning(f"Rate limit exceeded for {symbol}. Waiting 60 seconds before retry...")
                    await asyncio.sleep(60)  # Wait 1 minute
                    # Retry once
                    await self._rate_limiter.wait_for_token()
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                                df = pd.DataFrame(data["results"])
                                df = self._normalize_dataframe(df, symbol)
                                return df
                    logger.error(f"Retry failed for {symbol} after rate limit")
                    return pd.DataFrame()
                else:
                    error_text = await response.text()
                    logger.error(f"Polygon API error {response.status} for {symbol}: {error_text[:200]}")
                    return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return pd.DataFrame()
    
    def _normalize_dataframe(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Normalize Polygon response to standard format"""
        if df.empty:
            return df
        
        # Polygon returns: t (timestamp ms), o, h, l, c, v
        df = df.rename(columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume"
        })
        
        # Convert timestamp from milliseconds to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["symbol"] = symbol
        
        # Ensure proper column order
        df = df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("timestamp")
        
        return df
    
    async def get_latest_snapshot(self, symbol: str) -> Optional[Dict]:
        """
        Get latest snapshot for symbol (~15 min delayed on Starter/Developer).
        Use this for 'current price' instead of last daily bar.
        Returns: {"last_price": float, "updated_utc": int} or None.
        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}"
        params = {"apiKey": self.api_key}
        try:
            await self._rate_limiter.wait_for_token()
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get("status") != "OK":
                    return None
                ticker = data.get("ticker") or {}
                last_price = None
                if ticker.get("lastTrade") and "p" in ticker["lastTrade"]:
                    last_price = float(ticker["lastTrade"]["p"])
                elif ticker.get("min") and "c" in ticker["min"]:
                    last_price = float(ticker["min"]["c"])
                elif ticker.get("day") and "c" in ticker["day"]:
                    last_price = float(ticker["day"]["c"])
                elif ticker.get("prevDay") and "c" in ticker["prevDay"]:
                    last_price = float(ticker["prevDay"]["c"])
                if last_price is None:
                    return None
                updated = ticker.get("updated") or (ticker.get("lastTrade") or {}).get("t") or 0
                return {"last_price": last_price, "updated_utc": updated}
        except Exception as e:
            logger.debug(f"Snapshot for {symbol}: {e}")
            return None

    async def get_latest_bar(self, symbol: str) -> pd.DataFrame:
        """Get the latest bar for a symbol"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)  # Get last 5 days to ensure we get latest
        return await self.get_historical_data(symbol, start_date, end_date, "1D")
    
    async def get_multiple_symbols(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "1D"
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple symbols with optimized rate limiting"""
        results = {}
        
        # Determine batch size based on rate limit
        plan = config.get("data_provider.plan", "free").lower()
        if plan == "free":
            # Free tier: sequential processing
            batch_size = 1
            concurrent = False
        elif plan == "starter":
            # Starter: small batches
            batch_size = 10
            concurrent = True
        elif plan in ["developer", "advanced"]:
            # Higher tiers: larger batches with concurrency
            batch_size = 50
            concurrent = True
        else:
            batch_size = 1
            concurrent = False
        
        if concurrent and batch_size > 1:
            # Process in batches with concurrency
            total_batches = (len(symbols) + batch_size - 1) // batch_size
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                batch_num = i // batch_size + 1
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} symbols)")
                
                tasks = [
                    self.get_historical_data(sym, start_date, end_date, timeframe)
                    for sym in batch
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                success_count = 0
                for symbol, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"Error fetching {symbol}: {result}")
                        results[symbol] = pd.DataFrame()
                    else:
                        results[symbol] = result
                        if not result.empty:
                            success_count += 1
                
                logger.info(f"Batch {batch_num} complete: {success_count}/{len(batch)} symbols fetched successfully")
        else:
            # Sequential processing (free tier)
            for i, symbol in enumerate(symbols, 1):
                logger.info(f"Fetching {symbol} ({i}/{len(symbols)})")
                result = await self.get_historical_data(symbol, start_date, end_date, timeframe)
                results[symbol] = result
        
        return results
    
    async def get_ticker_details(self, symbol: str) -> Optional[Dict]:
        """
        Get ticker details from Polygon Reference API.
        Returns market cap, exchange, type, and other metadata.
        
        Used for Market Scanner filters per spec:
        - Market cap > $500M
        - Exchange: NYSE, NASDAQ, AMEX only
        - Exclude: OTC, ADR, SPAC
        
        Returns:
            Dict with keys: market_cap, primary_exchange, type, name, locale, currency
            or None if not found
        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/v3/reference/tickers/{symbol.upper()}"
        params = {"apiKey": self.api_key}
        
        try:
            await self._rate_limiter.wait_for_token()
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    logger.debug(f"Ticker details not found for {symbol}: {response.status}")
                    return None
                
                data = await response.json()
                if data.get("status") != "OK" or not data.get("results"):
                    return None
                
                results = data["results"]
                return {
                    'symbol': results.get('ticker'),
                    'name': results.get('name'),
                    'market_cap': results.get('market_cap'),  # Can be None
                    'primary_exchange': results.get('primary_exchange'),
                    'type': results.get('type'),  # CS=Common Stock, ETF, ADR, etc.
                    'locale': results.get('locale'),
                    'currency': results.get('currency_name'),
                    'sic_code': results.get('sic_code'),
                    'sic_description': results.get('sic_description'),
                    'share_class_shares_outstanding': results.get('share_class_shares_outstanding'),
                    'weighted_shares_outstanding': results.get('weighted_shares_outstanding')
                }
        except Exception as e:
            logger.debug(f"Error fetching ticker details for {symbol}: {e}")
            return None
    
    async def get_multiple_ticker_details(self, symbols: List[str]) -> Dict[str, Optional[Dict]]:
        """
        Fetch ticker details for multiple symbols.
        Uses batching and rate limiting.
        
        Returns:
            Dict mapping symbol -> ticker details (or None if not found)
        """
        results = {}
        
        # Process in batches
        plan = config.get("data_provider.plan", "free").lower()
        if plan in ["starter", "developer", "advanced"]:
            batch_size = 10
        else:
            batch_size = 1
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            if batch_size > 1:
                tasks = [self.get_ticker_details(sym) for sym in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for symbol, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        results[symbol] = None
                    else:
                        results[symbol] = result
            else:
                for symbol in batch:
                    results[symbol] = await self.get_ticker_details(symbol)
        
        return results