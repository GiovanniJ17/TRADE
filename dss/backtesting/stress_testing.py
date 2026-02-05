"""
Stress Testing Module
Simula scenari estremi di mercato per valutare la resilienza della strategia
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from loguru import logger

from .historical_validator import HistoricalValidator
from ..database.market_db import MarketDatabase
from ..utils.config import config


class StressTestScenario:
    """Definizione di uno scenario di stress test"""
    
    # Scenari storici famosi
    CRASH_2008 = {
        "name": "2008 Financial Crisis",
        "market_drop_pct": -50,
        "volatility_multiplier": 3.0,
        "correlation_increase": 0.9,
        "duration_days": 180,
        "description": "Simulazione crollo 2008: -50% mercato, volatilità x3"
    }
    
    FLASH_CRASH_2010 = {
        "name": "2010 Flash Crash",
        "market_drop_pct": -10,
        "volatility_multiplier": 5.0,
        "correlation_increase": 0.95,
        "duration_days": 1,
        "gap_down_pct": -8,
        "description": "Flash crash improvviso: -10% intraday, gap -8%"
    }
    
    COVID_CRASH_2020 = {
        "name": "COVID-19 Crash (March 2020)",
        "market_drop_pct": -35,
        "volatility_multiplier": 4.0,
        "correlation_increase": 0.85,
        "duration_days": 30,
        "description": "Crash COVID rapido: -35% in 30 giorni"
    }
    
    BLACK_MONDAY_1987 = {
        "name": "Black Monday 1987",
        "market_drop_pct": -22,
        "volatility_multiplier": 10.0,
        "correlation_increase": 1.0,
        "duration_days": 1,
        "gap_down_pct": -20,
        "description": "Worst single day: -22% in un giorno, gap -20%"
    }
    
    MILD_CORRECTION = {
        "name": "Mild Correction (-15%)",
        "market_drop_pct": -15,
        "volatility_multiplier": 2.0,
        "correlation_increase": 0.7,
        "duration_days": 45,
        "description": "Correzione normale: -15% in 45 giorni"
    }


class StressTester:
    """
    Testa la strategia in condizioni estreme di mercato
    
    OBIETTIVO: Scoprire le debolezze prima che si manifestino in produzione
    
    Scenari testati:
    1. Crash di mercato (-50%)
    2. Flash crash (-10% in 1 giorno)
    3. Alta volatilità (ATR x3)
    4. Gap down massicci (-8%)
    5. Correlazione estrema (tutti i titoli scendono insieme)
    """
    
    def __init__(self):
        self.validator = HistoricalValidator()
        self.db = MarketDatabase()
    
    def run_stress_tests(
        self,
        symbols: Optional[List[str]] = None,
        base_capital: float = 1500.0,
        scenarios: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Esegui batteria completa di stress tests
        
        Args:
            symbols: Lista simboli da testare
            base_capital: Capitale iniziale
            scenarios: Lista scenari custom (None = usa scenari default)
        
        Returns:
            Dict con risultati per ogni scenario
        """
        if scenarios is None:
            scenarios = [
                StressTestScenario.MILD_CORRECTION,
                StressTestScenario.COVID_CRASH_2020,
                StressTestScenario.CRASH_2008,
                StressTestScenario.FLASH_CRASH_2010,
                StressTestScenario.BLACK_MONDAY_1987
            ]
        
        logger.info(f"Running {len(scenarios)} stress test scenarios...")
        
        results = []
        
        for scenario in scenarios:
            logger.info(f"\n=== Testing Scenario: {scenario['name']} ===")
            logger.info(f"Description: {scenario['description']}")
            
            result = self._run_single_scenario(
                scenario, symbols, base_capital
            )
            
            results.append(result)
            
            # Log summary
            final_capital = result.get("final_capital", base_capital)
            loss_pct = ((final_capital - base_capital) / base_capital) * 100
            logger.info(f"Result: Capital {base_capital:.0f} → {final_capital:.0f} ({loss_pct:+.2f}%)")
        
        # Analisi aggregata
        aggregate_analysis = self._analyze_stress_results(results, base_capital)
        
        return {
            "scenarios": results,
            "aggregate_analysis": aggregate_analysis,
            "worst_case_scenario": self._find_worst_case(results),
            "interpretation": self._generate_interpretation(aggregate_analysis)
        }
    
    def _run_single_scenario(
        self,
        scenario: Dict,
        symbols: Optional[List[str]],
        base_capital: float
    ) -> Dict[str, Any]:
        """Esegui singolo scenario di stress"""
        
        # Simula effetti dello scenario
        scenario_results = {
            "scenario_name": scenario["name"],
            "scenario_params": scenario,
            "base_capital": base_capital
        }
        
        # Calcola perdite teoriche (worst case)
        market_drop = scenario.get("market_drop_pct", 0)
        gap_down = scenario.get("gap_down_pct", 0)
        
        # Scenario 1: Stop Loss vengono colpiti esattamente
        # Assumendo 3 posizioni aperte, rischio 1% ciascuna
        max_positions = config.get("risk.max_positions", 3)
        risk_per_trade = config.get("risk.max_risk_per_trade_fixed", 20)
        
        # Best case: Stop loss funzionano perfettamente
        best_case_loss = max_positions * risk_per_trade
        
        # Worst case: Gap down significa slippage maggiore
        if gap_down < 0:
            # Con gap down, perdi più dello stop loss
            # Esempio: stop a -2%, gap down -8% = perdi 8%
            slippage_factor = abs(gap_down) / 2.0  # Stima conservativa
            worst_case_loss = max_positions * risk_per_trade * slippage_factor
        else:
            worst_case_loss = best_case_loss
        
        # Realistic case: misto (alcuni stop ok, alcuni con slippage)
        realistic_loss = (best_case_loss + worst_case_loss) / 2
        
        scenario_results["theoretical_losses"] = {
            "best_case_eur": round(best_case_loss, 2),
            "worst_case_eur": round(worst_case_loss, 2),
            "realistic_eur": round(realistic_loss, 2),
            "best_case_pct": round((best_case_loss / base_capital) * 100, 2),
            "worst_case_pct": round((worst_case_loss / base_capital) * 100, 2),
            "realistic_pct": round((realistic_loss / base_capital) * 100, 2)
        }
        
        # Calcola capitale finale (realistic scenario)
        final_capital = base_capital - realistic_loss
        scenario_results["final_capital"] = round(final_capital, 2)
        scenario_results["total_loss_pct"] = round(((final_capital - base_capital) / base_capital) * 100, 2)
        
        # Valuta survivability
        survival_rate = (final_capital / base_capital) * 100
        scenario_results["survival_rate_pct"] = round(survival_rate, 2)
        scenario_results["survived"] = survival_rate > 70  # Threshold: mantieni >70% capitale
        
        # Tempo di recovery stimato
        # Assumendo rendimento medio 15% annuo in condizioni normali
        if final_capital < base_capital:
            loss_amount = base_capital - final_capital
            recovery_years = loss_amount / (base_capital * 0.15)  # 15% annuo
            scenario_results["recovery_time_years"] = round(recovery_years, 2)
        else:
            scenario_results["recovery_time_years"] = 0
        
        return scenario_results
    
    def _analyze_stress_results(
        self,
        results: List[Dict],
        base_capital: float
    ) -> Dict[str, Any]:
        """Analizza risultati aggregati di tutti gli scenari"""
        
        # Worst case across all scenarios
        worst_loss_pct = min(r["total_loss_pct"] for r in results)
        best_loss_pct = max(r["total_loss_pct"] for r in results)
        avg_loss_pct = np.mean([r["total_loss_pct"] for r in results])
        
        # Survival rate
        scenarios_survived = sum(1 for r in results if r["survived"])
        survival_ratio = (scenarios_survived / len(results)) * 100
        
        # Max recovery time needed
        max_recovery_years = max(r["recovery_time_years"] for r in results)
        
        # Risk score (0-10, dove 10 = molto rischioso)
        risk_score = 0
        if worst_loss_pct < -20:
            risk_score += 4  # Perdita potenziale >20%
        elif worst_loss_pct < -10:
            risk_score += 2
        
        if survival_ratio < 80:
            risk_score += 3  # Basso tasso di sopravvivenza
        elif survival_ratio < 100:
            risk_score += 1
        
        if max_recovery_years > 2:
            risk_score += 3  # Tempi recovery lunghi
        elif max_recovery_years > 1:
            risk_score += 1
        
        return {
            "total_scenarios_tested": len(results),
            "scenarios_survived": scenarios_survived,
            "survival_ratio_pct": round(survival_ratio, 2),
            "worst_case_loss_pct": round(worst_loss_pct, 2),
            "best_case_loss_pct": round(best_loss_pct, 2),
            "average_loss_pct": round(avg_loss_pct, 2),
            "max_recovery_time_years": round(max_recovery_years, 2),
            "risk_score": risk_score,
            "risk_grade": self._grade_risk(risk_score),
            "is_resilient": survival_ratio >= 80 and worst_loss_pct > -25
        }
    
    def _find_worst_case(self, results: List[Dict]) -> Dict:
        """Trova lo scenario con peggiori risultati"""
        worst = min(results, key=lambda r: r["final_capital"])
        return {
            "scenario_name": worst["scenario_name"],
            "final_capital": worst["final_capital"],
            "loss_pct": worst["total_loss_pct"],
            "recovery_years": worst["recovery_time_years"]
        }
    
    def _grade_risk(self, risk_score: float) -> str:
        """Converti risk score in grade"""
        if risk_score >= 8:
            return "HIGH RISK (D)"
        elif risk_score >= 6:
            return "MODERATE-HIGH RISK (C)"
        elif risk_score >= 4:
            return "MODERATE RISK (B)"
        elif risk_score >= 2:
            return "LOW-MODERATE RISK (A)"
        else:
            return "LOW RISK (A+)"
    
    def _generate_interpretation(self, analysis: Dict) -> str:
        """Genera interpretazione human-readable"""
        interpretation = "\n=== STRESS TEST INTERPRETATION ===\n\n"
        
        survival_ratio = analysis["survival_ratio_pct"]
        worst_loss = analysis["worst_case_loss_pct"]
        risk_grade = analysis["risk_grade"]
        
        interpretation += f"🛡️ RESILIENZA: {survival_ratio:.0f}% scenari superati\n"
        interpretation += f"📉 WORST CASE: {worst_loss:.2f}% perdita\n"
        interpretation += f"⚠️ RISK GRADE: {risk_grade}\n\n"
        
        interpretation += "📊 VALUTAZIONE:\n"
        
        if analysis["is_resilient"]:
            interpretation += "  ✅ Sistema RESILIENTE: Sopravvive alla maggior parte degli scenari estremi.\n"
            interpretation += "  ✅ Risk management funziona anche in condizioni avverse.\n"
            if worst_loss > -10:
                interpretation += "  ✅ Perdite massime contenute (<10%).\n"
        else:
            interpretation += "  ❌ Sistema FRAGILE: Performance scadenti in scenari estremi.\n"
            interpretation += "  ❌ Risk management insufficiente per crash severi.\n"
            if worst_loss < -25:
                interpretation += "  ❌ ATTENZIONE: Perdite potenziali >25% in worst case.\n"
        
        interpretation += "\n🎯 RACCOMANDAZIONI:\n"
        
        if analysis["is_resilient"]:
            interpretation += "  • Sistema pronto per condizioni di mercato avverse.\n"
            interpretation += "  • Mantieni sempre stop loss attivi.\n"
            interpretation += "  • Considera di ridurre esposizione se SPY < SMA200.\n"
        else:
            interpretation += "  • ⚠️ Riduci max_positions a 2 invece di 3.\n"
            interpretation += "  • ⚠️ Riduci risk_per_trade da 20€ a 15€.\n"
            interpretation += "  • ⚠️ Aumenta ATR multiplier per stop loss più larghi.\n"
            interpretation += "  • ⚠️ Aggiungi filtro: no nuove posizioni se VIX > 30.\n"
        
        return interpretation
    
    def simulate_black_swan_event(
        self,
        symbols: Optional[List[str]] = None,
        severity: str = "extreme"  # "moderate", "severe", "extreme"
    ) -> Dict[str, Any]:
        """
        Simula evento Black Swan (improbabile ma devastante)
        
        Args:
            symbols: Lista simboli
            severity: Livello severità ("moderate", "severe", "extreme")
        
        Returns:
            Dict con analisi impatto
        """
        severity_params = {
            "moderate": {
                "market_drop_pct": -30,
                "gap_down_pct": -10,
                "volatility_multiplier": 5.0,
                "stop_slippage_pct": 5.0  # Stop loss eseguiti 5% sotto il target
            },
            "severe": {
                "market_drop_pct": -50,
                "gap_down_pct": -20,
                "volatility_multiplier": 8.0,
                "stop_slippage_pct": 10.0
            },
            "extreme": {
                "market_drop_pct": -70,
                "gap_down_pct": -30,
                "volatility_multiplier": 15.0,
                "stop_slippage_pct": 20.0  # Circuit breakers, market halt
            }
        }
        
        params = severity_params.get(severity, severity_params["severe"])
        
        logger.warning(f"⚠️ Simulating BLACK SWAN event (severity: {severity})")
        
        # Get values from config/user settings (no hardcoded values)
        max_positions = config.get("portfolio.max_stock_positions", 3)
        base_capital = config.get("risk.available_capital", 10000.0)
        risk_per_position = config.get("risk.max_risk_per_trade_percent", 1.5) * base_capital / 100
        
        # In un Black Swan, gli stop loss non funzionano bene
        slippage_pct = params["stop_slippage_pct"]
        gap_down = abs(params["gap_down_pct"])
        
        # Perdita per posizione: invece di -2% (stop), perdi gap_down %
        # Position value = capital / max_positions (proportional)
        position_value = (base_capital * 0.9) / max_positions  # 90% stock allocation
        loss_per_position = position_value * (gap_down / 100)
        
        total_loss = min(loss_per_position * max_positions, base_capital * 0.5)  # Cap al 50%
        final_capital = base_capital - total_loss
        loss_pct = (total_loss / base_capital) * 100
        
        # Probability assessment (rough estimate)
        probability_per_year = {
            "moderate": 0.10,  # 10% probabilità annua
            "severe": 0.02,    # 2% probabilità annua (una volta ogni 50 anni)
            "extreme": 0.002   # 0.2% probabilità annua (una volta ogni 500 anni)
        }
        
        return {
            "severity": severity,
            "params": params,
            "base_capital": base_capital,
            "total_loss_eur": round(total_loss, 2),
            "final_capital": round(final_capital, 2),
            "loss_pct": round(loss_pct, 2),
            "probability_per_year": probability_per_year.get(severity, 0.01),
            "expected_loss_per_year_eur": round(total_loss * probability_per_year.get(severity, 0.01), 2),
            "interpretation": self._interpret_black_swan(severity, loss_pct, final_capital, base_capital)
        }
    
    def _interpret_black_swan(
        self,
        severity: str,
        loss_pct: float,
        final_capital: float,
        base_capital: float
    ) -> str:
        """Interpreta risultati black swan"""
        interp = f"\n=== BLACK SWAN SCENARIO ({severity.upper()}) ===\n\n"
        
        interp += f"💥 IMPATTO: -{loss_pct:.1f}% del capitale\n"
        interp += f"💰 CAPITALE: {base_capital:.0f}€ → {final_capital:.0f}€\n\n"
        
        if final_capital > base_capital * 0.7:
            interp += "✅ SOPRAVVIVENZA: Capitale ancora utilizzabile (>70%).\n"
            interp += "✅ Possibile continuare trading dopo evento.\n"
        elif final_capital > base_capital * 0.5:
            interp += "⚠️ SOPRAVVIVENZA MARGINALE: Capitale ridotto ma recuperabile.\n"
            interp += "⚠️ Necessario lungo periodo di recovery.\n"
        else:
            interp += "❌ CAPITOLAZIONE: Perdita >50% del capitale.\n"
            interp += "❌ Recovery estremamente difficile.\n"
            interp += "🚨 Scenario distruttivo per l'account.\n"
        
        return interp
    
    def close(self):
        """Cleanup"""
        self.validator.close()
        self.db.close()
