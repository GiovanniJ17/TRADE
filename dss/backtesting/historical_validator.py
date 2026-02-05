"""Historical validation: backtest strategy on past data (no look-ahead)."""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger

from ..database.market_db import MarketDatabase
from ..intelligence.signal_generator import SignalGenerator
from ..utils.config import config
from ..utils.currency import get_exchange_rate


class HistoricalValidator:
    """Validate strategy on historical data (day-by-day simulation)."""

    def __init__(self):
        self.db = MarketDatabase()
        self.signal_gen = SignalGenerator()
        self.user_db = None  # optional, for exchange rate
        self._cached_rate = None  # Cache rate for session

    def _get_rate(self) -> float:
        """Get exchange rate dynamically (cached for session)."""
        if self._cached_rate is None:
            if self.user_db is None:
                try:
                    from ..database.user_db import UserDatabase
                    self.user_db = UserDatabase()
                except Exception:
                    pass
            self._cached_rate = get_exchange_rate(user_db=self.user_db, config=config)
        return self._cached_rate

    def run_historical_simulation(
        self,
        start_date: str,
        end_date: str,
        symbols: Optional[List[str]] = None,
        min_score: int = 6,
        max_positions: int = 3,
        initial_capital: float = 1500.0,
        step_days: int = 7,
    ) -> Dict[str, Any]:
        """
        Simulate trading on historical data (no look-ahead).

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            symbols: Symbols to trade (None = all in DB)
            min_score: Minimum score for signals
            max_positions: Max open positions at once
            initial_capital: Starting capital (EUR)
            step_days: Generate new signals every N days (1=every day, 7=weekly; larger = faster)

        Returns:
            Dict with trades, equity_curve, metrics, final_capital, total_return_pct
        """
        rate = self._get_rate()
        self._cached_rate = rate  # Allow override for testing

        start = pd.to_datetime(start_date).normalize()
        end = pd.to_datetime(end_date).normalize()

        if symbols is None:
            symbols = self.db.get_all_symbols()
        if not symbols:
            return {
                "trades": [],
                "equity_curve": [],
                "metrics": {"error": "No symbols", "total_trades": 0},
                "final_capital": initial_capital,
                "total_return_pct": 0.0,
            }

        total_days = (end - start).days + 1
        logger.info(
            f"Historical simulation: {start.date()} to {end.date()}, symbols={len(symbols)}, "
            f"step_days={step_days} (~{total_days // max(1, step_days)} signal runs)"
        )

        trades: List[Dict] = []
        current_positions: List[Dict] = []
        equity_curve: List[Dict] = []
        current_capital = initial_capital
        current_date = start
        day_index = 0
        log_every = max(1, total_days // 10)  # log progress ~10 times

        while current_date <= end:
            try:
                # 1) Check open positions for stop/target using that day's OHLC
                for pos in list(current_positions):
                    outcome = self._check_position_outcome(pos, current_date)
                    if outcome is not None:
                        trades.append(outcome)
                        current_positions.remove(pos)
                        current_capital += outcome["pnl_eur"]

                # 2) New entries: signals as of this date (only every step_days to save time)
                available_slots = max_positions - len(current_positions)
                if available_slots > 0 and (day_index % step_days == 0):
                    signals = self.signal_gen.generate_signals_as_of(
                        pd.Timestamp(current_date), symbols=symbols, min_score=min_score
                    )
                    for sig in signals[:available_slots]:
                        if any(p["symbol"] == sig["symbol"] for p in current_positions):
                            continue
                        position = self._open_position(sig, current_date)
                        current_positions.append(position)

                # 3) Equity snapshot (after exits and entries)
                total_risk = sum(p.get("risk_amount", 0) for p in current_positions)
                equity_curve.append({
                    "date": current_date,
                    "capital": current_capital,
                    "open_positions": len(current_positions),
                    "total_risk": total_risk,
                })

                if day_index > 0 and day_index % log_every == 0:
                    logger.info(
                        f"Backtest progress: day {day_index}/{total_days} ({current_date.date()}), "
                        f"trades={len(trades)}, capital=€{current_capital:.0f}"
                    )
            except Exception as e:
                logger.error(f"Simulation error at {current_date}: {e}")
            current_date += timedelta(days=1)
            day_index += 1

        # Force-close remaining positions at end
        for pos in current_positions:
            outcome = self._force_close_position(pos, end)
            trades.append(outcome)
            current_capital += outcome["pnl_eur"]

        metrics = self._calculate_performance_metrics(
            trades, equity_curve, initial_capital
        )

        total_return_pct = ((current_capital - initial_capital) / initial_capital) * 100

        return {
            "trades": trades,
            "equity_curve": equity_curve,
            "metrics": metrics,
            "final_capital": current_capital,
            "total_return_pct": total_return_pct,
        }

    def _check_position_outcome(self, position: Dict, current_date: datetime) -> Optional[Dict]:
        """Check if position hit stop or target on current_date. Returns outcome dict or None."""
        symbol = position["symbol"]
        try:
            df = self.db.get_data_for_date(symbol, current_date)
            if df.empty:
                return None
            row = df.iloc[0]
            high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        except Exception as e:
            logger.debug(f"No data for {symbol} on {current_date}: {e}")
            return None

        entry_price = position["entry_price"]
        stop_loss = position["stop_loss"]
        target_price = position.get("target_price")
        quantity = position["quantity"]
        risk_amount = position.get("risk_amount", 0)

        # Stop hit (intraday: low <= stop)
        if low <= stop_loss:
            pnl_usd = (stop_loss - entry_price) * quantity
            pnl_eur = pnl_usd * self._get_rate() - 2.0  # commission
            return {
                "symbol": symbol,
                "entry_date": position["entry_date"],
                "entry_price": entry_price,
                "exit_date": current_date,
                "exit_price": stop_loss,
                "exit_reason": "stop_loss",
                "quantity": quantity,
                "pnl_usd": pnl_usd,
                "pnl_eur": pnl_eur,
                "r_multiple": -1.0,
                "risk_amount": risk_amount,
            }

        # Target hit
        if target_price and high >= target_price:
            pnl_usd = (target_price - entry_price) * quantity
            pnl_eur = pnl_usd * self._get_rate() - 2.0
            r_mult = (pnl_eur / risk_amount) if risk_amount and risk_amount > 0 else 0
            return {
                "symbol": symbol,
                "entry_date": position["entry_date"],
                "entry_price": entry_price,
                "exit_date": current_date,
                "exit_price": target_price,
                "exit_reason": "target",
                "quantity": quantity,
                "pnl_usd": pnl_usd,
                "pnl_eur": pnl_eur,
                "r_multiple": r_mult,
                "risk_amount": risk_amount,
            }
        return None

    def _open_position(self, signal: Dict, entry_date: datetime) -> Dict:
        """Build position dict from signal (entry = close of entry_date)."""
        return {
            "symbol": signal["symbol"],
            "entry_date": entry_date,
            "entry_price": signal["entry_price"],
            "stop_loss": signal["stop_loss"],
            "target_price": signal.get("target_price"),
            "quantity": signal["position_size"],
            "risk_amount": signal.get("risk_amount", 0),
            "score": signal.get("score"),
        }

    def _force_close_position(self, position: Dict, exit_date: datetime) -> Dict:
        """Close position at exit_date close (end of backtest)."""
        symbol = position["symbol"]
        try:
            df = self.db.get_data_for_date(symbol, exit_date)
            exit_price = float(df.iloc[0]["close"]) if not df.empty else position["entry_price"]
        except Exception:
            exit_price = position["entry_price"]

        pnl_usd = (exit_price - position["entry_price"]) * position["quantity"]
        pnl_eur = pnl_usd * self._get_rate() - 2.0
        risk_amount = position.get("risk_amount", 1.0)
        r_mult = (pnl_eur / risk_amount) if risk_amount else 0

        return {
            "symbol": symbol,
            "entry_date": position["entry_date"],
            "entry_price": position["entry_price"],
            "exit_date": exit_date,
            "exit_price": exit_price,
            "exit_reason": "forced_close",
            "quantity": position["quantity"],
            "pnl_usd": pnl_usd,
            "pnl_eur": pnl_eur,
            "r_multiple": r_mult,
            "risk_amount": risk_amount,
        }

    def _calculate_performance_metrics(
        self,
        trades: List[Dict],
        equity_curve: List[Dict],
        initial_capital: float,
    ) -> Dict[str, Any]:
        """Compute win rate, profit factor, max drawdown, Sharpe, etc."""
        if not trades:
            return {
                "error": "No trades executed",
                "total_trades": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_r_multiple": 0,
                "max_drawdown": 0,
                "max_drawdown_pct": 0,
                "total_return_pct": 0,
                "sharpe_ratio": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0,
            }

        df = pd.DataFrame(trades)
        pnl_eur = df["pnl_eur"].values

        winners = df[df["pnl_eur"] > 0]
        losers = df[df["pnl_eur"] <= 0]
        win_rate = (len(winners) / len(df)) * 100
        gross_profit = winners["pnl_eur"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl_eur"].sum()) if len(losers) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss
        avg_r = df["r_multiple"].mean()
        avg_win = winners["pnl_eur"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl_eur"].mean() if len(losers) > 0 else 0
        total_pnl = df["pnl_eur"].sum()
        total_return_pct = (total_pnl / initial_capital) * 100

        # Equity curve drawdown
        eq = pd.DataFrame(equity_curve)
        if not eq.empty and "capital" in eq.columns:
            eq["cumulative_pnl"] = eq["capital"] - initial_capital
            eq["peak"] = eq["capital"].cummax()
            eq["drawdown"] = eq["capital"] - eq["peak"]
            max_dd = eq["drawdown"].min()
            max_dd_pct = (max_dd / initial_capital) * 100
        else:
            cum = np.cumsum(pnl_eur)
            peak = np.maximum.accumulate(cum)
            max_dd = (cum - peak).min()
            max_dd_pct = (max_dd / initial_capital) * 100

        # Sharpe (simplified: per-trade returns)
        rets = pnl_eur / initial_capital
        sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if rets.std() > 0 else 0

        # Consecutive wins/losses
        is_win = df["pnl_eur"] > 0
        streak = (is_win != is_win.shift()).cumsum()
        win_streaks = df[is_win].groupby(streak[is_win]).size()
        loss_streaks = df[~is_win].groupby(streak[~is_win]).size()
        max_cw = int(win_streaks.max()) if len(win_streaks) > 0 else 0
        max_cl = int(loss_streaks.max()) if len(loss_streaks) > 0 else 0

        return {
            "total_trades": len(df),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": round(win_rate, 2),
            "avg_r_multiple": round(avg_r, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown": round(float(max_dd), 2),
            "max_drawdown_pct": round(float(max_dd_pct), 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_consecutive_wins": max_cw,
            "max_consecutive_losses": max_cl,
            "best_trade": round(df["pnl_eur"].max(), 2),
            "worst_trade": round(df["pnl_eur"].min(), 2),
        }

    def close(self):
        """Release resources."""
        self.db.close()
        self.signal_gen.close()
