"""VectorBT backtesting integration"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
from loguru import logger

from ..utils.config import config
from ..database.user_db import UserDatabase

# Try to import VectorBT - handle all possible errors
VECTORBT_AVAILABLE = False
vbt = None
VECTORBT_ERROR = None

try:
    import vectorbt as vbt
    VECTORBT_AVAILABLE = True
    logger.info("VectorBT successfully imported")
except ImportError as e:
    VECTORBT_AVAILABLE = False
    VECTORBT_ERROR = "not_installed"
    logger.info("VectorBT not installed. Backtesting will be disabled.")
    logger.info("To enable backtesting: pip install vectorbt")
except RuntimeError as e:
    VECTORBT_AVAILABLE = False
    VECTORBT_ERROR = "runtime_error"
    if "atexit" in str(e).lower() or "shutdown" in str(e).lower():
        logger.warning("VectorBT RuntimeError detected (likely Python 3.14 compatibility issue)")
        logger.warning("Solution: Use Python 3.11 or 3.12 for VectorBT compatibility")
        logger.warning("Current Python version may be incompatible with VectorBT dependencies")
    else:
        logger.warning(f"VectorBT RuntimeError: {e}")
except Exception as e:
    VECTORBT_AVAILABLE = False
    VECTORBT_ERROR = "unknown"
    logger.warning(f"VectorBT import failed: {type(e).__name__}: {str(e)[:100]}")
    logger.info("Backtesting will be disabled. Install VectorBT separately if needed.")


class VectorBTBacktester:
    """Backtest strategies using VectorBT"""
    
    def __init__(self):
        if not VECTORBT_AVAILABLE:
            error_msg = "VectorBT is not available."
            if VECTORBT_ERROR == "not_installed":
                error_msg += "\n\nInstall VectorBT with: pip install vectorbt"
            elif VECTORBT_ERROR == "runtime_error":
                error_msg += "\n\nVectorBT has compatibility issues with your Python version."
                error_msg += "\nSolution: Use Python 3.11 or 3.12 for full VectorBT compatibility."
                error_msg += "\nCurrent Python version may be incompatible with VectorBT dependencies (sklearn/joblib)."
            else:
                error_msg += "\n\nInstall VectorBT with: pip install vectorbt"
                error_msg += "\nNote: VectorBT may have compatibility issues with Python 3.14+"
                error_msg += "\nConsider using Python 3.11 or 3.12 for full compatibility."
            raise RuntimeError(error_msg)
        # Get capital from user settings first, then config, then default
        try:
            user_db = UserDatabase()
            capital_str = user_db.get_setting("portfolio_total_capital")
            self.initial_capital = float(capital_str) if capital_str else config.get("backtesting.initial_capital", 10000)
        except Exception:
            self.initial_capital = config.get("backtesting.initial_capital", 10000)
        
        self.commission = config.get("backtesting.commission", 0.001)
        self.slippage = config.get("backtesting.slippage", 0.0005)
    
    def backtest_strategy(
        self,
        df: pd.DataFrame,
        entry_signals: pd.Series,
        exit_signals: Optional[pd.Series] = None
    ) -> Dict:
        """
        Backtest a strategy using VectorBT
        
        Args:
            df: OHLCV DataFrame
            entry_signals: Boolean series for entry signals
            exit_signals: Boolean series for exit signals (optional)
        
        Returns:
            Dict with backtest results
        """
        if not VECTORBT_AVAILABLE:
            return {'error': 'vectorbt not installed - install with: pip install vectorbt'}
        
        if df.empty or entry_signals.empty:
            return {'error': 'Empty data or signals'}
        
        try:
            # Ensure signals align with price data
            prices = df['close']
            
            # Validate data
            if len(prices) == 0:
                return {'error': 'No price data available'}
            
            if prices.isna().all():
                return {'error': 'All prices are NaN'}
            
            # Reindex signals to match prices
            entry_signals = entry_signals.reindex(prices.index, fill_value=False)
            
            # Validate signals
            if entry_signals.sum() == 0:
                return {'error': 'No entry signals found in the data'}
            
            # Create exit signals if not provided (exit on opposite signal)
            if exit_signals is None:
                # Use opposite of entry signals, but ensure we have valid exits
                exit_signals = pd.Series(False, index=prices.index)
                # Set exit when entry signal ends
                for i in range(len(entry_signals) - 1):
                    if entry_signals.iloc[i] and not entry_signals.iloc[i+1]:
                        exit_signals.iloc[i+1] = True
            else:
                exit_signals = exit_signals.reindex(prices.index, fill_value=False)
            
            # Ensure we have at least some exit signals
            if exit_signals.sum() == 0:
                logger.warning("No exit signals found, using opposite of entry signals")
                exit_signals = ~entry_signals
            
            # Run backtest
            try:
                pf = vbt.Portfolio.from_signals(
                    prices,
                    entries=entry_signals,
                    exits=exit_signals,
                    init_cash=self.initial_capital,
                    fees=self.commission + self.slippage,
                    freq='D'
                )
            except Exception as vbt_error:
                logger.error(f"VectorBT Portfolio.from_signals error: {type(vbt_error).__name__}: {vbt_error}")
                return {'error': f'VectorBT error: {str(vbt_error)}'}
            
            # Extract metrics with error handling
            try:
                total_return = pf.total_return()
                sharpe_ratio = pf.sharpe_ratio()
                max_drawdown = pf.max_drawdown()
                
                # Get trades info
                trades = pf.trades
                win_rate = trades.win_rate() if len(trades) > 0 else None
                total_trades = len(trades)
                
                portfolio_value = pf.value()
                final_value = float(portfolio_value.iloc[-1]) if len(portfolio_value) > 0 else self.initial_capital
                
                return {
                    'total_return': float(total_return) if pd.notna(total_return) else 0.0,
                    'total_return_pct': float(total_return * 100) if pd.notna(total_return) else 0.0,
                    'sharpe_ratio': float(sharpe_ratio) if pd.notna(sharpe_ratio) else None,
                    'max_drawdown': float(max_drawdown) if pd.notna(max_drawdown) else None,
                    'win_rate': float(win_rate) if pd.notna(win_rate) and win_rate is not None else None,
                    'total_trades': int(total_trades),
                    'final_value': final_value,
                    'portfolio': pf
                }
            except Exception as metric_error:
                logger.error(f"Error extracting metrics: {type(metric_error).__name__}: {metric_error}")
                return {'error': f'Error calculating metrics: {str(metric_error)}'}
            
        except Exception as e:
            logger.error(f"Backtest error: {type(e).__name__}: {e}", exc_info=True)
            return {'error': f'{type(e).__name__}: {str(e)}'}
    
    def optimize_parameters(
        self,
        df: pd.DataFrame,
        param_ranges: Dict[str, np.ndarray],
        signal_function
    ) -> Dict:
        """
        Optimize strategy parameters using VectorBT
        
        Args:
            df: OHLCV DataFrame
            param_ranges: Dict of parameter names to arrays of values to test
            signal_function: Function that generates signals given (df, **params)
        
        Returns:
            Dict with best parameters and results
        """
        # This is a simplified version - full optimization would use VectorBT's grid search
        logger.info("Parameter optimization not fully implemented yet")
        return {'status': 'not_implemented'}
