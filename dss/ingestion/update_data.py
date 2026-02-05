"""Main data ingestion orchestrator with retry logic and rate limiting"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
import pandas as pd
from loguru import logger

from .polygon_provider import PolygonProvider
from ..database.market_db import MarketDatabase
from ..utils.config import config

MAX_RETRIES = 4
BACKOFF_BASE = 2  # seconds


class DataUpdater:
    """Orchestrates data ingestion with retry logic and rate limiting"""

    def __init__(self):
        provider_name = config.get("data_provider.provider", "polygon")
        if provider_name == "polygon":
            self.provider = PolygonProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

        self.db = MarketDatabase()
        self.watchlist_path = Path(config.get("data_provider.symbols_file", "config/watchlist.txt"))

    def load_watchlist(self) -> List[str]:
        """Load symbols from watchlist file"""
        if not self.watchlist_path.exists():
            logger.warning(f"Watchlist file not found: {self.watchlist_path}")
            return []

        symbols = []
        with open(self.watchlist_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    symbols.append(line.upper())

        return symbols

    async def _fetch_with_retry(self, symbol: str, start_date, end_date) -> pd.DataFrame:
        """Fetch data with exponential backoff retry on failure"""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                # Respect rate limiter before each API call
                await self.provider._rate_limiter.wait_for_token()
                df = await self.provider.get_historical_data(
                    symbol, start_date, end_date, "1D"
                )
                return df
            except Exception as e:
                last_error = e
                wait_time = BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    f"{symbol}: Fetch attempt {attempt + 1}/{MAX_RETRIES} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        logger.error(f"{symbol}: All {MAX_RETRIES} fetch attempts failed: {last_error}")
        return pd.DataFrame()

    async def update_symbol(self, symbol: str, force_full: bool = False) -> bool:
        """Update data for a single symbol with retry logic"""
        try:
            # Determine date range: dopo chiusura US (22:00 CET) includi oggi
            now = datetime.now()
            if now.hour >= 22:
                end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                end_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

            if force_full:
                historical_years = config.get("data_provider.historical_years", 5)
                historical_days = historical_years * 365
                start_date = end_date - timedelta(days=historical_days)
                logger.info(f"{symbol}: FORCED full historical download ({historical_years} years) from {start_date.date()}")
            else:
                last_timestamp = self.db.get_last_timestamp(symbol)

                if last_timestamp:
                    start_date = last_timestamp + timedelta(days=1)
                    logger.info(f"{symbol}: Incremental update from {start_date.date()}")
                else:
                    historical_years = config.get("data_provider.historical_years", 5)
                    historical_days = historical_years * 365
                    start_date = end_date - timedelta(days=historical_days)
                    logger.info(f"{symbol}: Full historical download ({historical_years} years) from {start_date.date()}")

            # Skip if start_date is today or future
            if start_date.date() > end_date.date():
                logger.info(f"{symbol}: Already up to date")
                return True

            # Fetch data with retry
            df = await self._fetch_with_retry(symbol, start_date, end_date)

            if df.empty:
                logger.warning(f"{symbol}: No new data available")
                return False

            # Validate data
            if not self.provider.validate_data(df):
                logger.error(f"{symbol}: Invalid data format")
                return False

            # Write to database
            self.db.insert_data(df)
            logger.info(f"{symbol}: Inserted {len(df)} bars")

            return True

        except Exception as e:
            logger.error(f"Error updating {symbol}: {e}")
            return False

    async def update_all(self, symbols: List[str] = None, force_full: bool = False):
        """Update all symbols in watchlist"""
        if symbols is None:
            symbols = self.load_watchlist()

        logger.info(f"Starting data update for {len(symbols)} symbols")

        # Determine batch processing based on plan
        plan = config.get("data_provider.plan", "free").lower()
        if plan == "free":
            batch_size = 1
            concurrent = False
        elif plan == "starter":
            batch_size = 10
            concurrent = True
        elif plan in ["developer", "advanced"]:
            batch_size = 50
            concurrent = True
        else:
            batch_size = 1
            concurrent = False

        success_count = 0

        if concurrent and batch_size > 1:
            total_batches = (len(symbols) + batch_size - 1) // batch_size
            logger.info(f"Using batch processing: {batch_size} symbols per batch, {total_batches} batches")

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                batch_num = i // batch_size + 1
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} symbols)")

                tasks = [self.update_symbol(sym, force_full) for sym in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                batch_success = 0
                for symbol, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"Error updating {symbol}: {result}")
                    elif result:
                        batch_success += 1
                        success_count += 1

                logger.info(f"Batch {batch_num} complete: {batch_success}/{len(batch)} symbols updated")
        else:
            for i, symbol in enumerate(symbols, 1):
                logger.info(f"Processing {symbol} ({i}/{len(symbols)})")
                if await self.update_symbol(symbol, force_full):
                    success_count += 1

        logger.info(f"Update complete: {success_count}/{len(symbols)} symbols updated")

    async def close(self):
        """Cleanup resources"""
        await self.provider.close()
        self.db.close()


async def main(force_full: bool = False):
    """CLI entry point"""
    updater = DataUpdater()
    try:
        await updater.update_all(force_full=force_full)
    finally:
        await updater.close()


if __name__ == "__main__":
    asyncio.run(main())
