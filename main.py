"""Main entry point for the Trading Workstation"""
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import streamlit.web.cli as stcli
from dss.utils.logger import logger


def run_streamlit():
    """Run Streamlit dashboard"""
    logger.info("Starting Streamlit dashboard...")
    sys.argv = ["streamlit", "run", "dss/ui/dashboard.py"]
    stcli.main()


def run_backtest(args):
    """
    Run historical backtest using PortfolioManager (same system as dashboard).
    
    Uses the unified multi-strategy system:
    - Regime Detection (ADX, BB squeeze)
    - Strategy Selection (Momentum/Mean Reversion/Breakout based on regime)
    - Position Sizing (fixed risk per trade)
    """
    import subprocess
    import sys
    
    years = getattr(args, "years", 3)
    initial_capital = getattr(args, "capital", 10000.0)
    slots = getattr(args, "slots", 3)
    
    print("\n" + "=" * 80)
    print("PORTFOLIO BACKTEST - MULTI-STRATEGY + REGIME DETECTION")
    print("=" * 80)
    print(f"\nUsing unified PortfolioManager (same as dashboard)")
    print(f"Period: {years} years")
    print(f"Initial Capital: €{initial_capital:,.2f}")
    print(f"Signal Generation: Every trading day (Tue-Fri)")
    print("\n")
    
    # Run the unified backtest script
    # NOTE: backtest_portfolio.py simulates daily signal generation (no step_days parameter)
    result = subprocess.run([
        sys.executable,
        "scripts/backtest_portfolio.py",
        f"--years={years}",
        f"--capital={initial_capital}",
        f"--slots={slots}"
    ], cwd=str(Path(__file__).parent))
    
    return


def run_backtest_legacy(args):
    """
    Run legacy backtest using SignalGenerator (scoring system).
    DEPRECATED: Use run_backtest() instead for consistency with dashboard.
    """
    from dss.backtesting.historical_validator import HistoricalValidator

    print("\n⚠️ WARNING: Using legacy backtest (SignalGenerator scoring system)")
    print("   For consistency with dashboard, use: python scripts/backtest_portfolio.py\n")

    validator = HistoricalValidator()
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        years = getattr(args, "years", 3)
        start_date = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        min_score = getattr(args, "min_score", 6)
        initial_capital = getattr(args, "capital", 1500.0)
        step_days = getattr(args, "step_days", 7)

        logger.info(
            f"Running backtest from {start_date} to {end_date} "
            f"(min_score={min_score}, step_days={step_days})"
        )
        print("Backtest may take several minutes (progress logged every ~10%). Use --step-days 1 for daily signals (slower).\n")

        results = validator.run_historical_simulation(
            start_date=start_date,
            end_date=end_date,
            min_score=min_score,
            initial_capital=initial_capital,
            step_days=step_days,
        )

        metrics = results.get("metrics", {})
        if metrics.get("error"):
            print(f"\nBacktest: {metrics['error']}")
            return

        print("\n" + "=" * 60)
        print("LEGACY BACKTEST RESULTS (Scoring System)")
        print("=" * 60)
        print(f"\nPeriod: {start_date} to {end_date}")
        print(f"Initial capital: €{initial_capital:,.2f}")
        print(f"Final capital: €{results['final_capital']:,.2f}")
        print(f"Total return: {results['total_return_pct']:.2f}%")

        print(f"\n--- Performance ---")
        print(f"Total trades: {metrics.get('total_trades', 0)}")
        print(f"Win rate: {metrics.get('win_rate', 0)}%")
        print(f"Profit factor: {metrics.get('profit_factor', 0)}")
        print(f"Avg R-multiple: {metrics.get('avg_r_multiple', 0)}")
        print(f"Sharpe ratio: {metrics.get('sharpe_ratio', 0)}")
        print(f"Max drawdown: €{metrics.get('max_drawdown', 0):.2f} ({metrics.get('max_drawdown_pct', 0):.2f}%)")
        print(f"Best trade: €{metrics.get('best_trade', 0):.2f}")
        print(f"Worst trade: €{metrics.get('worst_trade', 0):.2f}")
        print(f"Max consecutive wins: {metrics.get('max_consecutive_wins', 0)}")
        print(f"Max consecutive losses: {metrics.get('max_consecutive_losses', 0)}")

        out_file = f"backtest_legacy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(
                {k: v for k, v in results.items() if k != "trades" and k != "equity_curve"},
                f,
                indent=2,
            )
        print(f"\nMetrics saved to: {out_file}")
    finally:
        validator.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Algorithmic Trading Workstation (DSS)")
    parser.add_argument(
        "mode",
        choices=["ui", "desktop", "update", "signals", "monitor", "backtest", "backtest-legacy", "walkforward", "stress", "paper"],
        help="Mode: ui, desktop, update, signals, monitor, backtest (PortfolioManager), backtest-legacy (SignalGenerator), walkforward, stress, paper",
    )
    parser.add_argument("--force-full", action="store_true", help="Force full historical download")
    parser.add_argument("--min-score", type=int, default=6, help="Backtest: minimum signal score")
    parser.add_argument("--years", type=int, default=3, help="Backtest: number of years")
    parser.add_argument("--capital", type=float, default=1500.0, help="Backtest: initial capital (EUR)")
    parser.add_argument("--slots", type=int, default=3, help="Backtest: max concurrent positions (default: 3)")
    
    # Paper trading args
    parser.add_argument("--paper-action", choices=["start", "check", "summary", "export"], 
                       help="Paper trading action: start, check, summary, export")

    args = parser.parse_args()

    if args.mode == "ui":
        run_streamlit()
    elif args.mode == "desktop":
        from dss.ui.desktop_app import main as desktop_main
        desktop_main()
    elif args.mode == "update":
        from dss.ingestion.update_data import DataUpdater
        updater = DataUpdater()
        try:
            if args.force_full:
                print("🔄 FORCING FULL DOWNLOAD - This will download 5 years of data for all symbols")
                print("⏱️ Estimated time: ~30 seconds (Starter plan)")
                asyncio.run(updater.update_all(force_full=True))
            else:
                asyncio.run(updater.update_all())
        finally:
            asyncio.run(updater.close())
    elif args.mode == "signals":
        # Use PortfolioManager (unified system) instead of deprecated SignalGenerator
        # Per Code Review Issue #2: Unify signal systems
        from dss.core.portfolio_manager import PortfolioManager
        
        print("\n" + "=" * 60)
        print("SIGNAL GENERATION (Multi-Strategy + Regime Detection)")
        print("=" * 60)
        
        portfolio_mgr = PortfolioManager()
        try:
            signals = portfolio_mgr.generate_portfolio_signals()
            
            # Display regime info
            regime = signals.get('regime', {})
            print(f"\n📊 Market Regime: {regime.get('regime', 'unknown').upper()}")
            print(f"   ADX: {regime.get('adx', 0):.1f}, Trend: {regime.get('trend_direction', 'unknown')}")
            
            # Display stock signals
            stock_signals = signals.get('stock_signals', [])
            strategy_name = signals.get('stock_strategy_name', 'unknown')
            print(f"\n📈 Stock Signals ({len(stock_signals)}) - Strategy: {strategy_name}")
            
            for sig in stock_signals[:5]:
                print(f"   {sig['symbol']}: Entry ${sig['entry_price']:.2f}, Stop ${sig['stop_loss']:.2f}, Target ${sig.get('target_price', 0):.2f}")
            
            print(f"\n✅ Total: {len(stock_signals)} actionable signals")
            
        finally:
            portfolio_mgr.close()
    elif args.mode == "monitor":
        from dss.intelligence.price_monitor import PriceMonitor
        monitor = PriceMonitor()
        try:
            print("🔔 Starting price monitoring...")
            print("Press Ctrl+C to stop")
            asyncio.run(monitor.run_continuous_monitoring())
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
        finally:
            monitor.close()
    elif args.mode == "backtest":
        run_backtest(args)
    elif args.mode == "backtest-legacy":
        run_backtest_legacy(args)
    elif args.mode == "walkforward":
        run_walkforward(args)
    elif args.mode == "stress":
        run_stress_test(args)
    elif args.mode == "paper":
        run_paper_trading(args)


def run_walkforward(args):
    """Run walk-forward analysis (robust validation)"""
    from dss.backtesting.walk_forward import WalkForwardAnalyzer
    
    analyzer = WalkForwardAnalyzer()
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        years = getattr(args, "years", 3)
        start_date = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        initial_capital = getattr(args, "capital", 1500.0)
        
        print("\n" + "=" * 80)
        print("WALK-FORWARD ANALYSIS")
        print("=" * 80)
        print("\nOBIETTIVO: Validazione robusta per evitare overfitting")
        print(f"Periodo: {start_date} to {end_date}")
        print("\nQuesta analisi può richiedere 5-10 minuti...")
        print("Progress logged durante l'esecuzione.\n")
        
        results = analyzer.run_walk_forward_analysis(
            start_date=start_date,
            end_date=end_date,
            window_size_months=6,
            test_size_months=2,
            initial_capital=initial_capital,
            step_days=7
        )
        
        # Print results
        print("\n" + "=" * 80)
        print("WALK-FORWARD RESULTS")
        print("=" * 80)
        
        agg = results["aggregate_metrics"]
        rob = results["robustness_analysis"]
        
        print(f"\n📊 OUT-OF-SAMPLE PERFORMANCE:")
        print(f"   Total Trades: {agg['total_trades']}")
        print(f"   Win Rate: {agg['win_rate']}%")
        print(f"   Profit Factor: {agg['profit_factor']}")
        print(f"   Sharpe Ratio: {agg['sharpe_ratio']}")
        print(f"   Total Return: {agg['total_return_pct']}%")
        print(f"   Max Drawdown: {agg['max_drawdown_pct']}%")
        
        print(f"\n🛡️ ROBUSTNESS:")
        print(f"   Windows Tested: {rob['total_windows']}")
        print(f"   Profitable Windows: {rob['profitable_windows']} ({rob['profitability_ratio_pct']}%)")
        print(f"   Robustness Grade: {rob['robustness_grade']}")
        
        print(results["interpretation"])
        
        # Save results
        out_file = f"walkforward_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            # Remove non-serializable objects
            save_results = {k: v for k, v in results.items() if k not in ["windows"]}
            json.dump(save_results, f, indent=2, default=str)
        print(f"\n💾 Full results saved to: {out_file}")
        
    finally:
        analyzer.close()


def run_stress_test(args):
    """Run stress testing (crash scenarios)"""
    from dss.backtesting.stress_testing import StressTester
    
    tester = StressTester()
    try:
        print("\n" + "=" * 80)
        print("STRESS TESTING - Market Crash Scenarios")
        print("=" * 80)
        print("\nOBIETTIVO: Valutare resilienza in condizioni estreme\n")
        
        results = tester.run_stress_tests(base_capital=args.capital)
        
        print("\n" + "=" * 80)
        print("STRESS TEST RESULTS")
        print("=" * 80)
        
        agg = results["aggregate_analysis"]
        print(f"\n📊 AGGREGATE ANALYSIS:")
        print(f"   Scenarios Tested: {agg['total_scenarios_tested']}")
        print(f"   Scenarios Survived: {agg['scenarios_survived']}")
        print(f"   Survival Ratio: {agg['survival_ratio_pct']}%")
        print(f"   Worst Case Loss: {agg['worst_case_loss_pct']}%")
        print(f"   Risk Grade: {agg['risk_grade']}")
        print(f"   Is Resilient: {'✅ YES' if agg['is_resilient'] else '❌ NO'}")
        
        print(results["interpretation"])
        
        # Black Swan simulation
        print("\n" + "=" * 80)
        print("BLACK SWAN SIMULATION")
        print("=" * 80)
        
        black_swan = tester.simulate_black_swan_event(severity="severe")
        print(black_swan["interpretation"])
        
        print(f"\n💾 Stress test results saved to stress_test_results.json")
        
    finally:
        tester.close()


def run_paper_trading(args):
    """Run paper trading mode"""
    from dss.paper_trading.paper_trader import PaperTradingEngine
    
    engine = PaperTradingEngine()
    action = args.paper_action or "summary"
    
    try:
        if action == "start":
            print("\n" + "=" * 80)
            print("STARTING PAPER TRADING MODE")
            print("=" * 80)
            
            capital = args.capital
            print(f"\n💰 Initial Capital: {capital}€")
            print("📝 This will track simulated trades in real-time")
            print("🎯 Obiettivo: Validare strategia senza rischio capitale\n")
            
            confirm = input("Start paper trading? (yes/no): ").strip().lower()
            if confirm != "yes":
                print("Cancelled.")
                return
            
            engine.start_paper_trading(initial_capital=capital)
            print("\n✅ Paper trading started!")
            print("\nNext steps:")
            print("1. python main.py paper --paper-action=check  # Check for new signals")
            print("2. python main.py paper --paper-action=summary  # View performance")
            
        elif action == "check":
            print("\n🔍 Checking positions and generating new signals...")
            
            # Check existing positions
            events = engine.check_and_update_positions()
            
            if events:
                print(f"\n📢 {len(events)} events:")
                for evt in events:
                    print(f"   {evt}")
            else:
                print("   No events (no stops/targets hit)")
            
            # Get new signals
            open_slots = 3 - len(engine.open_trades)
            if open_slots > 0:
                print(f"\n🔍 Looking for new signals ({open_slots} slots available)...")
                signals = engine.get_new_signals(min_score=args.min_score)
                
                if signals:
                    print(f"\nFound {len(signals)} signals:")
                    for sig in signals[:open_slots]:
                        print(f"\n  {sig['symbol']}: Score {sig['score']}/10")
                        print(f"    Entry: ${sig['entry_price']:.2f}, Stop: ${sig['stop_loss']:.2f}, Target: ${sig.get('target_price', 0):.2f}")
                        print(f"    Quantity: {sig['position_size']}, Risk: {sig['risk_amount']:.2f}€")
                        
                        execute = input(f"  Execute paper trade for {sig['symbol']}? (yes/no): ").strip().lower()
                        if execute == "yes":
                            engine.open_paper_trade(sig)
                else:
                    print("   No new signals found")
            else:
                print(f"\n⚠️ No open slots (max {3} positions reached)")
            
        elif action == "summary":
            print("\n" + "=" * 80)
            print("PAPER TRADING PERFORMANCE SUMMARY")
            print("=" * 80)
            
            summary = engine.get_performance_summary()
            
            if "error" in summary:
                print(f"\n{summary['error']}")
                print(f"Open positions: {summary.get('open_positions', 0)}")
                return
            
            print(f"\n📅 Running since: {summary['start_date']} ({summary['days_running']} days)")
            print(f"💰 Capital: {summary['initial_capital']:.2f}€ → {summary['current_capital']:.2f}€")
            print(f"📈 Return: {summary['total_return_pct']:+.2f}%")
            
            print(f"\n📊 TRADES:")
            print(f"   Total: {summary['total_trades']}")
            print(f"   Open: {summary['open_positions']}")
            print(f"   Winners: {summary['winning_trades']}")
            print(f"   Losers: {summary['losing_trades']}")
            print(f"   Win Rate: {summary['win_rate']}%")
            
            print(f"\n💹 METRICS:")
            print(f"   Profit Factor: {summary['profit_factor']}")
            print(f"   Avg R-multiple: {summary['avg_r_multiple']}")
            print(f"   Sharpe Ratio: {summary['sharpe_ratio']}")
            print(f"   Max Drawdown: {summary['max_drawdown_pct']:.2f}%")
            
            print(f"\n🎯 BEST/WORST:")
            print(f"   Best Trade: +{summary['best_trade']:.2f}€")
            print(f"   Worst Trade: {summary['worst_trade']:.2f}€")
            print(f"   Avg Win: +{summary['avg_win']:.2f}€")
            print(f"   Avg Loss: {summary['avg_loss']:.2f}€")
            
            # Readiness assessment
            readiness = summary.get("is_ready_for_live", {})
            if readiness:
                print(f"\n{'=' * 80}")
                print("READINESS FOR LIVE TRADING")
                print("=" * 80)
                print(f"\nReady: {'✅ YES' if readiness['ready'] else '❌ NO'}")
                print(f"Score: {readiness.get('score', 0)}/{readiness.get('max_score', 10)}")
                print(f"\nChecks:")
                for check in readiness.get("checks", []):
                    print(f"  {check}")
                print(f"\n{readiness['recommendation']}")
                
                if readiness['ready']:
                    print(f"\n💡 Suggested Live Capital: {readiness['suggested_live_capital']}€")
        
        elif action == "export":
            filename = engine.export_trades_to_csv()
            print(f"\n✅ Trades exported to: {filename}")
        
    finally:
        engine.close()


if __name__ == "__main__":
    main()
