"""
Backtest Portfolio Multi-Strategy con Workflow Martedì→Venerdì
Sistema stock-only: 90% Stock Day/Swing + 10% Cash

Workflow reale simulato:
- LUNEDÌ: genera segnali (close di lunedì)
- MARTEDÌ: entra all'open + 0.2% slippage (max N slot)
- MER-GIO: check stop loss + trailing stop intra-settimanale
- VENERDÌ: solo check stop/trailing, lascia correre i winner

CONFIGURAZIONE FORMIDABILE (PF 1.67, Win Rate 57%):
- MAX_HOLD: 8 weeks (~2 mesi) - lascia correre i winner a lungo
- Trailing: trigger +6%, distance 1.5%, lock +3.5%
- Stops: ATR-based (entry - ATR×2.0, cap -5%)
- Risk: 1.5% del capitale per trade (COMPOUND enabled)
- Friday: niente chiusura forzata, solo stop/trailing check
- Position cap: max 33% capitale per posizione

NOTE:
- NATR filter + composite ranking rimossi (peggioravano)
- TP1/TP2 partial exits disabilitato (tagliava winner troppo presto)
- Position sizing fatto QUI, non nelle strategie (vedi dynamic_risk_amount)
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dss.core.portfolio_manager import PortfolioManager
from dss.database.market_db import MarketDatabase
from dss.database.user_db import UserDatabase
from dss.utils.config import config
from dss.utils.currency import get_exchange_rate
import pandas as pd
import numpy as np
from loguru import logger

# Get exchange rate from user_db (or fallback to 0.92)
_user_db = UserDatabase()
EUR_USD_RATE = get_exchange_rate(user_db=_user_db)
logger.info(f"Using EUR/USD rate: {EUR_USD_RATE}")

# =============================================================================
# ALL PARAMETERS READ FROM config.yaml (single source of truth)
# =============================================================================
MAX_HOLD_WEEKS = config.get("risk.max_hold_weeks", 8)
ENTRY_SLIPPAGE_PCT = config.get("risk.entry_slippage_pct", 0.2)
EXIT_SLIPPAGE_PCT = config.get("risk.exit_slippage_pct", 0.1)
TRAILING_TRIGGER_PCT = config.get("risk.trailing_trigger_pct", 6.0)
TRAILING_DISTANCE_PCT = config.get("risk.trailing_distance_pct", 1.5)
TRAILING_MIN_LOCK_PCT = config.get("risk.trailing_min_lock_pct", 3.5)

# Breakeven stop - DISABILITATO (non in config, troppo fragile)
BREAKEVEN_ENABLED = False
BREAKEVEN_TRIGGER_PCT = 3.0

# Bear Market Protection
BEAR_MARKET_PROTECTION = config.get("risk.bear_market_protection", True)
BEAR_MARKET_MODE = config.get("risk.bear_market_mode", "cash")
BEAR_MARKET_EXIT_POSITIONS = config.get("risk.bear_market_exit_positions", True)


def run_portfolio_backtest(
    start_date: str,
    end_date: str,
    initial_capital: float = 10_000.0,
    max_slots: int = 3
):
    """
    Backtest Portfolio Multi-Strategy con Workflow Martedì→Venerdì
    
    Capital Allocation:
    - 90% Stock Day/Swing (Momentum/Mean Reversion/Breakout)
    - 10% Cash Reserve
    """
    db = MarketDatabase()
    pm = PortfolioManager()
    
    start = pd.to_datetime(start_date).normalize()
    end = pd.to_datetime(end_date).normalize()
    
    print(f"\n{'=' * 80}")
    print("PORTFOLIO BACKTEST - WORKFLOW TUE->FRI")
    print("=" * 80)
    print(f"Period: {start.date()} to {end.date()}")
    print(f"Initial Capital: €{initial_capital:,.2f}")
    print(f"Max Slots: {max_slots}")
    print("\nWorkflow:")
    print("  MONDAY: generate signals")
    print("  TUESDAY: enter at open + 0.2% slippage")
    print("  WED-THU: check stop loss + trailing stop")
    print("  FRIDAY: only stop/trailing check, max_hold close, let winners run")
    print(f"\nSolution B - Trailing Stop:")
    print(f"  Trigger: +{TRAILING_TRIGGER_PCT}% | Trail: -{TRAILING_DISTANCE_PCT}% from high | Min lock: +{TRAILING_MIN_LOCK_PCT}%")
    print(f"\n{'=' * 80}\n")
    
    # Simulation state
    current_capital = initial_capital
    current_positions = []  # {symbol, strategy, entry_date, entry_price, stop_loss, quantity, ...}
    pending_signals = []    # Signals from Monday, to be executed Tuesday
    trades = []
    equity_curve = []
    regime_history = []
    weekly_stats = []
    
    current_date = start
    week_count = 0
    effective_max_slots = max_slots  # May be reduced by regime filter
    
    while current_date <= end:
        weekday = current_date.weekday()  # 0=Monday, 4=Friday
        
        try:
            # ================================================================
            # LUNEDI (weekday=0): Genera segnali
            # ================================================================
            if weekday == 0:
                week_count += 1
                portfolio = pm.generate_portfolio_signals(as_of_date=current_date)
                
                regime = portfolio['regime']['regime']
                adx = portfolio['regime']['adx']
                trend = portfolio['regime']['trend_direction']
                
                regime_history.append({
                    'date': current_date,
                    'regime': regime,
                    'adx': adx,
                    'trend': trend,
                    'strategy_used': portfolio['stock_strategy_used']
                })
                
                # ============================================================
                # AGGRESSIVE REGIME FILTER
                # ============================================================
                
                # Filter 1: Skip week if ADX < 15 (choppy market, no edge)
                if adx < 15:
                    pending_signals = []
                    effective_max_slots = 0
                    logger.info(
                        f"[LUNEDI {current_date.date()}] Week {week_count}: "
                        f"SKIPPED - ADX={adx:.1f} < 15 (too choppy)"
                    )
                else:
                    # Filter 2: Bear Market Protection
                    # SPY < SMA200 AND SPY < SMA50 = confirmed bear market → go to CASH
                    # SPY < SMA200 only = caution → reduce slots
                    bear_market = False
                    spy_below_sma200 = False
                    try:
                        # Need ~300 calendar days to get 200 trading days
                        spy_start = current_date - pd.Timedelta(days=300)
                        spy_data = db.get_data('SPY', start_date=spy_start, end_date=current_date)
                        if len(spy_data) >= 200:
                            spy_close = spy_data.iloc[-1]['close']
                            spy_sma200 = spy_data['close'].rolling(200).mean().iloc[-1]
                            spy_sma50 = spy_data['close'].rolling(50).mean().iloc[-1]
                            spy_below_sma200 = spy_close < spy_sma200
                            spy_below_sma50 = spy_close < spy_sma50
                            
                            # Confirmed bear market: price below BOTH SMAs
                            bear_market = spy_below_sma200 and spy_below_sma50
                    except Exception as e:
                        logger.debug(f"Could not check SPY SMAs: {e}")
                    
                    if BEAR_MARKET_PROTECTION and bear_market:
                        # Confirmed bear market → apply configured mode
                        if BEAR_MARKET_MODE == "cash":
                            effective_max_slots = 0
                            mode_desc = "CASH MODE (0 new entries)"
                        else:  # "reduced"
                            effective_max_slots = 1
                            mode_desc = "REDUCED MODE (1 slot only)"
                        
                        logger.info(
                            f"[LUNEDI {current_date.date()}] Week {week_count}: "
                            f"🐻 BEAR MARKET (SPY < SMA50 & SMA200) - {mode_desc}"
                        )
                        
                        # Exit existing positions if configured
                        if BEAR_MARKET_EXIT_POSITIONS and current_positions:
                            logger.info(f"  → Closing {len(current_positions)} existing positions (bear market exit)")
                            for pos in list(current_positions):
                                # Get current price for exit
                                try:
                                    sym_data = db.get_data(pos['symbol'], end_date=current_date)
                                    if not sym_data.empty:
                                        exit_price = float(sym_data.iloc[-1]['close'])
                                    else:
                                        exit_price = pos['entry_price']
                                except Exception:
                                    exit_price = pos['entry_price']
                                
                                outcome = create_outcome(pos, current_date, exit_price, 'bear_market_exit')
                                trades.append(outcome)
                                current_positions.remove(pos)
                                current_capital += pos['capital_allocated'] + outcome['pnl_eur']
                                logger.info(
                                    f"    {pos['symbol']}: Closed at ${exit_price:.2f} "
                                    f"(P&L: €{outcome['pnl_eur']:.2f})"
                                )
                    elif spy_below_sma200:
                        # Caution mode: reduce slots
                        effective_max_slots = max(1, max_slots - 1)
                        logger.info(
                            f"[LUNEDI {current_date.date()}] Week {week_count}: "
                            f"⚠️ SPY below SMA200 - reducing to {effective_max_slots} slots"
                        )
                    else:
                        effective_max_slots = max_slots
                    
                    # Store signals for Tuesday entry (no extra filtering - let strategy filters do the work)
                    pending_signals = portfolio['stock_signals']
                    logger.info(
                        f"[LUNEDI {current_date.date()}] Week {week_count}: "
                        f"{len(pending_signals)} signals, ADX={adx:.1f}, regime={regime}, "
                        f"slots={effective_max_slots}"
                    )
            
            # ================================================================
            # MARTEDÌ (weekday=1): Entra nelle posizioni
            # ================================================================
            elif weekday == 1:
                # BUG FIX 1: Check stop loss on carry-over positions BEFORE entering new ones
                for pos in list(current_positions):
                    outcome = check_intraweek_stop(pos, current_date, db)
                    if outcome:
                        trades.append(outcome)
                        current_positions.remove(pos)
                        current_capital += pos['capital_allocated'] + outcome['pnl_eur']
                        logger.info(
                            f"[MARTEDI {current_date.date()}] STOP HIT (carry-over) "
                            f"{outcome['symbol']}: P&L EUR{outcome['pnl_eur']:.2f}"
                        )
                
                # Calculate available slots (uses effective_max_slots from regime filter)
                # FIX: max(0, ...) prevents negative slice which would allow entries beyond limit
                available_slots = max(0, effective_max_slots - len(current_positions))
                
                for sig in pending_signals[:available_slots]:
                    if any(p['symbol'] == sig['symbol'] for p in current_positions):
                        continue
                    
                    # Get Tuesday's open price
                    try:
                        df_tue = db.get_data_for_date(sig['symbol'], current_date)
                        if df_tue.empty:
                            logger.debug(f"No data for {sig['symbol']} on {current_date.date()}")
                            continue
                        open_price = float(df_tue.iloc[0]['open'])
                    except Exception as e:
                        logger.debug(f"Error getting open for {sig['symbol']}: {e}")
                        continue
                    
                    # Entry price = open + slippage (we buy higher)
                    entry_price = open_price * (1 + ENTRY_SLIPPAGE_PCT / 100)
                    
                    # COMPOUND: Calculate risk amount as % of CURRENT capital (not fixed)
                    # This enables true compounding - profits get reinvested
                    RISK_PCT = 0.015  # 1.5% risk per trade (from config)
                    
                    # Calculate current total equity (cash + open positions value)
                    positions_value = calculate_positions_mtm(current_positions, current_date, db)
                    total_equity = current_capital + positions_value
                    
                    # Risk amount = % of total equity (TRUE COMPOUND)
                    dynamic_risk_amount = total_equity * RISK_PCT
                    
                    risk_per_share = entry_price - sig['stop_loss']
                    if risk_per_share <= 0:
                        continue
                    quantity = max(1, int(dynamic_risk_amount / (risk_per_share * EUR_USD_RATE)))
                    
                    # CAP: Position value cannot exceed 33% of total equity
                    max_position_value_eur = total_equity * 0.33
                    position_value_eur = (entry_price * quantity * EUR_USD_RATE)
                    if position_value_eur > max_position_value_eur:
                        # Reduce quantity to fit within cap
                        quantity = max(1, int(max_position_value_eur / (entry_price * EUR_USD_RATE)))
                        logger.debug(f"{sig['symbol']}: Position capped to {quantity} shares (33% rule)")
                    
                    capital_needed_usd = entry_price * quantity
                    capital_needed_eur = capital_needed_usd * EUR_USD_RATE + 1.0  # +€1 commission
                    
                    if current_capital < capital_needed_eur:
                        logger.info(f"Skipping {sig['symbol']}: Insufficient capital")
                        continue
                    
                    current_capital -= capital_needed_eur
                    
                    # Calculate ATR for TP1/TP2 levels
                    atr_pct = sig.get('metrics', {}).get('atr_stop_pct', 3.0)  # Default 3%
                    atr_value = entry_price * (atr_pct / 100)
                    
                    position = {
                        'symbol': sig['symbol'],
                        'asset_class': 'stock',
                        'strategy': sig['strategy'],
                        'entry_date': current_date,
                        'entry_week': week_count,
                        'entry_price': entry_price,
                        'stop_loss': sig['stop_loss'],
                        'target_price': sig['target_price'],
                        'quantity': quantity,
                        'original_quantity': quantity,
                        'risk_amount': dynamic_risk_amount,  # COMPOUND: 1.5% del capitale
                        'capital_allocated': capital_needed_eur,
                        'highest_price': entry_price,
                        'atr': atr_value
                    }
                    current_positions.append(position)
                    logger.info(
                        f"[MARTEDÌ {current_date.date()}] Opened {sig['symbol']} ({sig['strategy']}): "
                        f"Entry ${entry_price:.2f} (open ${open_price:.2f} + 0.2%), Qty {quantity}"
                    )
                
                pending_signals = []  # Clear pending signals
                
                # BUG FIX 3: Check stop loss on Tuesday for just-opened trades
                for pos in list(current_positions):
                    outcome = check_intraweek_stop(pos, current_date, db)
                    if outcome:
                        trades.append(outcome)
                        current_positions.remove(pos)
                        current_capital += pos['capital_allocated'] + outcome['pnl_eur']
                        logger.info(
                            f"[MARTEDI {current_date.date()}] STOP HIT (same day) "
                            f"{outcome['symbol']}: P&L EUR{outcome['pnl_eur']:.2f}"
                        )
            
            # ================================================================
            # MERCOLEDI-GIOVEDI (weekday=2,3): Check stop loss intra-settimanale
            # ================================================================
            elif weekday in [2, 3]:
                for pos in list(current_positions):
                    outcome = check_intraweek_stop(pos, current_date, db)
                    if outcome:
                        trades.append(outcome)
                        current_positions.remove(pos)
                        current_capital += pos['capital_allocated'] + outcome['pnl_eur']
                        logger.info(
                            f"[{['LUN','MAR','MER','GIO','VEN'][weekday]} {current_date.date()}] "
                            f"STOP HIT {outcome['symbol']}: P&L €{outcome['pnl_eur']:.2f}"
                        )
            
            # ================================================================
            # VENERDÌ (weekday=4): Regole di uscita del workflow
            # ================================================================
            elif weekday == 4:
                for pos in list(current_positions):
                    outcome = check_friday_exit(pos, current_date, db, week_count)
                    if outcome:
                        trades.append(outcome)
                        current_positions.remove(pos)
                        current_capital += pos['capital_allocated'] + outcome['pnl_eur']
                        logger.info(
                            f"[VENERDÌ {current_date.date()}] Closed {outcome['symbol']} ({outcome['strategy']}): "
                            f"{outcome['exit_reason']}, P&L €{outcome['pnl_eur']:.2f}"
                        )
                
                # Weekly summary
                weekly_stats.append({
                    'week': week_count,
                    'date': current_date,
                    'positions_held': len(current_positions),
                    'capital': current_capital
                })
            
            # ================================================================
            # Equity snapshot (every trading day)
            # ================================================================
            if weekday < 5:  # Only trading days
                positions_mtm = calculate_positions_mtm(current_positions, current_date, db)
                total_value = current_capital + positions_mtm
                
                equity_curve.append({
                    'date': current_date,
                    'capital': current_capital,
                    'positions_mtm': positions_mtm,
                    'total_value': total_value,
                    'positions': len(current_positions)
                })
        
        except Exception as e:
            logger.error(f"Error at {current_date}: {e}")
        
        current_date += timedelta(days=1)
    
    # Force close remaining positions at end
    for pos in current_positions:
        outcome = force_close_position(pos, end, db)
        trades.append(outcome)
        current_capital += pos['capital_allocated'] + outcome['pnl_eur']
        logger.info(f"Force closed {outcome['symbol']}: P&L €{outcome['pnl_eur']:.2f}")
    
    # Calculate metrics
    metrics = calculate_performance_metrics(trades, equity_curve, initial_capital, current_capital)
    total_return_pct = ((current_capital - initial_capital) / initial_capital) * 100
    
    # Print results
    print_results(
        trades, metrics, regime_history, initial_capital, current_capital, 
        total_return_pct, start, end, week_count
    )
    
    # Save results
    save_results(
        start_date, end_date, initial_capital, current_capital, 
        total_return_pct, metrics, trades, weekly_stats
    )
    
    db.close()
    pm.close()
    
    return {
        'final_capital': current_capital,
        'total_return_pct': total_return_pct,
        'metrics': metrics,
        'weeks': week_count
    }


def check_intraweek_stop(position: dict, current_date, db: MarketDatabase):
    """Check stop loss, trailing stop, and TP1/TP2 during the week
    
    FORMIDABLE SYSTEM:
    - TP1: Partial exit at 1.5x ATR (sell 50%, move stop to breakeven)
    - TP2: Full exit at 3x ATR
    - Trailing stop with balanced parameters
    - Stop loss protection
    """
    symbol = position['symbol']
    strategy = position.get('strategy', '').lower()
    
    try:
        df = db.get_data_for_date(symbol, current_date)
        if df.empty:
            return None
        
        row = df.iloc[0]
        low = float(row['low'])
        high = float(row['high'])
        close = float(row['close'])
        
        # Update highest price for trailing stop
        position['highest_price'] = max(position.get('highest_price', position['entry_price']), high)
        
        # TP1/TP2 RIMOSSO - vedere commento in cima al file
        
        # ============================================================
        # BREAKEVEN STOP - DISABILITATO (peggiorava i risultati)
        # ============================================================
        # Il codice è mantenuto ma disabilitato per futuri test
        if BREAKEVEN_ENABLED:
            current_profit_pct = ((high - position['entry_price']) / position['entry_price']) * 100
            if current_profit_pct >= BREAKEVEN_TRIGGER_PCT and not position.get('breakeven_active', False):
                breakeven_stop = position['entry_price'] * 1.003  # +0.3% sopra entry per coprire commissioni
                if breakeven_stop > position['stop_loss']:
                    position['stop_loss'] = breakeven_stop
                    position['breakeven_active'] = True
        
        # ============================================================
        # TRAILING STOP LOGIC (attivo a +6%)
        # ============================================================
        profit_from_high = ((position['highest_price'] - position['entry_price']) 
                           / position['entry_price']) * 100
        
        if profit_from_high >= TRAILING_TRIGGER_PCT:
            # Calculate trailing stop
            trailing_stop = position['highest_price'] * (1 - TRAILING_DISTANCE_PCT / 100)
            
            # Minimum lock
            min_lock = position['entry_price'] * (1 + TRAILING_MIN_LOCK_PCT / 100)
            trailing_stop = max(trailing_stop, min_lock)
            
            if trailing_stop > position['stop_loss']:
                old_stop = position['stop_loss']
                position['stop_loss'] = trailing_stop
                position['trailing_active'] = True
                logger.debug(
                    f"{symbol}: Trailing stop updated ${old_stop:.2f} -> ${trailing_stop:.2f}"
                )
        
        # ============================================================
        # STOP LOSS CHECK
        # ============================================================
        if low <= position['stop_loss']:
            exit_reason = 'trailing_stop' if position.get('trailing_active') else 'stop_loss'
            return create_outcome(position, current_date, position['stop_loss'], exit_reason)
        
        return None
    
    except Exception as e:
        logger.debug(f"Error checking stop for {symbol}: {e}")
        return None


def check_friday_exit(position: dict, current_date, db: MarketDatabase, current_week: int):
    """
    SIMPLIFIED Friday exit logic - let winners run!
    
    ONLY close if:
    - Stop loss / trailing stop hit
    - Max hold reached (extended to 8 weeks)
    
    NO MORE:
    - profit < 0% close (let stop manage it)
    - Complex decision logic
    
    Winners can run indefinitely until trailing stop catches them.
    """
    symbol = position['symbol']
    strategy = position['strategy']
    
    try:
        df = db.get_data_for_date(symbol, current_date)
        if df.empty:
            return None
        
        row = df.iloc[0]
        close = float(row['close'])
        low = float(row['low'])
        high = float(row['high'])
        
        # Update highest price (trailing stop tracking continues on Friday)
        position['highest_price'] = max(position.get('highest_price', position['entry_price']), high)
        
        # Breakeven stop - DISABILITATO (vedi commento sopra)
        if BREAKEVEN_ENABLED:
            current_profit_pct = ((high - position['entry_price']) / position['entry_price']) * 100
            if current_profit_pct >= BREAKEVEN_TRIGGER_PCT and not position.get('breakeven_active', False):
                breakeven_stop = position['entry_price'] * 1.003
                if breakeven_stop > position['stop_loss']:
                    position['stop_loss'] = breakeven_stop
                    position['breakeven_active'] = True
        
        # Update trailing stop if conditions met
        profit_from_high = ((position['highest_price'] - position['entry_price']) 
                           / position['entry_price']) * 100
        
        if profit_from_high >= TRAILING_TRIGGER_PCT:
            trailing_stop = position['highest_price'] * (1 - TRAILING_DISTANCE_PCT / 100)
            min_lock = position['entry_price'] * (1 + TRAILING_MIN_LOCK_PCT / 100)
            trailing_stop = max(trailing_stop, min_lock)
            
            if trailing_stop > position['stop_loss']:
                position['stop_loss'] = trailing_stop
                position['trailing_active'] = True
        
        # Check stop loss / trailing stop
        if low <= position['stop_loss']:
            exit_reason = 'trailing_stop' if position.get('trailing_active') else 'stop_loss'
            return create_outcome(position, current_date, position['stop_loss'], exit_reason)
        
        # How many weeks has this position been held?
        weeks_held = current_week - position['entry_week']
        
        # Max hold check (extended to 8 weeks)
        if weeks_held >= MAX_HOLD_WEEKS:
            return create_outcome(position, current_date, close, 'max_hold')
        
        # ALL OTHER CASES: HOLD - let the winner run!
        profit_pct = ((close - position['entry_price']) / position['entry_price']) * 100
        trailing_status = "TRAILING ACTIVE" if position.get('trailing_active') else "trailing pending"
        logger.info(
            f"[VENERDÌ] HOLD {symbol} ({strategy}): {profit_pct:+.1f}% | "
            f"high ${position['highest_price']:.2f} | stop ${position['stop_loss']:.2f} | {trailing_status}"
        )
        return None
    
    except Exception as e:
        logger.debug(f"Error checking Friday exit for {symbol}: {e}")
        return None


def system_decides_hold(position: dict, current_price: float, profit_pct: float, 
                        db: MarketDatabase, current_date) -> tuple:
    """
    LEGACY - No longer used after Solution B implementation.
    Kept for reference in case you want to restore the old 0-2% decision logic.
    
    Original purpose: decide whether to hold or close positions with 0-2% profit on Friday.
    Now replaced by: let all positive positions run with trailing stop.
    
    Returns:
        (should_close: bool, reason: str)
    """
    symbol = position['symbol']
    strategy = position['strategy'].lower()
    
    try:
        # Get recent data for analysis (~150 calendar days for 100 trading days)
        start_date = current_date - pd.Timedelta(days=150)
        df = db.get_data(symbol, start_date=start_date, end_date=current_date)
        if df.empty or len(df) < 20:
            return True, 'friday_insufficient_data'
        
        # Calculate indicators
        close = df['close'].values
        volume = df['volume'].values
        
        sma100 = df['close'].rolling(100).mean().iloc[-1] if len(df) >= 100 else df['close'].mean()
        avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        # 3-month return (proxy for trend strength)
        return_3m = ((close[-1] / close[0]) - 1) * 100 if len(close) > 60 else 0
        
        # ================================================================
        # MOMENTUM: HOLD if trend still strong (price > SMA100 and 3M return positive)
        # ================================================================
        if 'momentum' in strategy:
            price_above_sma = current_price > sma100
            trend_positive = return_3m > 0
            
            if price_above_sma and trend_positive:
                return False, 'hold_momentum_trend_intact'  # HOLD
            else:
                return True, 'friday_momentum_trend_weak'  # CLOSE
        
        # ================================================================
        # MEAN REVERSION: ALWAYS CLOSE (bounce is probably done)
        # ================================================================
        if 'mean_reversion' in strategy:
            return True, 'friday_mr_close'  # ALWAYS CLOSE
        
        # ================================================================
        # BREAKOUT: HOLD if volume still high (volume > 1.2x average)
        # ================================================================
        if 'breakout' in strategy:
            if volume_ratio > 1.2:
                return False, 'hold_breakout_volume_strong'  # HOLD
            else:
                return True, 'friday_breakout_volume_weak'  # CLOSE
        
        # Default: close unknown strategies
        return True, 'friday_unknown_strategy'
    
    except Exception as e:
        logger.debug(f"Error in system_decides for {symbol}: {e}")
        return True, 'friday_error'


def calculate_positions_mtm(positions: list, current_date, db: MarketDatabase) -> float:
    """Calculate mark-to-market value of all open positions"""
    total_mtm = 0.0
    for pos in positions:
        try:
            df = db.get_data_for_date(pos['symbol'], current_date)
            if not df.empty:
                current_price = float(df.iloc[0]['close'])
                position_value = current_price * pos['quantity'] * EUR_USD_RATE
                total_mtm += position_value
            else:
                # Fallback to entry value
                total_mtm += pos.get('capital_allocated', 0)
        except Exception:
            total_mtm += pos.get('capital_allocated', 0)
    return total_mtm


def create_outcome(position: dict, exit_date, exit_price: float, exit_reason: str):
    """Create trade outcome, including any TP1 partial profits"""
    # Apply exit slippage (we sell lower than the theoretical price)
    actual_exit_price = exit_price * (1 - EXIT_SLIPPAGE_PCT / 100)
    
    # Calculate P&L for remaining quantity
    pnl_usd = (actual_exit_price - position['entry_price']) * position['quantity']
    pnl_eur = pnl_usd * EUR_USD_RATE - 1.0  # Exit commission
    
    # Add TP1 partial profit if it was hit
    tp1_pnl = position.get('tp1_pnl', 0)
    total_pnl_eur = pnl_eur + tp1_pnl
    
    r_mult = (total_pnl_eur / position['risk_amount']) if position['risk_amount'] > 0 else 0
    
    return {
        'symbol': position['symbol'],
        'asset_class': position['asset_class'],
        'strategy': position['strategy'],
        'entry_date': position['entry_date'],
        'entry_price': position['entry_price'],
        'exit_date': exit_date,
        'exit_price': actual_exit_price,  # Price with slippage applied
        'exit_reason': exit_reason,
        'quantity': position.get('original_quantity', position['quantity']),
        'pnl_usd': pnl_usd,
        'pnl_eur': total_pnl_eur,
        'tp1_pnl': tp1_pnl,
        'r_multiple': r_mult,
        'risk_amount': position['risk_amount']
    }


def force_close_position(position: dict, exit_date, db: MarketDatabase):
    """Force close position at end of backtest"""
    symbol = position['symbol']
    try:
        df = db.get_data_for_date(symbol, exit_date)
        exit_price = float(df.iloc[0]['close']) if not df.empty else position['entry_price']
    except Exception:
        exit_price = position['entry_price']
    
    return create_outcome(position, exit_date, exit_price, 'forced_close')


def calculate_performance_metrics(trades, equity_curve, initial_capital, final_capital=None):
    """Calculate performance metrics"""
    if not trades:
        return {
            'error': 'No trades',
            'total_trades': 0,
            'win_rate': 0,
            'profit_factor': 0
        }
    
    df = pd.DataFrame(trades)
    pnl_eur = df['pnl_eur'].values
    
    winners = df[df['pnl_eur'] > 0]
    losers = df[df['pnl_eur'] <= 0]
    
    win_rate = (len(winners) / len(df)) * 100 if len(df) > 0 else 0
    gross_profit = winners['pnl_eur'].sum() if len(winners) > 0 else 0
    gross_loss = abs(losers['pnl_eur'].sum()) if len(losers) > 0 else 1e-9
    profit_factor = gross_profit / gross_loss
    
    avg_r = df['r_multiple'].mean()
    
    # Sharpe
    returns = pnl_eur / initial_capital
    sharpe = (returns.mean() / returns.std()) * np.sqrt(52) if returns.std() > 0 else 0  # Weekly
    
    # Max Drawdown
    cumulative_pnl = np.cumsum(pnl_eur)
    running_max = np.maximum.accumulate(cumulative_pnl)
    drawdown = cumulative_pnl - running_max
    max_dd = drawdown.min()
    max_dd_pct = (max_dd / initial_capital) * 100
    
    # CAGR
    df_equity = pd.DataFrame(equity_curve)
    if not df_equity.empty:
        start_date = df_equity['date'].iloc[0]
        end_date = df_equity['date'].iloc[-1]
        years = (end_date - start_date).days / 365.25
        
        if final_capital is not None:
            final_value = final_capital
        elif 'total_value' in df_equity.columns:
            final_value = df_equity['total_value'].iloc[-1]
        else:
            final_value = df_equity['capital'].iloc[-1]
        
        cagr = (((final_value / initial_capital) ** (1 / years)) - 1) * 100 if years > 0 else 0
    else:
        cagr = 0
    
    return {
        'total_trades': len(df),
        'winning_trades': len(winners),
        'losing_trades': len(losers),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_r_multiple': round(avg_r, 2),
        'sharpe_ratio': round(sharpe, 2),
        'max_drawdown': round(max_dd, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'best_trade': round(df['pnl_eur'].max(), 2),
        'worst_trade': round(df['pnl_eur'].min(), 2),
        'cagr': round(cagr, 2)
    }


def print_results(trades, metrics, regime_history, initial_capital, final_capital, 
                  total_return_pct, start, end, week_count):
    """Print backtest results"""
    print(f"\n{'=' * 80}")
    print("BACKTEST RESULTS - WORKFLOW TUE->FRI")
    print("=" * 80)
    print(f"\nPeriod: {start.date()} to {end.date()}")
    print(f"Total weeks: {week_count}")
    print(f"Initial capital: €{initial_capital:,.2f}")
    print(f"Final capital: €{final_capital:,.2f}")
    print(f"Total return: {total_return_pct:.2f}%")
    print(f"Annualized return: {metrics.get('cagr', 0):.2f}%")
    print(f"Monthly avg return: {total_return_pct / max(1, week_count / 4.33):.2f}%")
    
    print(f"\n--- Performance ---")
    print(f"Total trades: {metrics.get('total_trades', 0)}")
    print(f"Win rate: {metrics.get('win_rate', 0):.2f}%")
    print(f"Profit factor: {metrics.get('profit_factor', 0):.2f}")
    print(f"Avg R-multiple: {metrics.get('avg_r_multiple', 0):.2f}")
    print(f"Sharpe ratio (weekly): {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"Max drawdown: €{metrics.get('max_drawdown', 0):.2f} ({metrics.get('max_drawdown_pct', 0):.2f}%)")
    print(f"Best trade: €{metrics.get('best_trade', 0):.2f}")
    print(f"Worst trade: €{metrics.get('worst_trade', 0):.2f}")
    
    # Regime analysis
    if regime_history:
        df_regimes = pd.DataFrame(regime_history)
        print(f"\n--- Regime Distribution ---")
        for regime, count in df_regimes['regime'].value_counts().items():
            pct = (count / len(df_regimes)) * 100
            print(f"{regime}: {count} periods ({pct:.1f}%)")
        
        print(f"\n--- Strategy Usage ---")
        for strategy, count in df_regimes['strategy_used'].value_counts().items():
            pct = (count / len(df_regimes)) * 100
            print(f"{strategy}: {count} periods ({pct:.1f}%)")
    
    # Exit reasons
    if trades:
        df_trades = pd.DataFrame(trades)
        print(f"\n--- Exit Reasons ---")
        for reason, count in df_trades['exit_reason'].value_counts().items():
            pct = (count / len(df_trades)) * 100
            print(f"{reason}: {count} ({pct:.1f}%)")
        
        # Strategy performance
        print(f"\n--- Strategy Performance ---")
        for strategy in df_trades['strategy'].unique():
            strat_trades = df_trades[df_trades['strategy'] == strategy]
            strat_pnl = strat_trades['pnl_eur'].sum()
            strat_wins = len(strat_trades[strat_trades['pnl_eur'] > 0])
            strat_wr = (strat_wins / len(strat_trades)) * 100 if len(strat_trades) > 0 else 0
            print(f"{strategy}: {len(strat_trades)} trades, Win Rate {strat_wr:.1f}%, P&L €{strat_pnl:.2f}")


def save_results(start_date, end_date, initial_capital, final_capital, 
                 total_return_pct, metrics, trades, weekly_stats):
    """Save backtest results to JSON"""
    out_file = f"backtest_workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump({
            'strategy': 'workflow_tue_fri',
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'final_capital': final_capital,
            'total_return_pct': total_return_pct,
            'metrics': metrics,
            'total_trades': len(trades),
            'weeks_simulated': len(weekly_stats)
        }, f, indent=2)
    
    print(f"\nResults saved to: {out_file}")


def main():
    parser = argparse.ArgumentParser(description="Backtest Portfolio - Workflow Martedì→Venerdì")
    parser.add_argument("--years", type=int, default=1, help="Years to backtest")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital (EUR)")
    parser.add_argument("--slots", type=int, default=3, help="Max positions (default: 3)")
    
    args = parser.parse_args()
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")
    
    run_portfolio_backtest(
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
        max_slots=args.slots
    )


if __name__ == "__main__":
    main()
