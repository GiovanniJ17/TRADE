"""
Paper Trading Mode
Simulazione trading in tempo reale senza rischio capitale

Enhanced per Code Review Issue #6:
- Slippage simulation (0.05% base + 0.05% spread + random)
- Commission modeling
- Spread cost simulation
- Trailing stop tracking
"""
import pandas as pd
import numpy as np
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger

from ..database.market_db import MarketDatabase
from ..database.user_db import UserDatabase
from ..core.portfolio_manager import PortfolioManager
from ..intelligence.risk_manager import RiskManager
from ..utils.config import config


class SlippageModel:
    """
    Realistic slippage simulation for paper trading.
    
    Per Code Review Issue #6:
    - Base slippage: 0.05% (market microstructure)
    - Spread cost: 0.05% (half the bid-ask spread)
    - Random variation: ±0.05%
    
    Total expected slippage: ~0.1-0.15% per trade
    """
    
    # Slippage parameters
    BASE_SLIPPAGE = 0.0005       # 0.05% base slippage
    SPREAD_COST = 0.0005        # 0.05% half-spread
    RANDOM_RANGE = 0.0005       # ±0.05% random variation
    
    # 15-minute data delay simulation (for Polygon free tier)
    DATA_DELAY_MINUTES = 15
    
    @classmethod
    def simulate_fill(cls, signal_price: float, direction: str = 'buy', 
                     volatility_factor: float = 1.0) -> Dict:
        """
        Simulate realistic fill price with slippage.
        
        Args:
            signal_price: The theoretical signal price
            direction: 'buy' or 'sell'
            volatility_factor: Multiplier for high-volatility stocks (1.0 = normal)
            
        Returns:
            Dict with fill_price, slippage_pct, slippage_components
        """
        # Calculate slippage components
        base_slip = cls.BASE_SLIPPAGE * volatility_factor
        spread_cost = cls.SPREAD_COST * volatility_factor
        random_factor = random.uniform(-cls.RANDOM_RANGE, cls.RANDOM_RANGE) * volatility_factor
        
        total_slippage = base_slip + spread_cost + random_factor
        
        # Apply direction (buy = pay more, sell = receive less)
        if direction.lower() == 'buy':
            fill_price = signal_price * (1 + total_slippage)
        else:
            fill_price = signal_price * (1 - total_slippage)
        
        return {
            'fill_price': round(fill_price, 4),
            'signal_price': signal_price,
            'slippage_pct': round(total_slippage * 100, 4),
            'slippage_usd': round(abs(fill_price - signal_price), 4),
            'direction': direction,
            'components': {
                'base': base_slip * 100,
                'spread': spread_cost * 100,
                'random': random_factor * 100
            }
        }
    
    @classmethod
    def estimate_slippage_cost(cls, trade_value_usd: float, 
                              num_trades: int = 1) -> Dict:
        """
        Estimate total slippage cost for a trading scenario.
        
        Args:
            trade_value_usd: Total trade value in USD
            num_trades: Number of round-trip trades
            
        Returns:
            Dict with estimated costs
        """
        # Average slippage per trade (one-way)
        avg_slippage = cls.BASE_SLIPPAGE + cls.SPREAD_COST
        
        # Round-trip slippage (entry + exit)
        round_trip_slippage = avg_slippage * 2
        
        # Total cost
        total_slippage_cost = trade_value_usd * round_trip_slippage * num_trades
        
        return {
            'avg_slippage_pct': avg_slippage * 100,
            'round_trip_slippage_pct': round_trip_slippage * 100,
            'total_slippage_cost_usd': round(total_slippage_cost, 2),
            'cost_per_trade_usd': round(total_slippage_cost / num_trades, 2) if num_trades > 0 else 0
        }


class PaperTrade:
    """Singolo trade in paper trading mode"""
    
    def __init__(
        self,
        symbol: str,
        entry_date: datetime,
        entry_price: float,
        stop_loss: float,
        target_price: Optional[float],
        quantity: int,
        risk_amount: float,
        score: float,
        signal_breakdown: Dict
    ):
        self.trade_id = f"{symbol}_{entry_date.strftime('%Y%m%d_%H%M%S')}"
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.current_stop = stop_loss  # For trailing stop
        self.target_price = target_price
        self.quantity = quantity
        self.risk_amount = risk_amount
        self.score = score
        self.signal_breakdown = signal_breakdown
        
        self.exit_date = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl_usd = 0.0
        self.pnl_eur = 0.0
        self.r_multiple = 0.0
        self.status = "OPEN"
        
        self.highest_price = entry_price
        self.days_held = 0
    
    def to_dict(self) -> Dict:
        """Converti a dictionary per serializzazione"""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_date": self.entry_date.isoformat(),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "current_stop": self.current_stop,
            "target_price": self.target_price,
            "quantity": self.quantity,
            "risk_amount": self.risk_amount,
            "score": self.score,
            "signal_breakdown": self.signal_breakdown,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl_usd": self.pnl_usd,
            "pnl_eur": self.pnl_eur,
            "r_multiple": self.r_multiple,
            "status": self.status,
            "highest_price": self.highest_price,
            "days_held": self.days_held
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PaperTrade':
        """Carica da dictionary"""
        trade = cls(
            symbol=data["symbol"],
            entry_date=pd.to_datetime(data["entry_date"]),
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            target_price=data.get("target_price"),
            quantity=data["quantity"],
            risk_amount=data["risk_amount"],
            score=data["score"],
            signal_breakdown=data.get("signal_breakdown", {})
        )
        
        trade.trade_id = data.get("trade_id", trade.trade_id)
        trade.current_stop = data.get("current_stop", data["stop_loss"])
        trade.exit_date = pd.to_datetime(data["exit_date"]) if data.get("exit_date") else None
        trade.exit_price = data.get("exit_price")
        trade.exit_reason = data.get("exit_reason")
        trade.pnl_usd = data.get("pnl_usd", 0.0)
        trade.pnl_eur = data.get("pnl_eur", 0.0)
        trade.r_multiple = data.get("r_multiple", 0.0)
        trade.status = data.get("status", "OPEN")
        trade.highest_price = data.get("highest_price", trade.entry_price)
        trade.days_held = data.get("days_held", 0)
        
        return trade


class PaperTradingEngine:
    """
    Engine per Paper Trading
    
    OBIETTIVO: Testare strategia in condizioni reali senza rischiare capitale
    
    Features:
    - Tracking posizioni simulate
    - Aggiornamento automatico trailing stops
    - Esecuzione virtuale di stop loss e target
    - Performance tracking real-time
    - Export risultati per analisi
    
    UTILIZZO:
    1. Attiva paper trading mode
    2. Sistema genera segnali come al solito
    3. "Esegui" trades virtualmente
    4. Sistema monitora posizioni e aggiorna stops
    5. Dopo 3-6 mesi, analizza performance
    6. Se positive → passa a capitale reale (piccolo)
    """
    
    def __init__(self, paper_trading_dir: Optional[Path] = None):
        self.db = MarketDatabase()
        self.user_db = UserDatabase()
        self.portfolio_mgr = PortfolioManager(user_db=self.user_db)
        
        # Directory per persistenza dati paper trading
        self.paper_dir = paper_trading_dir or Path("./data/paper_trading")
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        
        self.trades_file = self.paper_dir / "paper_trades.json"
        self.config_file = self.paper_dir / "paper_config.json"
        
        # Stato
        self.open_trades: List[PaperTrade] = []
        self.closed_trades: List[PaperTrade] = []
        self.initial_capital = 1500.0
        self.current_capital = 1500.0
        self.start_date = datetime.now()
        
        # Load existing trades if any
        self._load_state()
    
    def start_paper_trading(
        self,
        initial_capital: float = 1500.0,
        max_positions: int = 3,
        min_score: int = 6
    ):
        """Inizializza nuovo periodo di paper trading"""
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.start_date = datetime.now()
        self.open_trades = []
        self.closed_trades = []
        
        config_data = {
            "initial_capital": initial_capital,
            "max_positions": max_positions,
            "min_score": min_score,
            "start_date": self.start_date.isoformat(),
            "mode": "paper_trading"
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        logger.info(f"📝 Paper Trading Started: Capital={initial_capital}€, Max Positions={max_positions}")
        self._save_state()
    
    def get_new_signals(
        self,
        min_score: int = 6,
        symbols: Optional[List[str]] = None
    ) -> List[Dict]:
        """Genera nuovi segnali per paper trading usando PortfolioManager"""
        logger.info("Generating new signals for paper trading (PortfolioManager)...")

        portfolio = self.portfolio_mgr.generate_portfolio_signals(
            stock_symbols=symbols
        )
        signals = portfolio.get('stock_signals', [])

        # Filtra simboli già in posizione
        open_symbols = {t.symbol for t in self.open_trades}
        available_signals = [s for s in signals if s["symbol"] not in open_symbols]

        logger.info(f"Found {len(available_signals)} new signals (excluding {len(open_symbols)} open positions)")

        return available_signals
    
    def open_paper_trade(self, signal: Dict, apply_slippage: bool = True) -> PaperTrade:
        """
        Apri un trade virtuale da un segnale.
        
        Args:
            signal: Signal dict with entry_price, stop_loss, etc.
            apply_slippage: Whether to simulate realistic slippage (default True)
            
        Returns:
            PaperTrade object
        """
        signal_price = signal["entry_price"]
        
        # Apply slippage simulation for realistic paper trading
        if apply_slippage:
            fill_result = SlippageModel.simulate_fill(signal_price, direction='buy')
            actual_entry_price = fill_result['fill_price']
            slippage_info = fill_result
            logger.debug(f"{signal['symbol']}: Slippage applied - Signal ${signal_price:.2f} → Fill ${actual_entry_price:.2f} ({fill_result['slippage_pct']:.3f}%)")
        else:
            actual_entry_price = signal_price
            slippage_info = None
        
        trade = PaperTrade(
            symbol=signal["symbol"],
            entry_date=datetime.now(),
            entry_price=actual_entry_price,  # Use slipped price
            stop_loss=signal["stop_loss"],
            target_price=signal.get("target_price"),
            quantity=signal["position_size"],
            risk_amount=signal["risk_amount"],
            score=signal.get("score", 0),
            signal_breakdown=signal.get("breakdown", {})
        )
        
        # Store slippage info for analysis
        if slippage_info:
            trade.signal_breakdown['entry_slippage'] = slippage_info
        
        self.open_trades.append(trade)
        
        logger.info(f"✅ Paper Trade OPENED: {trade.symbol} @ ${trade.entry_price:.2f}")
        if apply_slippage and signal_price != actual_entry_price:
            logger.info(f"   Slippage: Signal ${signal_price:.2f} → Fill ${actual_entry_price:.2f}")
        logger.info(f"   Stop: ${trade.stop_loss:.2f}, Target: ${trade.target_price:.2f if trade.target_price else 0:.2f}")
        logger.info(f"   Quantity: {trade.quantity}, Risk: {trade.risk_amount:.2f}€")
        
        self._save_state()
        return trade
    
    def check_and_update_positions(self) -> List[Dict]:
        """
        Controlla posizioni aperte e aggiorna:
        - Stop loss hit
        - Target hit
        - Trailing stop updates
        
        Returns:
            Lista di eventi (stop hit, target hit, trailing update)
        """
        events = []
        
        for trade in list(self.open_trades):
            try:
                # Ottieni prezzo corrente
                df = self.db.get_data(
                    trade.symbol,
                    start_date=datetime.now() - timedelta(days=5),
                    end_date=datetime.now()
                )
                
                if df.empty:
                    logger.debug(f"No recent data for {trade.symbol}")
                    continue
                
                latest = df.iloc[-1]
                current_price = float(latest["close"])
                current_high = float(latest["high"])
                current_low = float(latest["low"])
                
                # Update days held
                trade.days_held = (datetime.now() - trade.entry_date).days
                
                # Update highest price
                if current_high > trade.highest_price:
                    trade.highest_price = current_high
                
                # Check Stop Loss Hit
                if current_low <= trade.current_stop:
                    self._close_trade(
                        trade,
                        exit_price=trade.current_stop,
                        exit_reason="stop_loss",
                        exit_date=datetime.now()
                    )
                    events.append({
                        "type": "STOP_HIT",
                        "symbol": trade.symbol,
                        "exit_price": trade.current_stop,
                        "pnl_eur": trade.pnl_eur
                    })
                    continue
                
                # Check Target Hit
                if trade.target_price and current_high >= trade.target_price:
                    self._close_trade(
                        trade,
                        exit_price=trade.target_price,
                        exit_reason="target_reached",
                        exit_date=datetime.now()
                    )
                    events.append({
                        "type": "TARGET_HIT",
                        "symbol": trade.symbol,
                        "exit_price": trade.target_price,
                        "pnl_eur": trade.pnl_eur
                    })
                    continue
                
                # Update Trailing Stop (if in profit)
                if current_price > trade.entry_price * 1.05:  # At least 5% profit
                    atr = float(latest.get("atr", 0)) if "atr" in latest else None
                    
                    if atr and atr > 0:
                        new_stop = RiskManager.calculate_trailing_stop(
                            current_price,
                            atr,
                            trade.highest_price
                        )
                        
                        if new_stop > trade.current_stop:
                            old_stop = trade.current_stop
                            trade.current_stop = new_stop
                            events.append({
                                "type": "TRAILING_STOP_UPDATE",
                                "symbol": trade.symbol,
                                "old_stop": old_stop,
                                "new_stop": new_stop,
                                "current_price": current_price
                            })
                            logger.info(f"🔄 Trailing Stop Updated: {trade.symbol} ${old_stop:.2f} → ${new_stop:.2f}")
            
            except Exception as e:
                logger.error(f"Error checking position {trade.symbol}: {e}")
        
        if events:
            self._save_state()
        
        return events
    
    def _close_trade(
        self,
        trade: PaperTrade,
        exit_price: float,
        exit_reason: str,
        exit_date: datetime,
        apply_slippage: bool = True
    ):
        """
        Chiudi un trade virtuale con realistic slippage.
        
        Args:
            trade: The PaperTrade to close
            exit_price: Target exit price (before slippage)
            exit_reason: Reason for exit (stop_loss, target_reached, manual, etc.)
            exit_date: Exit timestamp
            apply_slippage: Whether to simulate exit slippage
        """
        signal_exit_price = exit_price
        
        # Apply slippage on exit (selling)
        if apply_slippage:
            fill_result = SlippageModel.simulate_fill(exit_price, direction='sell')
            actual_exit_price = fill_result['fill_price']
            slippage_info = fill_result
            logger.debug(f"{trade.symbol}: Exit slippage - Target ${exit_price:.2f} → Fill ${actual_exit_price:.2f} ({fill_result['slippage_pct']:.3f}%)")
        else:
            actual_exit_price = exit_price
            slippage_info = None
        
        trade.exit_date = exit_date
        trade.exit_price = actual_exit_price  # Use slipped price
        trade.exit_reason = exit_reason
        trade.status = "CLOSED"
        
        # Store exit slippage info
        if slippage_info:
            trade.signal_breakdown['exit_slippage'] = slippage_info
        
        # Calcola P&L with realistic costs
        from ..utils.currency import get_exchange_rate
        rate = get_exchange_rate(user_db=self.user_db)  # Dynamic rate from DB/API
        
        trade.pnl_usd = (actual_exit_price - trade.entry_price) * trade.quantity
        
        # Costs: Commission + FX cost
        commission = 2.0  # €1 entry + €1 exit on Trade Republic
        fx_cost = abs(trade.pnl_usd * rate) * 0.0025  # 0.25% FX cost
        
        trade.pnl_eur = (trade.pnl_usd * rate) - commission - fx_cost
        
        # Track costs for analysis
        trade.signal_breakdown['costs'] = {
            'commission_eur': commission,
            'fx_cost_eur': round(fx_cost, 2),
            'total_costs_eur': round(commission + fx_cost, 2)
        }
        
        # R-multiple
        if trade.risk_amount > 0:
            trade.r_multiple = trade.pnl_eur / trade.risk_amount
        
        # Update capital
        self.current_capital += trade.pnl_eur
        
        # Move to closed
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        
        logger.info(f"❌ Paper Trade CLOSED: {trade.symbol} @ ${actual_exit_price:.2f}")
        if apply_slippage and signal_exit_price != actual_exit_price:
            logger.info(f"   Slippage: Target ${signal_exit_price:.2f} → Fill ${actual_exit_price:.2f}")
        logger.info(f"   Reason: {exit_reason}, P&L: {trade.pnl_eur:+.2f}€ ({trade.r_multiple:+.2f}R)")
        logger.info(f"   Costs: Commission €{commission:.2f}, FX €{fx_cost:.2f}")
        logger.info(f"   Days held: {trade.days_held}, Capital: {self.current_capital:.2f}€")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Ottieni summary performance paper trading"""
        
        if not self.closed_trades:
            return {
                "error": "No closed trades yet",
                "open_positions": len(self.open_trades),
                "current_capital": self.current_capital
            }
        
        trades_df = pd.DataFrame([t.to_dict() for t in self.closed_trades])
        
        # Basic metrics
        total_trades = len(trades_df)
        winners = trades_df[trades_df["pnl_eur"] > 0]
        losers = trades_df[trades_df["pnl_eur"] <= 0]
        
        win_rate = (len(winners) / total_trades) * 100 if total_trades > 0 else 0
        
        gross_profit = winners["pnl_eur"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl_eur"].sum()) if len(losers) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss
        
        total_pnl = trades_df["pnl_eur"].sum()
        total_return_pct = ((self.current_capital - self.initial_capital) / self.initial_capital) * 100
        
        avg_r = trades_df["r_multiple"].mean()
        
        # Time analysis
        days_running = (datetime.now() - self.start_date).days
        
        # Sharpe ratio (simplified)
        returns = trades_df["pnl_eur"].values / self.initial_capital
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Max Drawdown
        cumulative_pnl = trades_df["pnl_eur"].cumsum().values
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = cumulative_pnl - running_max
        max_dd = drawdown.min()
        max_dd_pct = (max_dd / self.initial_capital) * 100
        
        return {
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "days_running": days_running,
            "initial_capital": self.initial_capital,
            "current_capital": round(self.current_capital, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "open_positions": len(self.open_trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_r_multiple": round(avg_r, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_eur": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "best_trade": round(trades_df["pnl_eur"].max(), 2),
            "worst_trade": round(trades_df["pnl_eur"].min(), 2),
            "avg_win": round(winners["pnl_eur"].mean(), 2) if len(winners) > 0 else 0,
            "avg_loss": round(losers["pnl_eur"].mean(), 2) if len(losers) > 0 else 0,
            "avg_days_held": round(trades_df["days_held"].mean(), 1),
            "is_ready_for_live": self._assess_readiness_for_live()
        }
    
    def _assess_readiness_for_live(self) -> Dict[str, Any]:
        """
        Valuta se il sistema è pronto per trading con capitale reale
        
        Criteri:
        - Minimo 20 trades
        - Win rate > 40%
        - Profit factor > 1.3
        - Sharpe > 0.8
        - Max DD < -20%
        - Almeno 3 mesi di testing
        """
        if len(self.closed_trades) < 20:
            return {
                "ready": False,
                "reason": f"Insufficienti trades ({len(self.closed_trades)}/20 minimi)",
                "recommendation": "Continua paper trading"
            }
        
        summary = self.get_performance_summary()
        
        days_running = summary["days_running"]
        win_rate = summary["win_rate"]
        profit_factor = summary["profit_factor"]
        sharpe = summary["sharpe_ratio"]
        max_dd_pct = summary["max_drawdown_pct"]
        total_return = summary["total_return_pct"]
        
        checks = []
        score = 0
        
        # Check 1: Durata testing
        if days_running >= 90:
            checks.append("✅ Durata sufficiente (>=3 mesi)")
            score += 2
        elif days_running >= 60:
            checks.append("⚠️ Durata media (>=2 mesi)")
            score += 1
        else:
            checks.append(f"❌ Durata insufficiente ({days_running} giorni < 90)")
        
        # Check 2: Win rate
        if win_rate >= 45:
            checks.append(f"✅ Win rate eccellente ({win_rate:.1f}%)")
            score += 2
        elif win_rate >= 40:
            checks.append(f"✅ Win rate buono ({win_rate:.1f}%)")
            score += 1
        else:
            checks.append(f"❌ Win rate basso ({win_rate:.1f}%)")
        
        # Check 3: Profit factor
        if profit_factor >= 1.5:
            checks.append(f"✅ Profit factor eccellente ({profit_factor:.2f})")
            score += 2
        elif profit_factor >= 1.3:
            checks.append(f"✅ Profit factor buono ({profit_factor:.2f})")
            score += 1
        else:
            checks.append(f"❌ Profit factor insufficiente ({profit_factor:.2f})")
        
        # Check 4: Sharpe ratio
        if sharpe >= 1.0:
            checks.append(f"✅ Sharpe eccellente ({sharpe:.2f})")
            score += 2
        elif sharpe >= 0.8:
            checks.append(f"✅ Sharpe buono ({sharpe:.2f})")
            score += 1
        else:
            checks.append(f"❌ Sharpe basso ({sharpe:.2f})")
        
        # Check 5: Max Drawdown
        if max_dd_pct > -15:
            checks.append(f"✅ Max DD controllato ({max_dd_pct:.1f}%)")
            score += 2
        elif max_dd_pct > -20:
            checks.append(f"⚠️ Max DD accettabile ({max_dd_pct:.1f}%)")
            score += 1
        else:
            checks.append(f"❌ Max DD eccessivo ({max_dd_pct:.1f}%)")
        
        # Decision
        ready = score >= 7  # Su 10 possibili
        
        if ready:
            recommendation = "✅ SISTEMA PRONTO per live trading con capitale piccolo (10-20% del capitale totale)"
        elif score >= 5:
            recommendation = "⚠️ Sistema promettente ma necessita più testing (1-2 mesi aggiuntivi)"
        else:
            recommendation = "❌ Sistema NON pronto. Rivedi strategia, filtri o parametri"
        
        return {
            "ready": ready,
            "score": score,
            "max_score": 10,
            "checks": checks,
            "recommendation": recommendation,
            "suggested_live_capital": round(self.initial_capital * 0.15, 2) if ready else 0
        }
    
    def export_trades_to_csv(self, filename: Optional[str] = None) -> str:
        """Esporta tutti i trades in CSV per analisi"""
        if filename is None:
            filename = self.paper_dir / f"paper_trades_{datetime.now().strftime('%Y%m%d')}.csv"
        
        all_trades = self.closed_trades + self.open_trades
        trades_df = pd.DataFrame([t.to_dict() for t in all_trades])
        
        trades_df.to_csv(filename, index=False)
        logger.info(f"📊 Trades exported to: {filename}")
        
        return str(filename)
    
    def _save_state(self):
        """Salva stato corrente su disco"""
        state = {
            "initial_capital": self.initial_capital,
            "current_capital": self.current_capital,
            "start_date": self.start_date.isoformat(),
            "open_trades": [t.to_dict() for t in self.open_trades],
            "closed_trades": [t.to_dict() for t in self.closed_trades]
        }
        
        with open(self.trades_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self):
        """Carica stato da disco"""
        if not self.trades_file.exists():
            return
        
        try:
            with open(self.trades_file, 'r') as f:
                state = json.load(f)
            
            self.initial_capital = state.get("initial_capital", 1500.0)
            self.current_capital = state.get("current_capital", 1500.0)
            self.start_date = pd.to_datetime(state.get("start_date", datetime.now()))
            
            self.open_trades = [PaperTrade.from_dict(t) for t in state.get("open_trades", [])]
            self.closed_trades = [PaperTrade.from_dict(t) for t in state.get("closed_trades", [])]
            
            logger.info(f"📂 Loaded paper trading state: {len(self.open_trades)} open, {len(self.closed_trades)} closed")
        
        except Exception as e:
            logger.error(f"Error loading paper trading state: {e}")
    
    def close(self):
        """Cleanup"""
        self._save_state()
        self.db.close()
        self.portfolio_mgr.close()
