"""Price monitoring and trailing stop management"""
import pandas as pd
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger

from ..database.user_db import UserDatabase
from ..notifications.telegram_bot import TelegramNotifier
from ..utils.config import config
from pathlib import Path

# Provider per snapshot (~15 min ritardato): opzionale
_snapshot_provider = None


def _get_snapshot_provider():
    """Lazy init Polygon provider per prezzo di oggi (~15 min delay)."""
    global _snapshot_provider
    if _snapshot_provider is None:
        try:
            from ..ingestion.polygon_provider import PolygonProvider
            _snapshot_provider = PolygonProvider()
        except Exception as e:
            logger.debug(f"Snapshot provider not available: {e}")
    return _snapshot_provider


class PriceMonitor:
    """Monitor prices and manage trailing stops"""
    
    def __init__(self):
        # Don't create persistent connection - DuckDB doesn't allow multiple connections
        # We'll create connections on-demand to avoid locking issues
        self.user_db = UserDatabase()
        self.telegram = TelegramNotifier() if config.get("telegram.enabled", True) else None
        # Read interval from user_db first (Settings), then config. Default 600 = 10 min.
        interval_str = self.user_db.get_setting("monitoring_interval_seconds")
        self.monitoring_interval = int(interval_str) if interval_str else config.get("telegram.monitoring_interval_seconds", 600)
        
        # Store path for on-demand connections
        self.market_db_path = Path(config.get_env("DUCKDB_PATH", "./data/market_data.duckdb"))
    
    def _get_market_data(self, symbol: str):
        """Get market data using a temporary connection (to avoid DuckDB locking issues)"""
        import duckdb
        import time
        
        # Try to connect with retries (database might be locked by dashboard)
        max_retries = 3
        retry_delay = 1.0  # seconds
        
        for attempt in range(max_retries):
            try:
                # Try to connect (DuckDB doesn't support true read-only, but we can try)
                conn = duckdb.connect(str(self.market_db_path))
                try:
                    query = "SELECT * FROM market_data WHERE symbol = ? ORDER BY timestamp"
                    df = conn.execute(query, [symbol]).df()
                    return df
                finally:
                    conn.close()
            except Exception as e:
                if "already open" in str(e).lower() or "being used" in str(e).lower():
                    if attempt < max_retries - 1:
                        logger.debug(f"Database locked, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.warning(f"Database is locked by another process (likely dashboard). Skipping {symbol} this cycle.")
                        return pd.DataFrame()
                else:
                    logger.error(f"Failed to get market data for {symbol}: {e}")
                    return pd.DataFrame()
        
        return pd.DataFrame()
    
    def get_active_positions(self) -> List[Dict]:
        """Get all active positions from user database"""
        try:
            positions = self.user_db.get_active_positions()
            return positions
        except Exception as e:
            logger.error(f"Error fetching active positions: {e}")
            return []
    
    def update_position_stop(self, symbol: str, new_stop: float, reason: str = "Trailing stop"):
        """Update stop loss for a position"""
        try:
            old_stop = self.user_db.get_position_stop(symbol)
            self.user_db.update_position_stop(symbol, new_stop, reason)
            
            # Send Telegram alert (non-blocking, errors are handled in telegram_bot)
            if self.telegram and self.telegram.enabled:
                try:
                    asyncio.run(self.telegram.send_stop_update(symbol, old_stop, new_stop))
                except Exception as e:
                    logger.debug(f"Could not send stop update alert: {e}")
            
            logger.info(f"{symbol}: Stop updated {old_stop:.2f} -> {new_stop:.2f} ({reason})")
            return True
        except Exception as e:
            logger.error(f"Error updating stop for {symbol}: {e}")
            return False
    
    def check_price_levels(self, symbol: str, current_price: float, 
                          entry_price: float, stop_loss: float, 
                          target_price: Optional[float] = None) -> Dict:
        """
        Check if price has reached any significant levels
        
        Returns:
            Dict with level_type and message if level reached
        """
        result = {
            'level_reached': False,
            'level_type': None,
            'message': None
        }
        
        # Check stop loss hit
        if current_price <= stop_loss:
            result['level_reached'] = True
            result['level_type'] = 'stop_loss'
            result['message'] = f"{symbol} hit stop loss at ${stop_loss:.2f}"
            return result
        
        # Check target price reached (take profit)
        if target_price and current_price >= target_price:
            result['level_reached'] = True
            result['level_type'] = 'target_reached'
            result['message'] = f"{symbol} reached target price ${target_price:.2f}"
            return result
        
        # Check entry price reached (for pending entries)
        if abs(current_price - entry_price) / entry_price < 0.01:  # Within 1%
            result['level_reached'] = True
            result['level_type'] = 'entry_reached'
            result['message'] = f"{symbol} reached entry price ${entry_price:.2f}"
            return result
        
        return result
    
    def calculate_trailing_stop(self, symbol: str, entry_price: float, 
                               current_price: float, atr: float, 
                               highest_price: float) -> Optional[float]:
        """
        Calculate new trailing stop per Trading System Specification v1.0 Section 7.2:
        
        "Once a trade is in profit by 1× ATR, the stop trails at 1.5× ATR below 
        the highest price reached."
        
        Args:
            symbol: Stock symbol
            entry_price: Original entry price
            current_price: Current market price
            atr: Average True Range (14-period)
            highest_price: Highest price since entry
        
        Returns:
            New stop loss price or None if no update needed
        """
        if not atr or atr <= 0:
            return None
        
        # Check if trailing should activate (profit >= 1× ATR per spec)
        profit = highest_price - entry_price
        if profit < atr:
            # Not yet in sufficient profit - don't trail
            return None
        
        # Trailing active: Stop = Highest Price - (1.5 × ATR) per spec
        TRAILING_ATR_MULTIPLIER = 1.5  # Per spec Section 7.2
        new_stop = highest_price - (atr * TRAILING_ATR_MULTIPLIER)
        
        # Stop should never go below entry price once trailing activates (breakeven minimum)
        new_stop = max(new_stop, entry_price)
        
        # Get current stop and only move up, never down
        current_stop = self.user_db.get_position_stop(symbol)
        if current_stop:
            new_stop = max(new_stop, current_stop)
        
        # Ensure stop is below current price (safety)
        if new_stop >= current_price:
            return None
        
        # Only update if new stop is significantly higher (avoid noise updates)
        if current_stop and (new_stop - current_stop) / current_stop < 0.01:  # Less than 1% improvement
            return None
        
        return new_stop
    
    def check_partial_exit_levels(self, symbol: str, entry_price: float,
                                   current_price: float, atr: float,
                                   position: Dict) -> Optional[Dict]:
        """
        Check if partial exit levels (TP1/TP2) are reached per spec Section 7.3:
        
        - TP1: Entry + 1.5× ATR → Sell 50%, move SL to breakeven
        - TP2: Entry + 3× ATR → Close remaining position
        
        Args:
            symbol: Stock symbol
            entry_price: Original entry price
            current_price: Current market price
            atr: Average True Range
            position: Position dict from database
        
        Returns:
            Dict with action if level reached, None otherwise
        """
        if not atr or atr <= 0:
            return None
        
        # Calculate TP levels per spec
        tp1_price = entry_price + (1.5 * atr)
        tp2_price = entry_price + (3.0 * atr)
        
        # Check if already partially exited (TP1 hit)
        tp1_hit = position.get('tp1_hit', False)
        
        # Check TP2 first (full exit)
        if current_price >= tp2_price:
            return {
                'action': 'tp2_full_exit',
                'level': 'TP2',
                'price': tp2_price,
                'message': f"{symbol}: TP2 reached (${tp2_price:.2f}) - Close remaining position"
            }
        
        # Check TP1 (partial exit - only if not already hit)
        if not tp1_hit and current_price >= tp1_price:
            return {
                'action': 'tp1_partial_exit',
                'level': 'TP1',
                'price': tp1_price,
                'new_stop': entry_price,  # Move stop to breakeven
                'message': f"{symbol}: TP1 reached (${tp1_price:.2f}) - Sell 50%, move stop to breakeven ${entry_price:.2f}"
            }
        
        return None
    
    async def monitor_positions(self):
        """Monitor all active positions and update trailing stops"""
        positions = self.get_active_positions()
        
        if not positions:
            logger.debug("No active positions to monitor")
            return
        
        logger.info(f"Monitoring {len(positions)} active positions")
        
        for position in positions:
            symbol = position['symbol']
            entry_price = position['entry_price']
            stop_loss = position['stop_loss']
            target_price = position.get('target_price')
            
            try:
                # Prezzo corrente: prima snapshot Polygon (~15 min ritardato, dati di oggi), altrimenti ultima barra giornaliera
                current_price = None
                provider = _get_snapshot_provider()
                if provider:
                    try:
                        snapshot = await provider.get_latest_snapshot(symbol)
                        if snapshot and snapshot.get("last_price") is not None:
                            current_price = float(snapshot["last_price"])
                    except Exception as e:
                        logger.debug(f"Snapshot for {symbol}: {e}")
                if current_price is None:
                    symbol_data = self._get_market_data(symbol)
                    if symbol_data.empty:
                        logger.debug(f"No data available for {symbol}, skipping")
                        continue
                    latest = symbol_data.iloc[-1]
                    current_price = latest['close']
                else:
                    symbol_data = self._get_market_data(symbol)  # serve per trailing stop / ATR

                # Check if price level reached
                level_check = self.check_price_levels(symbol, current_price, entry_price, stop_loss, target_price)
                if level_check['level_reached']:
                    level_type = level_check['level_type']
                    # Send alert only once per level per symbol (evita messaggi ripetuti ogni 5 min)
                    already_sent = self.user_db.was_price_alert_sent(symbol, level_type)
                    if not already_sent and self.telegram and self.telegram.enabled:
                        await self.telegram.send_price_alert(
                            symbol,
                            current_price,
                            level_type,
                            entry_price=entry_price,
                            stop_loss=stop_loss
                        )
                        self.user_db.set_price_alert_sent(symbol, level_type)
                    
                    # If stop loss hit, mark position as closed
                    if level_check['level_type'] == 'stop_loss':
                        self.user_db.close_position(symbol, current_price, "Stop loss hit")
                        continue
                    
                    # If target reached, mark position as closed
                    if level_check['level_type'] == 'target_reached':
                        self.user_db.close_position(symbol, current_price, "Target reached")
                        continue
                
                # Calculate ATR for trailing stop and TP checks
                from .indicators import IndicatorCalculator
                if not symbol_data.empty:
                    symbol_data_with_indicators = IndicatorCalculator.calculate_all(symbol_data)
                    atr = symbol_data_with_indicators['atr'].iloc[-1] if 'atr' in symbol_data_with_indicators.columns else None
                    
                    # Check TP1/TP2 partial exit levels (per spec Section 7.3)
                    if atr and atr > 0:
                        tp_check = self.check_partial_exit_levels(symbol, entry_price, current_price, atr, position)
                        if tp_check:
                            level_type = tp_check['action']
                            already_sent = self.user_db.was_price_alert_sent(symbol, level_type)
                            
                            if not already_sent:
                                # Send TP alert
                                if self.telegram and self.telegram.enabled:
                                    await self.telegram.send_price_alert(
                                        symbol,
                                        current_price,
                                        f"tp1_reached" if tp_check['level'] == 'TP1' else "tp2_reached",
                                        entry_price=entry_price,
                                        stop_loss=stop_loss
                                    )
                                self.user_db.set_price_alert_sent(symbol, level_type)
                                
                                # If TP1, move stop to breakeven
                                if tp_check['action'] == 'tp1_partial_exit':
                                    new_stop = tp_check.get('new_stop', entry_price)
                                    self.update_position_stop(symbol, new_stop, "TP1 hit - moved to breakeven")
                                    logger.info(tp_check['message'])
                                
                                # If TP2, close position (remaining 50%)
                                elif tp_check['action'] == 'tp2_full_exit':
                                    self.user_db.close_position(symbol, current_price, "TP2 full target reached")
                                    logger.info(tp_check['message'])
                                    continue
                
                # Trailing stop: Activate once in profit by 1× ATR (per spec Section 7.2)
                current_stop = position.get('current_stop_loss') or stop_loss
                if not symbol_data.empty and atr and atr > 0:
                    entry_date = pd.to_datetime(position.get('entry_date', symbol_data['timestamp'].min()))
                    price_since_entry = symbol_data[symbol_data['timestamp'] >= entry_date]['close']
                    highest_price = price_since_entry.max() if not price_since_entry.empty else current_price
                    
                    new_stop = self.calculate_trailing_stop(
                        symbol, entry_price, current_price, atr, highest_price
                    )
                    if new_stop and new_stop > current_stop:
                        self.update_position_stop(symbol, new_stop, "Trailing stop (1.5× ATR)")
                
            except Exception as e:
                logger.error(f"Error monitoring {symbol}: {e}")
                continue
    
    async def run_continuous_monitoring(self):
        """Run continuous monitoring loop.
        Notifications are sent only when an event happens (level reached, trailing stop update),
        not every interval. Optional heartbeat every 6 cycles (~1h at 10min) confirms monitor is alive.
        """
        logger.info(f"Starting price monitoring (interval: {self.monitoring_interval}s)")
        heartbeat_interval_cycles = 6  # Send status to Telegram every 6 cycles (~1h if interval=600s)
        cycle = 0
        
        while True:
            try:
                positions = self.get_active_positions()
                await self.monitor_positions()
                cycle += 1
                # Heartbeat: ogni N cicli invia un messaggio "Monitor attivo" su Telegram
                if (
                    heartbeat_interval_cycles > 0
                    and cycle % heartbeat_interval_cycles == 0
                    and self.telegram
                    and self.telegram.enabled
                    and positions
                ):
                    try:
                        n = len(positions)
                        syms = ", ".join(p["symbol"] for p in positions[:3])
                        if n > 3:
                            syms += f" +{n - 3} altre"
                        await self.telegram.send_message(
                            f"📊 <b>Monitor attivo</b>\n"
                            f"Controllo ogni {self.monitoring_interval // 60} min · "
                            f"{n} posizione/i: {syms}\n"
                            f"<i>Notifiche inviate solo quando succede qualcosa (livello raggiunto, stop aggiornato).</i>"
                        )
                    except Exception as e:
                        logger.debug(f"Heartbeat Telegram skipped: {e}")
                await asyncio.sleep(self.monitoring_interval)
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(self.monitoring_interval)
    
    def close(self):
        """Cleanup"""
        global _snapshot_provider
        if _snapshot_provider is not None:
            try:
                asyncio.run(_snapshot_provider.close())  # evita "Unclosed client session"
            except Exception:
                pass
            _snapshot_provider = None
        self.user_db.close()
