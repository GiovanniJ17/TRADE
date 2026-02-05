"""SQLite user data database"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
from loguru import logger

from ..utils.config import config


class UserDatabase:
    """SQLite database for user data (OLTP)"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or config.get_env("SQLITE_PATH", "./data/user_data.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize_schema(self):
        """Initialize database schema"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Watchlist table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol VARCHAR PRIMARY KEY,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)
        
        # Trading journal
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trading_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR NOT NULL,
                entry_date TIMESTAMP NOT NULL,
                entry_price DOUBLE NOT NULL,
                exit_date TIMESTAMP,
                exit_price DOUBLE,
                quantity INTEGER NOT NULL,
                stop_loss DOUBLE,
                target_price DOUBLE,
                current_stop_loss DOUBLE,  -- Current trailing stop (updated over time)
                status VARCHAR DEFAULT 'open',  -- open, closed, stopped, target_reached
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Executed orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS executed_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR NOT NULL,
                order_type VARCHAR NOT NULL,  -- buy, sell
                price DOUBLE NOT NULL,
                quantity INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                broker_order_id VARCHAR,
                notes TEXT
            )
        """)
        
        # Signal history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR NOT NULL,
                signal_date TIMESTAMP NOT NULL,
                score DOUBLE NOT NULL,
                entry_price DOUBLE,
                stop_loss DOUBLE,
                position_size INTEGER,
                status VARCHAR DEFAULT 'generated',  -- generated, executed, expired
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User settings (capital, telegram config, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key VARCHAR PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Telegram: invio alert prezzo solo una volta per livello/simbolo (evita ripetizioni ogni 5 min)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_alert_sent (
                symbol VARCHAR NOT NULL,
                level_type VARCHAR NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, level_type)
            )
        """)
        
        conn.commit()
        
        # Migrate existing tables to add new columns if needed
        self._migrate_schema(conn)
        
        conn.close()
        logger.info("User database schema initialized")
    
    def _migrate_schema(self, conn: sqlite3.Connection):
        """Migrate existing schema to add new columns if they don't exist"""
        cursor = conn.cursor()
        
        # Check if trading_journal table exists and get its columns
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='trading_journal'
        """)
        if cursor.fetchone():
            # Get existing columns
            cursor.execute("PRAGMA table_info(trading_journal)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # Add current_stop_loss if missing
            if 'current_stop_loss' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE trading_journal ADD COLUMN current_stop_loss DOUBLE")
                    logger.info("Added column 'current_stop_loss' to trading_journal")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Could not add column 'current_stop_loss': {e}")
            
            # Add updated_at if missing (SQLite doesn't support DEFAULT CURRENT_TIMESTAMP in ALTER TABLE)
            if 'updated_at' not in existing_columns:
                try:
                    # Add column without default first
                    cursor.execute("ALTER TABLE trading_journal ADD COLUMN updated_at TIMESTAMP")
                    # Update existing records with current timestamp
                    cursor.execute("""
                        UPDATE trading_journal 
                        SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                        WHERE updated_at IS NULL
                    """)
                    # If created_at doesn't exist, use CURRENT_TIMESTAMP
                    cursor.execute("""
                        UPDATE trading_journal 
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """)
                    logger.info("Added column 'updated_at' to trading_journal")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Could not add column 'updated_at': {e}")
            
            # Initialize current_stop_loss for existing open positions that don't have it set
            cursor.execute("""
                UPDATE trading_journal 
                SET current_stop_loss = stop_loss 
                WHERE status = 'open' AND current_stop_loss IS NULL AND stop_loss IS NOT NULL
            """)
        
        conn.commit()
    
    # Watchlist methods
    def add_to_watchlist(self, symbol: str, notes: str = ""):
        """Add symbol to watchlist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, notes) VALUES (?, ?)",
            (symbol.upper(), notes)
        )
        conn.commit()
        conn.close()
    
    def remove_from_watchlist(self, symbol: str):
        """Remove symbol from watchlist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
        conn.commit()
        conn.close()
    
    def get_watchlist(self) -> List[Dict]:
        """Get all watchlist symbols"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM watchlist ORDER BY symbol")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Trading journal methods
    def add_trade(self, symbol: str, entry_price: float, quantity: int,
                  stop_loss: Optional[float] = None, target_price: Optional[float] = None,
                  notes: str = ""):
        """Add trade to journal"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trading_journal 
            (symbol, entry_date, entry_price, quantity, stop_loss, target_price, current_stop_loss, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), datetime.now(), entry_price, quantity, stop_loss, target_price, stop_loss, notes))
        conn.commit()
        conn.close()
    
    def update_trade(self, trade_id: int, exit_price: Optional[float] = None,
                     status: Optional[str] = None, notes: str = ""):
        """Update trade in journal"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if exit_price is not None:
            updates.append("exit_price = ?")
            params.append(exit_price)
            updates.append("exit_date = ?")
            params.append(datetime.now())
        
        if status:
            updates.append("status = ?")
            params.append(status)
        
        if notes:
            updates.append("notes = ?")
            params.append(notes)
        
        if updates:
            params.append(trade_id)
            query = f"UPDATE trading_journal SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
        
        conn.close()
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open trades"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trading_journal WHERE status = 'open' ORDER BY entry_date")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_closed_trades(self, limit: Optional[int] = None) -> List[Dict]:
        """Get all closed trades"""
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM trading_journal WHERE status != 'open' ORDER BY exit_date DESC"
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_trade_statistics(self) -> Dict:
        """Calculate trading statistics"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get all closed trades with all columns
        cursor.execute("""
            SELECT symbol, entry_price, exit_price, quantity, status, entry_date, exit_date
            FROM trading_journal 
            WHERE status != 'open' AND exit_price IS NOT NULL
        """)
        closed_trades = cursor.fetchall()
        
        if not closed_trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'best_trade': None,
                'worst_trade': None,
                'avg_win': 0.0,
                'avg_loss': 0.0
            }
        
        # Calculate statistics
        total_trades = len(closed_trades)
        winning_trades = 0
        losing_trades = 0
        total_pnl = 0.0
        pnl_list = []
        best_trade = None
        worst_trade = None
        wins = []
        losses = []
        
        for trade in closed_trades:
            symbol = trade[0]
            entry_price = trade[1]
            exit_price = trade[2]
            quantity = trade[3]
            status = trade[4]
            entry_date = trade[5]
            exit_date = trade[6]
            
            pnl = (exit_price - entry_price) * quantity
            pnl_list.append(pnl)
            total_pnl += pnl
            
            trade_info = {
                'symbol': symbol,
                'pnl': pnl,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'entry_date': entry_date,
                'exit_date': exit_date,
                'status': status
            }
            
            if pnl > 0:
                winning_trades += 1
                wins.append(pnl)
                if best_trade is None or pnl > best_trade['pnl']:
                    best_trade = trade_info.copy()
            else:
                losing_trades += 1
                losses.append(pnl)
                if worst_trade is None or pnl < worst_trade['pnl']:
                    worst_trade = trade_info.copy()
        
        conn.close()
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0.0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / total_trades if total_trades > 0 else 0.0,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'avg_win': sum(wins) / len(wins) if wins else 0.0,
            'avg_loss': sum(losses) / len(losses) if losses else 0.0
        }
    
    # Signal history methods
    def save_signal(self, symbol: str, score: float, entry_price: Optional[float] = None,
                    stop_loss: Optional[float] = None, position_size: Optional[int] = None,
                    notes: str = ""):
        """Save generated signal"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signal_history 
            (symbol, signal_date, score, entry_price, stop_loss, position_size, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), datetime.now(), score, entry_price, stop_loss, position_size, notes))
        conn.commit()
        conn.close()
    
    def get_recent_signals(self, days: int = 7) -> List[Dict]:
        """Get recent signals"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM signal_history 
            WHERE signal_date >= datetime('now', '-' || ? || ' days')
            ORDER BY signal_date DESC
        """, (days,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Position monitoring methods
    def get_active_positions(self) -> List[Dict]:
        """Get all active positions (open trades)"""
        return self.get_open_trades()
    
    def get_position_stop(self, symbol: str) -> Optional[float]:
        """Get current stop loss for a position"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stop_loss FROM trading_journal 
            WHERE symbol = ? AND status = 'open'
            ORDER BY entry_date DESC LIMIT 1
        """, (symbol.upper(),))
        row = cursor.fetchone()
        conn.close()
        return row['stop_loss'] if row else None
    
    def _ensure_column_exists(self, conn: sqlite3.Connection, table: str, column: str, column_type: str):
        """Ensure a column exists in a table, add it if missing"""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info({})".format(table))
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        if column not in existing_columns:
            try:
                cursor.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, column_type))
                
                # If adding updated_at, initialize existing records
                if column == "updated_at" and table == "trading_journal":
                    # Try to use created_at if it exists, otherwise use CURRENT_TIMESTAMP
                    cursor.execute("""
                        UPDATE trading_journal 
                        SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                        WHERE updated_at IS NULL
                    """)
                    # Fallback for records without created_at
                    cursor.execute("""
                        UPDATE trading_journal 
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """)
                
                conn.commit()
                logger.info(f"Added column '{column}' to {table}")
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column '{column}' to {table}: {e}")
    
    def update_position_stop(self, symbol: str, new_stop: float, reason: str = ""):
        """Update stop loss for an active position"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Ensure columns exist
        self._ensure_column_exists(conn, "trading_journal", "current_stop_loss", "DOUBLE")
        self._ensure_column_exists(conn, "trading_journal", "updated_at", "TIMESTAMP")
        
        # Build update query - check if updated_at column exists
        cursor.execute("PRAGMA table_info(trading_journal)")
        columns = {row[1] for row in cursor.fetchall()}
        
        if 'updated_at' in columns:
            cursor.execute("""
                UPDATE trading_journal 
                SET current_stop_loss = ?, stop_loss = ?, 
                    notes = COALESCE(notes || '\n' || ?, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = ? AND status = 'open'
            """, (new_stop, new_stop, f"Stop updated: {reason}", reason, symbol.upper()))
        else:
            cursor.execute("""
                UPDATE trading_journal 
                SET current_stop_loss = ?, stop_loss = ?, 
                    notes = COALESCE(notes || '\n' || ?, ?)
                WHERE symbol = ? AND status = 'open'
            """, (new_stop, new_stop, f"Stop updated: {reason}", reason, symbol.upper()))
        
        conn.commit()
        conn.close()
    
    def close_position(self, symbol: str, exit_price: float, reason: str = ""):
        """Close a position"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Ensure columns exist
        self._ensure_column_exists(conn, "trading_journal", "updated_at", "TIMESTAMP")
        
        # Determine status based on reason
        if "target" in reason.lower() or "profit" in reason.lower():
            status = "target_reached"
        elif "stop" in reason.lower():
            status = "stopped"
        else:
            status = "closed"
        
        # Check if updated_at column exists
        cursor.execute("PRAGMA table_info(trading_journal)")
        columns = {row[1] for row in cursor.fetchall()}
        
        if 'updated_at' in columns:
            cursor.execute("""
                UPDATE trading_journal 
                SET exit_price = ?, exit_date = ?, status = ?,
                    notes = COALESCE(notes || '\n' || ?, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = ? AND status = 'open'
            """, (exit_price, datetime.now(), status, f"Closed: {reason}", reason, symbol.upper()))
        else:
            cursor.execute("""
                UPDATE trading_journal 
                SET exit_price = ?, exit_date = ?, status = ?,
                    notes = COALESCE(notes || '\n' || ?, ?)
                WHERE symbol = ? AND status = 'open'
            """, (exit_price, datetime.now(), status, f"Closed: {reason}", reason, symbol.upper()))
        
        conn.commit()
        conn.close()
        self.clear_alerts_for_symbol(symbol)
    
    def was_price_alert_sent(self, symbol: str, level_type: str) -> bool:
        """Check if we already sent this price alert for this symbol (evita ripetizioni)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM telegram_alert_sent WHERE symbol = ? AND level_type = ?",
            (symbol.upper(), level_type)
        )
        row = cursor.fetchone()
        conn.close()
        return row is not None
    
    def set_price_alert_sent(self, symbol: str, level_type: str):
        """Mark that we sent this price alert for this symbol."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO telegram_alert_sent (symbol, level_type, sent_at) VALUES (?, ?, ?)",
            (symbol.upper(), level_type, datetime.now())
        )
        conn.commit()
        conn.close()
    
    def clear_alerts_for_symbol(self, symbol: str):
        """Clear sent alerts for symbol (e.g. when position is closed)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telegram_alert_sent WHERE symbol = ?", (symbol.upper(),))
        conn.commit()
        conn.close()
    
    def delete_trade(self, trade_id: int) -> bool:
        """Delete a single trade by ID (for cleaning test data)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM trading_journal WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
        cursor.execute("DELETE FROM trading_journal WHERE id = ?", (trade_id,))
        conn.commit()
        conn.close()
        self.clear_alerts_for_symbol(row['symbol'])
        return True
    
    def delete_all_closed_trades(self) -> int:
        """Delete all closed trades (for cleaning test/prova data). Returns count deleted."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM trading_journal WHERE status != 'open'")
        symbols = {row['symbol'] for row in cursor.fetchall()}
        cursor.execute("DELETE FROM trading_journal WHERE status != 'open'")
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        for sym in symbols:
            self.clear_alerts_for_symbol(sym)
        return deleted
    
    def reset_all_trades(self) -> int:
        """Delete ALL trades (open and closed) for a complete reset. Returns count deleted."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM trading_journal")
        symbols = {row['symbol'] for row in cursor.fetchall()}
        cursor.execute("DELETE FROM trading_journal")
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        # Clear all alerts
        for sym in symbols:
            self.clear_alerts_for_symbol(sym)
        logger.info(f"Reset all trades: {deleted} trades deleted")
        return deleted
    
    # User settings methods
    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """Get user setting"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row['value'] if row else default
    
    def set_setting(self, key: str, value: str):
        """Set user setting"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, datetime.now()))
        conn.commit()
        conn.close()
    
    def analyze_trade_performance(self, trade_id: int) -> Dict:
        """
        Analyze why a trade performed well or poorly
        
        Returns:
            Dict with analysis results
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get trade details
        cursor.execute("SELECT * FROM trading_journal WHERE id = ?", (trade_id,))
        trade = cursor.fetchone()
        
        if not trade:
            conn.close()
            return {'error': 'Trade not found'}
        
        trade_dict = dict(trade)
        
        # Calculate P&L
        if trade_dict.get('exit_price') and trade_dict.get('entry_price'):
            pnl = (trade_dict['exit_price'] - trade_dict['entry_price']) * trade_dict['quantity']
            pnl_pct = ((trade_dict['exit_price'] - trade_dict['entry_price']) / trade_dict['entry_price']) * 100
            
            # Get commission cost
            commission_per_trade = 1.0  # Trade Republic
            total_commission = commission_per_trade * 2  # Entry + Exit
            net_pnl = pnl - total_commission
            
            # Calculate if target was reached
            target_reached = False
            if trade_dict.get('target_price'):
                target_reached = trade_dict['exit_price'] >= trade_dict['target_price']
            
            # Calculate if stop loss was hit
            stop_hit = False
            if trade_dict.get('stop_loss'):
                stop_hit = trade_dict['exit_price'] <= trade_dict['stop_loss']
            
            analysis = {
                'trade_id': trade_id,
                'symbol': trade_dict['symbol'],
                'pnl': pnl,
                'net_pnl': net_pnl,
                'pnl_pct': pnl_pct,
                'commission_cost': total_commission,
                'target_reached': target_reached,
                'stop_hit': stop_hit,
                'status': trade_dict.get('status', 'unknown'),
                'entry_price': trade_dict['entry_price'],
                'exit_price': trade_dict['exit_price'],
                'target_price': trade_dict.get('target_price'),
                'stop_loss': trade_dict.get('stop_loss'),
                'days_held': None
            }
            
            # Calculate days held
            if trade_dict.get('entry_date') and trade_dict.get('exit_date'):
                entry_date = pd.to_datetime(trade_dict['entry_date'])
                exit_date = pd.to_datetime(trade_dict['exit_date'])
                days_held = (exit_date - entry_date).days
                analysis['days_held'] = days_held
            
            conn.close()
            return analysis
        else:
            conn.close()
            return {'error': 'Trade not closed yet'}
    
    def close(self):
        """Close database connection (no-op for SQLite, connections are auto-closed)"""
        pass
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
        return False  # Don't suppress exceptions
