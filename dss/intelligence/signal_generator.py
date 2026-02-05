"""
Main signal generation pipeline using 100-point scoring system.

⚠️ DEPRECATION NOTICE:
This module is DEPRECATED in favor of dss.core.portfolio_manager.PortfolioManager
which provides a simpler, less overfitting-prone approach with:
- Multi-strategy system (Momentum, Mean Reversion, Breakout)
- Regime detection for strategy selection
- ETF leveraged signals for strong trends

The 100-point scoring system is kept for backward compatibility with:
- Historical backtests (backtest-legacy mode)
- Development/debugging (detailed scoring breakdown)

For production use, use PortfolioManager instead:
    from dss.core.portfolio_manager import PortfolioManager
    mgr = PortfolioManager()
    signals = mgr.generate_portfolio_signals()
"""
import pandas as pd
import asyncio
import warnings
from typing import List, Dict, Optional
from loguru import logger

from ..database.market_db import MarketDatabase
from ..database.user_db import UserDatabase
from .indicators import IndicatorCalculator
from .scoring import SignalScorer
from .screening import StockScreener
from ..notifications.telegram_bot import TelegramNotifier
from ..utils.config import config


class SignalGenerator:
    """Orchestrate signal generation pipeline"""
    
    def __init__(self):
        self.db = MarketDatabase()
        self.scorer = SignalScorer()
        self.screener = StockScreener()
        self.benchmark_symbol = config.get("filters.benchmark_symbol", "SPY")
        self.telegram = TelegramNotifier() if config.get("telegram.enabled", True) else None
    
    def generate_signals(self, symbols: Optional[List[str]] = None, 
                        min_score: int = 50) -> List[Dict]:
        """
        Generate signals for all symbols
        
        Args:
            symbols: List of symbols to analyze (None = all in DB)
            min_score: Minimum score to include in results
        
        Returns:
            List of signal dicts sorted by score
        """
        if symbols is None:
            symbols = self.db.get_all_symbols()
        
        logger.info(f"Generating signals for {len(symbols)} symbols")
        
        # Get benchmark data
        benchmark_df = None
        try:
            benchmark_data = self.db.get_data(self.benchmark_symbol)
            if not benchmark_data.empty:
                benchmark_df = IndicatorCalculator.calculate_all(benchmark_data)
                market_regime = self.screener.check_market_regime(benchmark_df)
                logger.info(f"Market regime: {market_regime['regime']} (stricter: {market_regime['stricter_criteria']})")
        except Exception as e:
            logger.warning(f"Could not load benchmark {self.benchmark_symbol}: {e}")
        
        signals = []
        lookback_days = config.get("backtesting.lookback_days", 1260)  # Default 5 years
        
        # Get all data at once for efficiency
        # With more historical data available, use longer lookback for better analysis
        logger.info(f"Fetching data with {lookback_days} days lookback ({lookback_days/252:.1f} years)")
        all_data = self.db.get_latest_bars(symbols, lookback_days)
        
        for symbol in symbols:
            try:
                # Get symbol data
                symbol_data = all_data[all_data['symbol'] == symbol].copy()
                if symbol_data.empty:
                    continue
                
                symbol_data = symbol_data.sort_values('timestamp').reset_index(drop=True)
                
                # Step 1: Quality Filters
                filter_result = self.screener.apply_filters(symbol_data, symbol)
                if not filter_result['passed']:
                    logger.info(f"{symbol}: Filtered out - {filter_result['reasons']}")
                    continue
                
                # Step 2: Calculate Indicators
                symbol_data = IndicatorCalculator.calculate_all(symbol_data)
                
                # Step 3: Volume Profile
                volume_profile = IndicatorCalculator.calculate_volume_profile(symbol_data)
                
                # Step 3.5: Get weekly data for timeframe confluence
                # Resample daily data to weekly (more efficient than fetching from API)
                weekly_data = None
                try:
                    if len(symbol_data) >= 50:  # Need at least 50 days for meaningful weekly data
                        # Resample daily to weekly
                        symbol_data_indexed = symbol_data.set_index('timestamp')
                        weekly_resampled = symbol_data_indexed.resample('W').agg({
                            'open': 'first',
                            'high': 'max',
                            'low': 'min',
                            'close': 'last',
                            'volume': 'sum',
                            'symbol': 'first'
                        }).reset_index()
                        
                        if len(weekly_resampled) >= 10:  # Need at least 10 weeks
                            weekly_data = IndicatorCalculator.calculate_all(weekly_resampled)
                except Exception as e:
                    logger.debug(f"Could not resample weekly data for {symbol}: {e}")
                    weekly_data = None
                
                # Step 4: Scoring
                score_result = self.scorer.score_symbol(symbol_data, benchmark_df, volume_profile, weekly_data)
                
                if score_result['score'] < min_score:
                    continue
                
                # Step 4.5: Validate trade economics (commission filter)
                commission_cost = score_result.get('commission_cost', 0)
                position_size = score_result.get('position_size', 0)
                entry_price = score_result.get('entry_price', 0)
                
                if position_size > 0 and entry_price > 0:
                    min_trade_value = config.get("risk.min_trade_value", 50.0)
                    trade_validation = self.screener.validate_trade_economics(
                        entry_price, position_size, commission_cost, min_trade_value
                    )
                    
                    if not trade_validation['is_valid']:
                        logger.info(f"{symbol}: Filtered out - {trade_validation['reason']}")
                        continue
                    
                    # Add validation info to score result
                    score_result['trade_validation'] = trade_validation
                
                # Step 5: Compile signal
                signal = {
                    'symbol': symbol,
                    'score': score_result['score'],
                    'max_score': score_result['max_score'],
                    'entry_price': score_result['entry_price'],
                    'stop_loss': score_result['stop_loss'],
                    'target_price': score_result.get('target_price'),  # Include target price
                    'position_size': score_result['position_size'],
                    'risk_amount': score_result['risk_amount'],
                    'commission_cost': score_result.get('commission_cost', 2.0),
                    'current_price': score_result['current_price'],
                    'atr': score_result['atr'],
                    'sma_200': score_result['sma_200'],
                    'rsi': score_result['rsi'],
                    'breakdown': score_result['breakdown'],
                    'volume_profile': {
                        'poc_price': volume_profile.get('poc_price'),
                        'value_area_high': volume_profile.get('value_area_high'),
                        'value_area_low': volume_profile.get('value_area_low')
                    },
                    'filter_info': filter_result
                }
                
                signals.append(signal)
                logger.info(f"{symbol}: Score {score_result['score']}/100 ({score_result.get('classification', 'UNKNOWN')})")
                
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)
                continue
        
        # Sort by score descending
        signals.sort(key=lambda x: x['score'], reverse=True)
        
        logger.info(f"Generated {len(signals)} signals with score >= {min_score}")
        
        # Portfolio-level filter: Return top signals (max 3)
        # Note: Full portfolio management moved to dss.core.portfolio_manager
        selected_signals = signals[:3]  # Take top 3 by score
        logger.info(f"Selected top {len(selected_signals)} signals from {len(signals)}")
        
        # Send Telegram alerts only for selected signals
        if self.telegram and self.telegram.enabled and config.get("telegram.alert_on_signal", True):
            try:
                # Check if there's already an event loop running
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is running, we can't use asyncio.run()
                        # Schedule in background thread instead
                        import threading
                        def send_alerts():
                            new_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(new_loop)
                            try:
                                new_loop.run_until_complete(self._send_telegram_alerts(selected_signals))
                            finally:
                                new_loop.close()
                        thread = threading.Thread(target=send_alerts, daemon=True)
                        thread.start()
                    else:
                        asyncio.run(self._send_telegram_alerts(selected_signals))
                except RuntimeError:
                    asyncio.run(self._send_telegram_alerts(selected_signals))
            except Exception as e:
                logger.warning(f"Failed to send Telegram alerts: {e}")
        
        return selected_signals
    
    async def _send_telegram_alerts(self, signals: List[Dict]):
        """Send Telegram alerts for generated signals"""
        if not self.telegram or not self.telegram.enabled:
            return
        
        # Send alerts for top signals (limit to avoid spam)
        max_alerts = config.get("telegram.max_signal_alerts", 10)
        top_signals = signals[:max_alerts]
        
        # Send alerts sequentially with delays to avoid pool timeout
        # Use semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(1)  # Only one message at a time
        
        for i, signal in enumerate(top_signals):
            try:
                async with semaphore:
                    success = await self.telegram.send_signal_alert(signal)
                    if not success:
                        logger.debug(f"Telegram alert not sent for {signal.get('symbol', 'unknown')}")
                
                # Delay between messages to avoid rate limits and pool exhaustion
                # Increased delay to reduce pool timeout errors
                if i < len(top_signals) - 1:  # Don't delay after last message
                    await asyncio.sleep(2.0)  # Increased delay to 2 seconds
            except Exception as e:
                logger.debug(f"Failed to send Telegram alert for {signal.get('symbol', 'unknown')}: {e}")
                # Continue with next signal even if one fails
                # Add delay even on error to avoid overwhelming the pool
                if i < len(top_signals) - 1:
                    await asyncio.sleep(1.0)
                continue
    
    def generate_signals_as_of(
        self,
        end_date: pd.Timestamp,
        symbols: Optional[List[str]] = None,
        min_score: int = 50,
    ) -> List[Dict]:
        """
        Generate signals using only data up to end_date (for backtest, no look-ahead).

        Args:
            end_date: Last date included in data (inclusive).
            symbols: Symbols to analyze (None = all in DB).
            min_score: Minimum score for signals.

        Returns:
            List of signal dicts sorted by score (no Telegram).
        """
        if symbols is None:
            symbols = self.db.get_all_symbols()
        if not symbols:
            return []

        lookback_days = config.get("backtesting.lookback_days", 1260)
        all_data = self.db.get_bars_until(symbols, end_date, lookback_days)
        if all_data.empty:
            return []

        benchmark_df = None
        try:
            bench = self.db.get_bars_until([self.benchmark_symbol], end_date, lookback_days)
            if not bench.empty:
                benchmark_df = IndicatorCalculator.calculate_all(bench)
        except Exception:
            pass

        signals = []
        for symbol in symbols:
            try:
                symbol_data = all_data[all_data["symbol"] == symbol].copy()
                if symbol_data.empty or len(symbol_data) < 50:
                    continue
                symbol_data = symbol_data.sort_values("timestamp").reset_index(drop=True)

                filter_result = self.screener.apply_filters(symbol_data, symbol)
                if not filter_result["passed"]:
                    continue

                symbol_data = IndicatorCalculator.calculate_all(symbol_data)
                volume_profile = IndicatorCalculator.calculate_volume_profile(symbol_data)

                weekly_data = None
                try:
                    if len(symbol_data) >= 50:
                        symbol_data_indexed = symbol_data.set_index("timestamp")
                        weekly_resampled = symbol_data_indexed.resample("W").agg({
                            "open": "first", "high": "max", "low": "min",
                            "close": "last", "volume": "sum", "symbol": "first",
                        }).reset_index()
                        if len(weekly_resampled) >= 10:
                            weekly_data = IndicatorCalculator.calculate_all(weekly_resampled)
                except Exception:
                    pass

                score_result = self.scorer.score_symbol(
                    symbol_data, benchmark_df, volume_profile, weekly_data
                )
                if score_result["score"] < min_score:
                    continue

                commission_cost = score_result.get("commission_cost", 0)
                position_size = score_result.get("position_size", 0)
                entry_price = score_result.get("entry_price", 0)
                if position_size > 0 and entry_price > 0:
                    min_trade_value = config.get("risk.min_trade_value", 50.0)
                    trade_validation = self.screener.validate_trade_economics(
                        entry_price, position_size, commission_cost, min_trade_value
                    )
                    if not trade_validation.get("is_valid", True):
                        continue

                signal = {
                    "symbol": symbol,
                    "score": score_result["score"],
                    "max_score": score_result["max_score"],
                    "entry_price": score_result["entry_price"],
                    "stop_loss": score_result["stop_loss"],
                    "target_price": score_result.get("target_price"),
                    "position_size": score_result["position_size"],
                    "risk_amount": score_result["risk_amount"],
                    "commission_cost": score_result.get("commission_cost", 2.0),
                    "current_price": score_result["current_price"],
                    "atr": score_result.get("atr"),
                    "sma_200": score_result.get("sma_200"),
                    "rsi": score_result.get("rsi"),
                    "breakdown": score_result.get("breakdown", {}),
                    "volume_profile": {},
                    "filter_info": filter_result,
                }
                signals.append(signal)
            except Exception as e:
                logger.debug(f"generate_signals_as_of {symbol}: {e}")
                continue

        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals

    def close(self):
        """Cleanup"""
        self.db.close()
