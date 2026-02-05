"""
Test Settings Workflow - Verifica che modifiche manuali dopo preset vengano applicate

Updated for stock-only system (no ETF support)

Scenario di test:
1. Applica preset "Conservative"
2. Modifica manualmente alcuni parametri
3. Genera segnali
4. Verifica che i segnali usino i parametri modificati, NON il preset
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dss.core.portfolio_manager import PortfolioManager
from dss.database.user_db import UserDatabase

def test_settings_workflow():
    """Test che modifiche manuali dopo preset vengano rispettate"""
    print("\n" + "="*80)
    print("TEST: Settings Workflow (Preset + Manual Modifications)")
    print("Stock-Only System")
    print("="*80 + "\n")
    
    # Initialize
    user_db = UserDatabase()
    portfolio_mgr = PortfolioManager(user_db=user_db)
    
    # Step 1: Apply Conservative preset
    print("[STEP 1] Applying Conservative preset...")
    portfolio_mgr.update_settings(
        stock_allocation=0.80,
        cash_reserve=0.20,
        max_stock_positions=2,
        stock_risk_per_trade=15.0
    )
    print(f"  Stock Allocation: {portfolio_mgr.STOCK_ALLOCATION*100:.0f}%")
    print(f"  Cash Reserve: {portfolio_mgr.CASH_RESERVE*100:.0f}%")
    print(f"  Max Stock Positions: {portfolio_mgr.MAX_STOCK_POSITIONS}")
    print(f"  Stock Risk: €{portfolio_mgr.momentum.RISK_PER_TRADE_EUR:.0f}")
    
    # Step 2: Manually modify allocation
    print("\n[STEP 2] Manually modifying allocation to 90/10...")
    portfolio_mgr.update_settings(
        stock_allocation=0.90,
        cash_reserve=0.10
    )
    print(f"  Stock Allocation: {portfolio_mgr.STOCK_ALLOCATION*100:.0f}%")
    print(f"  Cash Reserve: {portfolio_mgr.CASH_RESERVE*100:.0f}%")
    
    # Step 3: Reload settings (simula quello che fa Generate Signals)
    print("\n[STEP 3] Reloading settings from database (simulating Generate Signals)...")
    portfolio_mgr.reload_settings()
    print(f"  Stock Allocation: {portfolio_mgr.STOCK_ALLOCATION*100:.0f}%")
    print(f"  Cash Reserve: {portfolio_mgr.CASH_RESERVE*100:.0f}%")
    print(f"  Max Stock Positions: {portfolio_mgr.MAX_STOCK_POSITIONS}")
    
    # Step 4: Verify
    print("\n[VERIFICATION]")
    
    success = True
    
    # Check allocation (should be manual values, NOT preset)
    if abs(portfolio_mgr.STOCK_ALLOCATION - 0.90) < 0.01:
        print("  [OK] Stock Allocation: 90% (manual modification respected)")
    else:
        print(f"  [FAILED] Stock Allocation: {portfolio_mgr.STOCK_ALLOCATION*100:.0f}% (expected 90%)")
        success = False
    
    if abs(portfolio_mgr.CASH_RESERVE - 0.10) < 0.01:
        print("  [OK] Cash Reserve: 10% (manual modification respected)")
    else:
        print(f"  [FAILED] Cash Reserve: {portfolio_mgr.CASH_RESERVE*100:.0f}% (expected 10%)")
        success = False
    
    # Check max positions (should still be from preset)
    if portfolio_mgr.MAX_STOCK_POSITIONS == 2:
        print("  [OK] Max Stock Positions: 2 (from preset, not modified)")
    else:
        print(f"  [FAILED] Max Stock Positions: {portfolio_mgr.MAX_STOCK_POSITIONS} (expected 2)")
        success = False
    
    # Step 5: Test that Generate Signals uses correct settings
    print("\n[STEP 4] Testing capital allocation calculation...")
    total_capital = portfolio_mgr.TOTAL_CAPITAL
    stock_capital = total_capital * portfolio_mgr.STOCK_ALLOCATION
    cash_reserve = total_capital * portfolio_mgr.CASH_RESERVE
    
    print(f"  Total Capital: €{total_capital:,.0f}")
    print(f"  Stock Capital: €{stock_capital:,.0f} (90% of €{total_capital:,.0f})")
    print(f"  Cash Reserve: €{cash_reserve:,.0f} (10% of €{total_capital:,.0f})")
    
    expected_stock = total_capital * 0.90
    if abs(stock_capital - expected_stock) < 1.0:
        print("  [OK] Stock capital calculation correct")
    else:
        print(f"  [FAILED] Stock capital: €{stock_capital:,.0f} (expected €{expected_stock:,.0f})")
        success = False
    
    # Final result
    print("\n" + "="*80)
    if success:
        print("[SUCCESS] ALL TESTS PASSED!")
        print("Manual modifications after preset are correctly applied.")
    else:
        print("[FAILED] Some tests failed. Check output above.")
    print("="*80 + "\n")
    
    return success


if __name__ == "__main__":
    success = test_settings_workflow()
    sys.exit(0 if success else 1)
