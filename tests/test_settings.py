"""
Unit tests for settings persistence and workflow.

Converted from:
- scripts/test_settings_persistence.py
- scripts/test_settings_workflow.py

Tests:
- Settings saved and loaded correctly from database
- Manual modifications after preset are respected
- Reload preserves latest settings
"""
import pytest
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def user_db():
    """Create a temporary user database"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    from dss.database.user_db import UserDatabase
    db = UserDatabase(db_path=db_path)
    yield db
    db.close()
    os.unlink(db_path)


class TestSettingsPersistence:
    """Converted from scripts/test_settings_persistence.py"""

    def test_save_and_load_settings(self, user_db):
        """Settings should be saved and loaded correctly"""
        user_db.set_setting("portfolio_total_capital", "10000")
        user_db.set_setting("portfolio_stock_allocation", "0.80")
        user_db.set_setting("portfolio_cash_reserve", "0.20")
        user_db.set_setting("portfolio_max_stock_positions", "2")
        user_db.set_setting("risk_per_stock_trade", "15")

        assert user_db.get_setting("portfolio_total_capital") == "10000"
        assert user_db.get_setting("portfolio_stock_allocation") == "0.80"
        assert user_db.get_setting("portfolio_cash_reserve") == "0.20"
        assert user_db.get_setting("portfolio_max_stock_positions") == "2"
        assert user_db.get_setting("risk_per_stock_trade") == "15"

    def test_setting_overwrite(self, user_db):
        """Updating a setting should overwrite the old value"""
        user_db.set_setting("portfolio_total_capital", "5000")
        assert user_db.get_setting("portfolio_total_capital") == "5000"

        user_db.set_setting("portfolio_total_capital", "15000")
        assert user_db.get_setting("portfolio_total_capital") == "15000"

    def test_setting_defaults(self, user_db):
        """Missing settings should return provided default"""
        result = user_db.get_setting("nonexistent_key", "default123")
        assert result == "default123"

    def test_setting_none_default(self, user_db):
        """Missing settings without default should return None"""
        result = user_db.get_setting("nonexistent_key")
        assert result is None


class TestSettingsWorkflow:
    """Converted from scripts/test_settings_workflow.py"""

    def test_preset_then_manual_modification(self, user_db):
        """Manual modifications after preset should be respected"""
        # Step 1: Apply Conservative preset
        user_db.set_setting("portfolio_stock_allocation", "0.80")
        user_db.set_setting("portfolio_cash_reserve", "0.20")
        user_db.set_setting("portfolio_max_stock_positions", "2")
        user_db.set_setting("risk_per_stock_trade", "15")

        # Step 2: Manually modify allocation
        user_db.set_setting("portfolio_stock_allocation", "0.90")
        user_db.set_setting("portfolio_cash_reserve", "0.10")

        # Step 3: Reload and verify
        assert user_db.get_setting("portfolio_stock_allocation") == "0.90"
        assert user_db.get_setting("portfolio_cash_reserve") == "0.10"
        # Unchanged settings should persist
        assert user_db.get_setting("portfolio_max_stock_positions") == "2"
        assert user_db.get_setting("risk_per_stock_trade") == "15"

    def test_capital_allocation_calculation(self, user_db):
        """Capital allocation should use persisted settings"""
        user_db.set_setting("portfolio_total_capital", "10000")
        user_db.set_setting("portfolio_stock_allocation", "0.90")

        total = float(user_db.get_setting("portfolio_total_capital"))
        alloc = float(user_db.get_setting("portfolio_stock_allocation"))

        stock_capital = total * alloc
        assert abs(stock_capital - 9000.0) < 0.01
