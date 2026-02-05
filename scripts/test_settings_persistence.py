"""
Test script to verify settings persistence
Verifica che le impostazioni vengano salvate e caricate correttamente dal database

Updated for stock-only system (no ETF support)
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dss.core.portfolio_manager import PortfolioManager
from dss.database.user_db import UserDatabase

def test_settings_persistence():
    """Test that settings are saved and loaded correctly"""
    
    print("="*80)
    print("TEST SETTINGS PERSISTENCE (Stock-Only System)")
    print("="*80)
    print()
    
    # Initialize
    user_db = UserDatabase()
    
    # Test 1: Save Conservative preset
    print("TEST 1: Saving Conservative Preset")
    print("-" * 80)
    
    user_db.set_setting("portfolio_total_capital", "10000")
    user_db.set_setting("portfolio_stock_allocation", "0.80")
    user_db.set_setting("portfolio_cash_reserve", "0.20")
    user_db.set_setting("portfolio_max_stock_positions", "2")
    user_db.set_setting("risk_per_stock_trade", "15")
    
    print("[OK] Settings saved to database")
    print()
    
    # Test 2: Load settings via Portfolio Manager
    print("TEST 2: Loading Settings via Portfolio Manager")
    print("-" * 80)
    
    pm = PortfolioManager()
    
    print(f"Capital: €{pm.TOTAL_CAPITAL:,.0f}")
    print(f"Stock Allocation: {pm.STOCK_ALLOCATION*100:.0f}%")
    print(f"Cash Reserve: {pm.CASH_RESERVE*100:.0f}%")
    print(f"Max Stock Positions: {pm.MAX_STOCK_POSITIONS}")
    
    # Verify
    assert pm.TOTAL_CAPITAL == 10000.0, "Capital mismatch"
    assert pm.STOCK_ALLOCATION == 0.80, "Stock allocation mismatch"
    assert pm.CASH_RESERVE == 0.20, "Cash reserve mismatch"
    assert pm.MAX_STOCK_POSITIONS == 2, "Max stock positions mismatch"
    
    # Check risk settings
    assert pm.momentum.RISK_PER_TRADE_EUR == 15.0, "Stock risk mismatch"
    
    print()
    print("[OK] All settings loaded correctly!")
    print()
    
    # Test 3: Update via Portfolio Manager
    print("TEST 3: Updating Settings via Portfolio Manager")
    print("-" * 80)
    
    pm.update_settings(
        total_capital=5000.0,
        stock_allocation=0.90,
        cash_reserve=0.10,
        max_stock_positions=3
    )
    
    print(f"Updated Capital: €{pm.TOTAL_CAPITAL:,.0f}")
    print(f"Updated Stock: {pm.STOCK_ALLOCATION*100:.0f}%")
    print(f"Updated Cash: {pm.CASH_RESERVE*100:.0f}%")
    print()
    print("[OK] Settings updated")
    print()
    
    # Test 4: Reload to verify persistence
    print("TEST 4: Reloading to Verify Persistence")
    print("-" * 80)
    
    pm2 = PortfolioManager()
    
    print(f"Reloaded Capital: €{pm2.TOTAL_CAPITAL:,.0f}")
    print(f"Reloaded Stock: {pm2.STOCK_ALLOCATION*100:.0f}%")
    print(f"Reloaded Cash: {pm2.CASH_RESERVE*100:.0f}%")
    
    assert pm2.TOTAL_CAPITAL == 5000.0, "Persistence failed: Capital"
    assert pm2.STOCK_ALLOCATION == 0.90, "Persistence failed: Stock allocation"
    assert pm2.CASH_RESERVE == 0.10, "Persistence failed: Cash reserve"
    
    print()
    print("[OK] Settings persisted correctly!")
    print()
    
    # Cleanup: Reset to defaults
    print("CLEANUP: Resetting to Defaults")
    print("-" * 80)
    
    pm2.update_settings(
        total_capital=10000.0,
        stock_allocation=0.90,
        cash_reserve=0.10,
        max_stock_positions=5
    )
    user_db.set_setting("risk_per_stock_trade", "20")
    
    print("[OK] Defaults restored")
    print()
    
    # Final verification
    pm3 = PortfolioManager()
    print("Final State:")
    print(f"Capital: €{pm3.TOTAL_CAPITAL:,.0f}")
    print(f"Allocation: {pm3.STOCK_ALLOCATION*100:.0f}% Stock / {pm3.CASH_RESERVE*100:.0f}% Cash")
    print(f"Max Positions: {pm3.MAX_STOCK_POSITIONS} stock")
    print()
    
    print("="*80)
    print("[SUCCESS] ALL TESTS PASSED!")
    print("="*80)
    print()
    print("Settings persistence is working correctly!")
    print("Presets should work in the dashboard.")


if __name__ == "__main__":
    try:
        test_settings_persistence()
    except AssertionError as e:
        print()
        print("="*80)
        print("[FAILED] TEST FAILED!")
        print("="*80)
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print()
        print("="*80)
        print("[ERROR] UNEXPECTED ERROR!")
        print("="*80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
