"""
Unit tests for database modules.

Tests:
- MarketDatabase (DuckDB): CRUD, upsert, singleton pattern
- UserDatabase (SQLite): settings, trades, watchlist, connection handling
"""
import pytest
import pandas as pd
import numpy as np
import tempfile
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_market_db():
    """Create a temporary DuckDB database for testing"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_market.duckdb")
    from dss.database.market_db import MarketDatabase
    MarketDatabase._instances.clear()
    db = MarketDatabase(db_path=db_path)
    yield db
    db.close()
    MarketDatabase._instances.clear()
    try:
        os.unlink(db_path)
        os.rmdir(tmpdir)
    except OSError:
        pass


@pytest.fixture
def temp_user_db():
    """Create a temporary SQLite database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    from dss.database.user_db import UserDatabase
    db = UserDatabase(db_path=db_path)
    yield db
    db.close()
    os.unlink(db_path)


@pytest.fixture
def sample_market_data():
    """Generate sample OHLCV data"""
    dates = pd.date_range('2024-01-01', periods=10, freq='B')
    data = pd.DataFrame({
        'timestamp': dates,
        'symbol': 'AAPL',
        'open': np.random.uniform(170, 180, 10),
        'high': np.random.uniform(180, 185, 10),
        'low': np.random.uniform(165, 170, 10),
        'close': np.random.uniform(170, 180, 10),
        'volume': np.random.randint(50_000_000, 100_000_000, 10)
    })
    return data


class TestMarketDatabase:
    """Tests for DuckDB market database"""

    def test_insert_and_retrieve(self, temp_market_db, sample_market_data):
        """Test basic data insertion and retrieval"""
        temp_market_db.insert_data(sample_market_data)
        result = temp_market_db.get_data('AAPL')

        assert len(result) == 10
        assert 'close' in result.columns
        assert 'volume' in result.columns

    def test_insert_empty_df(self, temp_market_db):
        """Insert empty DataFrame should be a no-op"""
        temp_market_db.insert_data(pd.DataFrame())
        result = temp_market_db.get_all_symbols()
        assert len(result) == 0

    def test_upsert_updates_existing(self, temp_market_db, sample_market_data):
        """Inserting same timestamps should update (not duplicate)"""
        temp_market_db.insert_data(sample_market_data)

        # Modify close prices and re-insert
        updated = sample_market_data.copy()
        updated['close'] = updated['close'] + 10

        temp_market_db.insert_data(updated)
        result = temp_market_db.get_data('AAPL')

        assert len(result) == 10  # Same count, not 20

    def test_get_last_timestamp(self, temp_market_db, sample_market_data):
        """Test retrieving last timestamp for a symbol"""
        temp_market_db.insert_data(sample_market_data)
        last_ts = temp_market_db.get_last_timestamp('AAPL')

        assert last_ts is not None
        assert isinstance(last_ts, datetime)

    def test_get_last_timestamp_missing_symbol(self, temp_market_db):
        """Missing symbol should return None"""
        result = temp_market_db.get_last_timestamp('NONEXISTENT')
        assert result is None

    def test_get_all_symbols(self, temp_market_db, sample_market_data):
        """Test listing all symbols in DB"""
        temp_market_db.insert_data(sample_market_data)

        # Add a second symbol
        msft_data = sample_market_data.copy()
        msft_data['symbol'] = 'MSFT'
        temp_market_db.insert_data(msft_data)

        symbols = temp_market_db.get_all_symbols()
        assert 'AAPL' in symbols
        assert 'MSFT' in symbols
        assert len(symbols) == 2

    def test_get_data_date_range(self, temp_market_db, sample_market_data):
        """Test retrieving data within a date range"""
        temp_market_db.insert_data(sample_market_data)

        mid_date = sample_market_data['timestamp'].iloc[5]
        result = temp_market_db.get_data('AAPL', start_date=mid_date)

        assert len(result) <= 5

    def test_singleton_pattern(self, temp_market_db):
        """MarketDatabase should reuse connections for same path"""
        from dss.database.market_db import MarketDatabase
        db2 = MarketDatabase(db_path=str(temp_market_db.db_path))
        assert db2 is temp_market_db

    def test_context_manager(self, sample_market_data):
        """Test context manager protocol"""
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test_ctx.duckdb")
        from dss.database.market_db import MarketDatabase
        MarketDatabase._instances.clear()
        with MarketDatabase(db_path=db_path) as db:
            db.insert_data(sample_market_data)
            result = db.get_data('AAPL')
            assert len(result) == 10
        MarketDatabase._instances.clear()
        try:
            os.unlink(db_path)
            os.rmdir(tmpdir)
        except OSError:
            pass

    def test_invalid_columns_raises(self, temp_market_db):
        """Missing required columns should raise ValueError"""
        bad_data = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=5, freq='B'),
            'symbol': 'BAD',
            'price': [100, 101, 102, 103, 104]
        })
        with pytest.raises(ValueError, match="Missing required columns"):
            temp_market_db.insert_data(bad_data)


class TestUserDatabase:
    """Tests for SQLite user database"""

    def test_setting_crud(self, temp_user_db):
        """Test get/set settings"""
        temp_user_db.set_setting("test_key", "test_value")
        assert temp_user_db.get_setting("test_key") == "test_value"

    def test_setting_default(self, temp_user_db):
        """Missing setting should return default"""
        result = temp_user_db.get_setting("nonexistent", "default_val")
        assert result == "default_val"

    def test_setting_overwrite(self, temp_user_db):
        """Setting same key should overwrite"""
        temp_user_db.set_setting("key1", "value1")
        temp_user_db.set_setting("key1", "value2")
        assert temp_user_db.get_setting("key1") == "value2"

    def test_watchlist_add_remove(self, temp_user_db):
        """Test adding and removing from watchlist"""
        temp_user_db.add_to_watchlist("AAPL", notes="Apple")
        temp_user_db.add_to_watchlist("MSFT", notes="Microsoft")

        watchlist = temp_user_db.get_watchlist()
        symbols = [w['symbol'] for w in watchlist]
        assert 'AAPL' in symbols
        assert 'MSFT' in symbols

        temp_user_db.remove_from_watchlist("AAPL")
        watchlist = temp_user_db.get_watchlist()
        symbols = [w['symbol'] for w in watchlist]
        assert 'AAPL' not in symbols
        assert 'MSFT' in symbols

    def test_watchlist_case_insensitive(self, temp_user_db):
        """Watchlist symbols should be uppercased"""
        temp_user_db.add_to_watchlist("aapl")
        watchlist = temp_user_db.get_watchlist()
        assert watchlist[0]['symbol'] == 'AAPL'

    def test_trade_lifecycle(self, temp_user_db):
        """Test full trade lifecycle: add -> open -> close"""
        temp_user_db.add_trade(
            symbol="NVDA",
            entry_price=800.0,
            quantity=2,
            stop_loss=760.0,
            target_price=880.0,
            notes="Test trade"
        )

        open_trades = temp_user_db.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]['symbol'] == 'NVDA'

        trade_id = open_trades[0]['id']
        temp_user_db.update_trade(trade_id, exit_price=850.0, status='closed')

        open_trades = temp_user_db.get_open_trades()
        assert len(open_trades) == 0

        closed_trades = temp_user_db.get_closed_trades()
        assert len(closed_trades) == 1

    def test_trade_statistics(self, temp_user_db):
        """Test trade statistics calculation"""
        # Add winning trade
        temp_user_db.add_trade("WIN", 100.0, 10, stop_loss=95.0)
        trades = temp_user_db.get_open_trades()
        temp_user_db.update_trade(trades[0]['id'], exit_price=110.0, status='closed')

        # Add losing trade
        temp_user_db.add_trade("LOSS", 100.0, 10, stop_loss=95.0)
        trades = temp_user_db.get_open_trades()
        temp_user_db.update_trade(trades[0]['id'], exit_price=95.0, status='stopped')

        stats = temp_user_db.get_trade_statistics()
        assert stats['total_trades'] == 2
        assert stats['winning_trades'] == 1
        assert stats['losing_trades'] == 1
        assert stats['win_rate'] == 50.0

    def test_delete_trade(self, temp_user_db):
        """Test deleting a trade"""
        temp_user_db.add_trade("DEL", 100.0, 5)
        trades = temp_user_db.get_open_trades()
        assert len(trades) == 1

        temp_user_db.delete_trade(trades[0]['id'])
        trades = temp_user_db.get_open_trades()
        assert len(trades) == 0

    def test_signal_history(self, temp_user_db):
        """Test signal save and retrieval"""
        temp_user_db.save_signal("TSLA", 8.5, entry_price=250.0, stop_loss=240.0)
        signals = temp_user_db.get_recent_signals(days=7)
        assert len(signals) >= 1
        assert signals[0]['symbol'] == 'TSLA'

    def test_alert_tracking(self, temp_user_db):
        """Test price alert sent tracking"""
        assert not temp_user_db.was_price_alert_sent("AAPL", "stop_loss")

        temp_user_db.set_price_alert_sent("AAPL", "stop_loss")
        assert temp_user_db.was_price_alert_sent("AAPL", "stop_loss")

        temp_user_db.clear_alerts_for_symbol("AAPL")
        assert not temp_user_db.was_price_alert_sent("AAPL", "stop_loss")

    def test_reset_all_trades(self, temp_user_db):
        """Test full trade reset"""
        temp_user_db.add_trade("A", 100.0, 1)
        temp_user_db.add_trade("B", 200.0, 2)
        temp_user_db.add_trade("C", 300.0, 3)

        deleted = temp_user_db.reset_all_trades()
        assert deleted == 3
        assert len(temp_user_db.get_open_trades()) == 0
