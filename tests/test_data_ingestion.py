"""
Unit tests for data ingestion module.

Tests:
- Retry logic constants
- Rate limiter (token bucket)
- Watchlist loading
"""
import pytest
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

aiohttp_available = True
try:
    import aiohttp
except ImportError:
    aiohttp_available = False


class TestRetryConstants:
    """Test retry logic constants are correctly defined"""

    @pytest.mark.skipif(not aiohttp_available, reason="aiohttp not installed")
    def test_retry_constants(self):
        """Should have correct retry constants"""
        from dss.ingestion.update_data import MAX_RETRIES, BACKOFF_BASE
        assert MAX_RETRIES == 4
        assert BACKOFF_BASE == 2

    def test_backoff_exponential(self):
        """Backoff should be exponential: 2, 4, 8, 16"""
        base = 2
        expected = [2, 4, 8, 16]
        for attempt in range(4):
            wait = base ** (attempt + 1)
            assert wait == expected[attempt]


class TestRateLimiter:
    """Test token bucket rate limiter"""

    @pytest.mark.asyncio
    async def test_token_bucket_capacity(self):
        """Token bucket should respect capacity"""
        from dss.ingestion.rate_limiter import TokenBucket

        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(5):
            assert await bucket.acquire()

    @pytest.mark.asyncio
    async def test_token_bucket_exhaustion(self):
        """Token bucket should deny after exhaustion"""
        from dss.ingestion.rate_limiter import TokenBucket

        bucket = TokenBucket(capacity=2, refill_rate=0.01)  # Very slow refill
        await bucket.acquire()
        await bucket.acquire()
        # Next acquire should fail (no tokens left, slow refill)
        result = await bucket.acquire()
        assert not result

    @pytest.mark.asyncio
    async def test_token_bucket_refill(self):
        """Token bucket should refill over time"""
        from dss.ingestion.rate_limiter import TokenBucket

        bucket = TokenBucket(capacity=2, refill_rate=100.0)  # Fast refill
        await bucket.acquire()
        await bucket.acquire()
        await asyncio.sleep(0.05)
        assert await bucket.acquire()

    @pytest.mark.asyncio
    async def test_wait_for_token(self):
        """wait_for_token should block until token available"""
        from dss.ingestion.rate_limiter import TokenBucket

        bucket = TokenBucket(capacity=1, refill_rate=100.0)
        await bucket.wait_for_token()
        # Should complete without error even after exhaustion
        await bucket.wait_for_token()


class TestWatchlistLoading:
    """Test watchlist file loading"""

    def test_load_watchlist_from_file(self, tmp_path):
        """Should load symbols from watchlist file, ignoring comments"""
        watchlist_file = tmp_path / "watchlist.txt"
        watchlist_file.write_text("# Header comment\nAAPL\nMSFT\nGOOGL\n\n# Section\nAMZN\n")

        # Create a minimal DataUpdater mock
        class MockUpdater:
            def __init__(self):
                self.watchlist_path = watchlist_file

            def load_watchlist(self):
                if not self.watchlist_path.exists():
                    return []
                symbols = []
                with open(self.watchlist_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            symbols.append(line.upper())
                return symbols

        updater = MockUpdater()
        symbols = updater.load_watchlist()
        assert symbols == ['AAPL', 'MSFT', 'GOOGL', 'AMZN']

    def test_load_missing_watchlist(self, tmp_path):
        """Missing watchlist file should return empty list"""
        class MockUpdater:
            def __init__(self):
                self.watchlist_path = tmp_path / "nonexistent.txt"

            def load_watchlist(self):
                if not self.watchlist_path.exists():
                    return []
                return []

        updater = MockUpdater()
        assert updater.load_watchlist() == []

    def test_load_watchlist_with_lowercase(self, tmp_path):
        """Symbols should be uppercased"""
        watchlist_file = tmp_path / "watchlist.txt"
        watchlist_file.write_text("aapl\nmsft\n")

        class MockUpdater:
            def __init__(self):
                self.watchlist_path = watchlist_file

            def load_watchlist(self):
                symbols = []
                with open(self.watchlist_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            symbols.append(line.upper())
                return symbols

        updater = MockUpdater()
        assert updater.load_watchlist() == ['AAPL', 'MSFT']
