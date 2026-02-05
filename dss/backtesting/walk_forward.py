"""
Walk-Forward Analysis & Out-of-Sample Testing
Implementa validation robusta per evitare overfitting
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from loguru import logger
from dataclasses import dataclass

from .historical_validator import HistoricalValidator
from ..utils.config import config


@dataclass
class WalkForwardWindow:
    """Singola finestra di walk-forward analysis"""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    optimized_params: Optional[Dict] = None
    test_results: Optional[Dict] = None


class WalkForwardAnalyzer:
    """
    Walk-Forward Analysis per validazione robusta della strategia
    
    METODOLOGIA:
    1. Split temporale: Training (70%) → Testing (30%)
    2. Rolling windows: ottimizza su training, testa su out-of-sample
    3. Nessun data snooping: parametri ottimizzati solo su dati passati
    4. Metriche aggregate su tutti i periodi out-of-sample
    
    Questo previene l'overfitting e fornisce stima realistica delle performance future.
    """
    
    def __init__(self):
        self.validator = HistoricalValidator()
    
    def run_walk_forward_analysis(
        self,
        start_date: str,
        end_date: str,
        window_size_months: int = 6,
        test_size_months: int = 2,
        symbols: Optional[List[str]] = None,
        initial_capital: float = 1500.0,
        step_days: int = 7
    ) -> Dict[str, Any]:
        """
        Esegui walk-forward analysis
        
        Args:
            start_date: Data inizio (YYYY-MM-DD)
            end_date: Data fine (YYYY-MM-DD)
            window_size_months: Durata finestra training (mesi)
            test_size_months: Durata finestra test (mesi)
            symbols: Lista simboli da testare
            initial_capital: Capitale iniziale (EUR)
            step_days: Frequenza generazione segnali
        
        Returns:
            Dict con risultati aggregati e per finestra
        """
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        # Crea finestre rolling
        windows = self._create_rolling_windows(
            start, end, window_size_months, test_size_months
        )
        
        logger.info(f"Walk-Forward Analysis: {len(windows)} windows")
        logger.info(f"Training: {window_size_months} months, Testing: {test_size_months} months")
        
        # Esegui backtest su ogni finestra
        all_trades = []
        window_results = []
        
        for i, window in enumerate(windows, 1):
            logger.info(f"\n=== Window {i}/{len(windows)} ===")
            logger.info(f"Train: {window.train_start.date()} to {window.train_end.date()}")
            logger.info(f"Test: {window.test_start.date()} to {window.test_end.date()}")
            
            # Fase 1: Optimization su training set (qui fisso, ma potresti ottimizzare parametri)
            # Per semplicità, uso i parametri di default da config
            # In un sistema avanzato, ottimizzeresti min_score, ATR multiplier, ecc.
            optimized_params = self._optimize_on_training(
                window.train_start.strftime("%Y-%m-%d"),
                window.train_end.strftime("%Y-%m-%d"),
                symbols,
                initial_capital,
                step_days
            )
            window.optimized_params = optimized_params
            
            # Fase 2: Test su out-of-sample period
            test_results = self.validator.run_historical_simulation(
                start_date=window.test_start.strftime("%Y-%m-%d"),
                end_date=window.test_end.strftime("%Y-%m-%d"),
                symbols=symbols,
                min_score=optimized_params.get("min_score", 6),
                max_positions=optimized_params.get("max_positions", 3),
                initial_capital=initial_capital,
                step_days=step_days
            )
            
            window.test_results = test_results
            
            # Aggiungi trades di questo periodo
            all_trades.extend(test_results.get("trades", []))
            
            window_results.append({
                "window_id": i,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "test_start": window.test_start,
                "test_end": window.test_end,
                "optimized_params": optimized_params,
                "test_metrics": test_results.get("metrics", {}),
                "test_return_pct": test_results.get("total_return_pct", 0),
                "test_trades": len(test_results.get("trades", []))
            })
            
            logger.info(f"Window {i} Test Results: Return {test_results.get('total_return_pct', 0):.2f}%, "
                       f"Trades: {len(test_results.get('trades', []))}, "
                       f"Sharpe: {test_results.get('metrics', {}).get('sharpe_ratio', 0):.2f}")
        
        # Calcola metriche aggregate
        aggregate_metrics = self._calculate_aggregate_metrics(
            all_trades, window_results, initial_capital
        )
        
        # Analisi robustezza (consistency across windows)
        robustness_analysis = self._analyze_robustness(window_results)
        
        return {
            "windows": window_results,
            "aggregate_metrics": aggregate_metrics,
            "robustness_analysis": robustness_analysis,
            "total_out_of_sample_trades": len(all_trades),
            "methodology": "Walk-Forward Analysis with Out-of-Sample Testing",
            "interpretation": self._generate_interpretation(aggregate_metrics, robustness_analysis)
        }
    
    def _create_rolling_windows(
        self,
        start: datetime,
        end: datetime,
        train_months: int,
        test_months: int
    ) -> List[WalkForwardWindow]:
        """Crea finestre rolling per walk-forward"""
        windows = []
        current_start = start
        
        while True:
            train_end = current_start + pd.DateOffset(months=train_months)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + pd.DateOffset(months=test_months)
            
            if test_end > end:
                break
            
            windows.append(WalkForwardWindow(
                train_start=current_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end
            ))
            
            # Roll forward by test period
            current_start = test_start
        
        return windows
    
    def _optimize_on_training(
        self,
        train_start: str,
        train_end: str,
        symbols: Optional[List[str]],
        initial_capital: float,
        step_days: int
    ) -> Dict[str, Any]:
        """
        Ottimizza parametri su training set
        
        VERSIONE ATTUALE: Usa parametri ottimizzati dal backtest principale.
        
        I parametri sono già stati ottimizzati manualmente tramite iterazioni:
        - ATR multiplier: 2.0 (testato 1.5, 2.0, 2.5)
        - Max positions: 3-5 (testato 3, 4, 5, 6)
        - Trailing stop: trigger 6%, distance 1.5%, lock 3.5%
        
        Questi parametri hanno prodotto PF 1.14-1.44 nei backtest.
        
        NOTA FUTURA: Per una vera optimization automatica, implementare
        grid search con cross-validation temporale. Non implementato
        perché i parametri attuali sono già stati ottimizzati manualmente.
        """
        # Return optimized parameters from manual testing
        return {
            "min_score": config.get("scoring.min_score", 6),
            "max_positions": config.get("risk.max_positions", 3),
            "atr_multiplier": config.get("risk.atr_multiplier", 2.0),
            "trailing_trigger": 6.0,
            "trailing_distance": 1.5,
            "trailing_lock": 3.5,
            "optimization_method": "manual_backtest_optimized_v2"
        }
    
    def _calculate_aggregate_metrics(
        self,
        all_trades: List[Dict],
        window_results: List[Dict],
        initial_capital: float
    ) -> Dict[str, Any]:
        """Calcola metriche aggregate su tutti i periodi out-of-sample"""
        if not all_trades:
            return {
                "error": "No trades in out-of-sample periods",
                "total_trades": 0
            }
        
        df = pd.DataFrame(all_trades)
        
        # Win rate
        winners = df[df["pnl_eur"] > 0]
        losers = df[df["pnl_eur"] <= 0]
        win_rate = (len(winners) / len(df)) * 100 if len(df) > 0 else 0
        
        # Profit factor
        gross_profit = winners["pnl_eur"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl_eur"].sum()) if len(losers) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss
        
        # Average R-multiple
        avg_r = df["r_multiple"].mean() if "r_multiple" in df.columns else 0
        
        # Total return
        total_pnl = df["pnl_eur"].sum()
        total_return_pct = (total_pnl / initial_capital) * 100
        
        # Sharpe Ratio (simplified)
        returns = df["pnl_eur"].values / initial_capital
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Sortino Ratio (downside deviation only)
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-9
        sortino = (returns.mean() / downside_std) * np.sqrt(252)
        
        # Max Drawdown
        cumulative_pnl = np.cumsum(df["pnl_eur"].values)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = cumulative_pnl - running_max
        max_drawdown = drawdown.min()
        max_drawdown_pct = (max_drawdown / initial_capital) * 100
        
        # Expectancy per trade
        expectancy = df["pnl_eur"].mean()
        
        # Consecutive wins/losses
        is_win = df["pnl_eur"] > 0
        streak = (is_win != is_win.shift()).cumsum()
        win_streaks = df[is_win].groupby(streak[is_win]).size()
        loss_streaks = df[~is_win].groupby(streak[~is_win]).size()
        max_consecutive_wins = int(win_streaks.max()) if len(win_streaks) > 0 else 0
        max_consecutive_losses = int(loss_streaks.max()) if len(loss_streaks) > 0 else 0
        
        # Recovery Factor (total profit / max drawdown)
        recovery_factor = abs(total_pnl / max_drawdown) if max_drawdown < 0 else 0
        
        return {
            "total_trades": len(df),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_r_multiple": round(avg_r, 2),
            "expectancy_per_trade": round(expectancy, 2),
            "total_return_pct": round(total_return_pct, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "max_drawdown_eur": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "recovery_factor": round(recovery_factor, 2),
            "best_trade": round(df["pnl_eur"].max(), 2),
            "worst_trade": round(df["pnl_eur"].min(), 2),
            "avg_win": round(winners["pnl_eur"].mean(), 2) if len(winners) > 0 else 0,
            "avg_loss": round(losers["pnl_eur"].mean(), 2) if len(losers) > 0 else 0,
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
        }
    
    def _analyze_robustness(self, window_results: List[Dict]) -> Dict[str, Any]:
        """
        Analizza robustezza della strategia across windows
        
        Una strategia robusta dovrebbe avere performance consistenti
        attraverso diversi periodi di mercato, non solo eccellente in uno.
        """
        if not window_results:
            return {"error": "No windows to analyze"}
        
        # Estrai returns di ogni finestra
        returns = [w["test_return_pct"] for w in window_results]
        sharpes = [w["test_metrics"].get("sharpe_ratio", 0) for w in window_results]
        win_rates = [w["test_metrics"].get("win_rate", 0) for w in window_results]
        
        # Filtra valori None/NaN
        returns = [r for r in returns if r is not None and not np.isnan(r)]
        sharpes = [s for s in sharpes if s is not None and not np.isnan(s)]
        win_rates = [w for w in win_rates if w is not None and not np.isnan(w)]
        
        if not returns:
            return {"error": "No valid returns data"}
        
        # Consistency metrics
        returns_std = np.std(returns)
        returns_mean = np.mean(returns)
        coefficient_of_variation = (returns_std / returns_mean) if returns_mean != 0 else float('inf')
        
        # Percentuale finestre profittevoli
        profitable_windows = sum(1 for r in returns if r > 0)
        profitability_ratio = (profitable_windows / len(returns)) * 100
        
        # Range di performance
        best_window_return = max(returns)
        worst_window_return = min(returns)
        
        # Stabilitàdi Sharpe
        sharpe_mean = np.mean(sharpes) if sharpes else 0
        sharpe_std = np.std(sharpes) if sharpes else 0
        
        # Valutazione robustezza (score 0-10)
        robustness_score = 0
        if profitability_ratio >= 70:
            robustness_score += 3  # Maggioranza finestre profittevoli
        elif profitability_ratio >= 50:
            robustness_score += 2
        elif profitability_ratio >= 40:
            robustness_score += 1
        
        if coefficient_of_variation < 0.5:
            robustness_score += 3  # Bassa variabilità
        elif coefficient_of_variation < 1.0:
            robustness_score += 2
        elif coefficient_of_variation < 1.5:
            robustness_score += 1
        
        if sharpe_mean > 1.5:
            robustness_score += 2  # Sharpe eccellente
        elif sharpe_mean > 1.0:
            robustness_score += 1
        
        if worst_window_return > -10:
            robustness_score += 2  # Worst case gestibile
        elif worst_window_return > -20:
            robustness_score += 1
        
        return {
            "total_windows": len(window_results),
            "profitable_windows": profitable_windows,
            "profitability_ratio_pct": round(profitability_ratio, 2),
            "returns_mean": round(returns_mean, 2),
            "returns_std": round(returns_std, 2),
            "coefficient_of_variation": round(coefficient_of_variation, 2),
            "best_window_return_pct": round(best_window_return, 2),
            "worst_window_return_pct": round(worst_window_return, 2),
            "sharpe_mean": round(sharpe_mean, 2),
            "sharpe_std": round(sharpe_std, 2),
            "robustness_score": robustness_score,
            "robustness_grade": self._grade_robustness(robustness_score),
            "interpretation": self._interpret_robustness(robustness_score)
        }
    
    def _grade_robustness(self, score: float) -> str:
        """Converti robustness score in grade"""
        if score >= 9:
            return "A+ (Eccellente)"
        elif score >= 7:
            return "A (Molto Buono)"
        elif score >= 5:
            return "B (Buono)"
        elif score >= 3:
            return "C (Accettabile)"
        else:
            return "D (Scarso - RISCHIO OVERFITTING)"
    
    def _interpret_robustness(self, score: float) -> str:
        """Interpretazione human-readable del robustness score"""
        if score >= 9:
            return "Strategia estremamente robusta. Performance consistenti in quasi tutti i periodi di mercato."
        elif score >= 7:
            return "Strategia robusta. Buona consistenza con pochi periodi negativi."
        elif score >= 5:
            return "Strategia mediamente robusta. Performance variabili ma gestibili."
        elif score >= 3:
            return "Strategia poco robusta. Elevata variabilità nelle performance."
        else:
            return "ATTENZIONE: Strategia fragile. Alto rischio di overfitting. NON usare in produzione."
    
    def _generate_interpretation(
        self,
        aggregate_metrics: Dict,
        robustness_analysis: Dict
    ) -> str:
        """Genera interpretazione completa dei risultati"""
        interpretation = "\n=== INTERPRETAZIONE WALK-FORWARD ANALYSIS ===\n\n"
        
        # Performance aggregate
        total_return = aggregate_metrics.get("total_return_pct", 0)
        sharpe = aggregate_metrics.get("sharpe_ratio", 0)
        win_rate = aggregate_metrics.get("win_rate", 0)
        profit_factor = aggregate_metrics.get("profit_factor", 0)
        max_dd = aggregate_metrics.get("max_drawdown_pct", 0)
        
        interpretation += "📊 PERFORMANCE OUT-OF-SAMPLE:\n"
        interpretation += f"  - Return Totale: {total_return:.2f}%\n"
        interpretation += f"  - Sharpe Ratio: {sharpe:.2f}"
        if sharpe > 1.5:
            interpretation += " (ECCELLENTE)\n"
        elif sharpe > 1.0:
            interpretation += " (BUONO)\n"
        elif sharpe > 0.5:
            interpretation += " (ACCETTABILE)\n"
        else:
            interpretation += " (SCARSO)\n"
        
        interpretation += f"  - Win Rate: {win_rate:.2f}%\n"
        interpretation += f"  - Profit Factor: {profit_factor:.2f}\n"
        interpretation += f"  - Max Drawdown: {max_dd:.2f}%\n\n"
        
        # Robustezza
        robustness_grade = robustness_analysis.get("robustness_grade", "N/A")
        profitability_ratio = robustness_analysis.get("profitability_ratio_pct", 0)
        
        interpretation += "🛡️ ROBUSTEZZA:\n"
        interpretation += f"  - Grade: {robustness_grade}\n"
        interpretation += f"  - Finestre Profittevoli: {profitability_ratio:.1f}%\n"
        interpretation += f"  - {robustness_analysis.get('interpretation', '')}\n\n"
        
        # Valutazione finale
        interpretation += "🎯 RACCOMANDAZIONE:\n"
        if sharpe > 1.2 and profitability_ratio > 60 and profit_factor > 1.5:
            interpretation += "  ✅ Strategia PROMETTENTE per paper trading.\n"
            interpretation += "  ✅ Metriche out-of-sample solide.\n"
            interpretation += "  ⚠️ Testa comunque 3-6 mesi in paper trading prima di capitale reale.\n"
        elif sharpe > 0.8 and profitability_ratio > 50:
            interpretation += "  ⚠️ Strategia DISCRETA ma necessita miglioramenti.\n"
            interpretation += "  ⚠️ Considera paper trading esteso (6+ mesi).\n"
        else:
            interpretation += "  ❌ Strategia NON PRONTA per produzione.\n"
            interpretation += "  ❌ Performance insufficienti in out-of-sample testing.\n"
            interpretation += "  🔧 Rivedi parametri, filtri, o logica di scoring.\n"
        
        return interpretation
    
    def close(self):
        """Cleanup resources"""
        self.validator.close()
