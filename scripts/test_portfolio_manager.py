"""
Test Portfolio Manager
Testa il sistema multi-strategia con regime detection

Updated for stock-only system (no ETF support)
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dss.core.portfolio_manager import PortfolioManager


def main():
    print("=" * 80)
    print("PORTFOLIO MANAGER - MULTI-STRATEGY TEST")
    print("Stock-Only System")
    print("=" * 80)
    print("\nCapital: €10,000")
    print("Allocation:")
    print("  - 90% (€9,000) Stock Swing (Momentum/Mean Reversion/Breakout)")
    print("  - 10% (€1,000) Cash Reserve")
    print("\n" + "=" * 80 + "\n")
    
    pm = PortfolioManager()
    
    try:
        # Generate portfolio signals
        portfolio = pm.generate_portfolio_signals()
        
        # Display results
        print("\n" + "=" * 80)
        print("PORTFOLIO SIGNALS")
        print("=" * 80)
        
        # Regime
        regime = portfolio['regime']
        print(f"\nMarket Regime: {regime['regime'].upper()}")
        print(f"  ADX: {regime['adx']:.1f}")
        print(f"  Trend: {regime['trend_direction']}")
        print(f"  Confidence: {regime['confidence']:.0f}%")
        
        # Stock strategy
        stock_strategy = portfolio['stock_strategy_used']
        stock_signals = portfolio['stock_signals']
        
        print(f"\nStock Strategy Selected: {stock_strategy.upper()}")
        print(f"Stock Signals: {len(stock_signals)}")
        
        if stock_signals:
            print("\nTop Stock Signals:")
            for i, sig in enumerate(stock_signals, 1):
                print(f"\n{i}. {sig['symbol']}")
                print(f"   Strategy: {sig['strategy']}")
                print(f"   Entry: ${sig['entry_price']:.2f}")
                print(f"   Target: ${sig['target_price']:.2f}")
                print(f"   Stop: ${sig['stop_loss']:.2f}")
                print(f"   Quantity: {sig['position_size']}")
                print(f"   Risk: €{sig['risk_amount']:.2f}")
        else:
            print("  (No stock signals generated)")
        
        # Capital allocation
        alloc = portfolio['capital_allocation']
        print(f"\n{'-' * 80}")
        print("Capital Allocation:")
        print(f"  Stock: €{alloc['stock']:,.0f}")
        print(f"  Cash: €{alloc['cash']:,.0f}")
        print(f"  Total: €{alloc['total']:,.0f}")
        
        print("\n" + "=" * 80)
        print("NEXT STEPS")
        print("=" * 80)
        print("\n1. Review signals and confirm setup quality")
        print("2. Execute trades on Trade Republic:")
        print("   - Buy stock positions (limit orders preferred)")
        print("   - Set STOP LOSS immediately after entry")
        print("   - Set price alerts for targets")
        print("3. Monitor regime changes (every 3-7 days)")
        print("4. Update trailing stops as positions become profitable")
        
        print("\nPer backtest completo:")
        print("  python scripts/backtest_portfolio.py --years=3")
        
    finally:
        pm.close()


if __name__ == "__main__":
    main()
