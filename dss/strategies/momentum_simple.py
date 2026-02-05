"""
Simple Momentum Strategy - Version 2.1 (Short-Term Swing)
Optimized for 3-5 day holding period

FILOSOFIA: "Meno è Meglio"
- Solo 2 fattori: Trend + Relative Strength
- Zero parametri ottimizzabili
- Stop loss -5% (tighter for short hold)
- Logica binaria (pass/fail), non scoring

REGOLE:
Entry:
  1. Prezzo > SMA(100) [Trend bullish]
  2. Return 3M > SPY Return 3M [Relative strength]
  3. Liquidity > $3M/day [Filtro qualità]

Exit:
  - Stop loss: -5% fisso (was -8%)
  - Target: +10% informativo
  - Trailing stop: Se profit > +3%, stop = entry + 1%
  - Max hold: 5 giorni (force exit Friday)

Position Sizing:
  - Risk fisso 20€ per trade
  - Max 3 posizioni
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from loguru import logger

from ..database.market_db import MarketDatabase
from ..utils.config import config


class SimpleMomentumStrategy:
    """
    Strategia momentum ultra-semplice per evitare overfitting
    
    Caratteristiche:
    - Zero parametri da ottimizzare
    - Logica trasparente e replicabile
    - Basata su principi economici robusti (momentum persiste)
    """
    
    # Parametri FISSI (non ottimizzabili)
    # RILASSATO: SMA100 invece di SMA200 (entra prima nel trend)
    SMA_PERIOD = 100
    LOOKBACK_MONTHS = 3
    MIN_DOLLAR_VOLUME = 3_000_000  # RILASSATO: $3M/day (più titoli)
    
    # =========================================================================
    # PARAMETRI PER VALIDAZIONE SEGNALI (non per sizing/backtest)
    # I valori REALI usati dal backtest sono in scripts/backtest_portfolio.py:
    #   - MAX_HOLD_WEEKS = 8, TRAILING_TRIGGER_PCT = 6.0, TRAILING_DISTANCE_PCT = 1.5
    # =========================================================================
    STOP_LOSS_PCT = -5.0  # Cap massimo -5%, stop reale = max(ATR*2, entry*0.95)
    RISK_PER_TRADE_EUR = 20.0  # Default, viene sovrascritto da UI settings
    
    # DEPRECATED: Questi parametri non sono usati - mantenuti per retrocompatibilità
    # Vedi backtest_portfolio.py per i valori effettivi
    _DEPRECATED_TRAILING_TRIGGER_PCT = 3.0
    _DEPRECATED_TRAILING_STOP_PCT = 1.0
    _DEPRECATED_MAX_HOLD_DAYS = 15
    _DEPRECATED_MAX_POSITIONS = 3
    
    def __init__(self, user_db=None):
        self.db = MarketDatabase()
        self.user_db = user_db  # For get_exchange_rate()
    
    def generate_signals(
        self,
        symbols: Optional[List[str]] = None,
        as_of_date: Optional[pd.Timestamp] = None
    ) -> List[Dict]:
        """
        Genera segnali usando strategia momentum semplice
        
        Args:
            symbols: Lista simboli da analizzare (None = tutti in DB)
            as_of_date: Data as-of per backtest (None = oggi)
        
        Returns:
            Lista di segnali che passano tutti i filtri
        """
        if symbols is None:
            symbols = self.db.get_all_symbols()
        
        if as_of_date is None:
            as_of_date = pd.Timestamp.now()
        
        logger.info(f"Simple Momentum: Analyzing {len(symbols)} symbols as of {as_of_date.date()}")
        
        # Fetch data
        # Need ~260 trading days (200 for SMA + 60 buffer)
        # 260 trading days = ~380 calendar days (accounting for weekends/holidays)
        lookback_days = 450  # Extra margin for safety
        end_date = as_of_date
        start_date = as_of_date - pd.Timedelta(days=lookback_days)
        
        # PERFORMANCE FIX: Fetch SPY once before loop (instead of 211 times!)
        spy_3m_return = None
        try:
            spy_df = self.db.get_data('SPY', start_date=start_date, end_date=end_date)
            if not spy_df.empty and len(spy_df) >= 63:
                spy_3m_return = (spy_df.iloc[-1]['close'] / spy_df.iloc[-63]['close']) - 1
                logger.debug(f"SPY 3M Return (cached): {spy_3m_return:.2%}")
        except Exception as e:
            logger.warning(f"Could not fetch SPY for relative strength filter: {e}")
        
        signals = []
        
        for symbol in symbols:
            try:
                signal = self._analyze_symbol(
                    symbol, 
                    start_date, 
                    end_date, 
                    as_of_date,
                    spy_3m_return  # Pass cached SPY return
                )
                
                if signal:
                    signals.append(signal)
                    logger.debug(f"✅ {symbol}: PASS - Entry ${signal['entry_price']:.2f}, Stop ${signal['stop_loss']:.2f}")
            
            except Exception as e:
                logger.debug(f"❌ {symbol}: Error - {e}")
        
        logger.info(f"Simple Momentum: {len(signals)} signals generated")
        return signals
    
    def _analyze_symbol(
        self,
        symbol: str,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        as_of_date: pd.Timestamp,
        spy_3m_return: Optional[float] = None
    ) -> Optional[Dict]:
        """
        Analizza singolo simbolo
        
        Returns:
            Dict con signal se passa tutti i filtri, None altrimenti
        """
        # Fetch data
        df = self.db.get_data(symbol, start_date=start_date, end_date=end_date)
        
        if df.empty or len(df) < self.SMA_PERIOD + 60:
            logger.debug(f"{symbol}: ❌ Insufficient data ({len(df)} < {self.SMA_PERIOD + 60})")
            return None
        
        # Calcola SMA trend filter (SMA_PERIOD = 100)
        df['sma_trend'] = df['close'].rolling(window=self.SMA_PERIOD).mean()
        
        # ATR per stop loss adattivo
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(window=14).mean()
        df['natr'] = (df['atr_14'] / df['close']) * 100
        
        latest = df.iloc[-1]
        
        # FILTRO 1: Liquidity
        dollar_volume = latest['close'] * latest['volume']
        if dollar_volume < self.MIN_DOLLAR_VOLUME:
            logger.debug(f"{symbol}: ❌ Liquidity (${dollar_volume:,.0f} < ${self.MIN_DOLLAR_VOLUME:,.0f})")
            return None
        
        # FILTRO 2: Trend (Prezzo > SMA trend)
        if pd.isna(latest['sma_trend']):
            logger.debug(f"{symbol}: ❌ SMA{self.SMA_PERIOD} is NaN")
            return None
        
        if latest['close'] <= latest['sma_trend']:
            logger.debug(f"{symbol}: ❌ Trend (${latest['close']:.2f} <= SMA{self.SMA_PERIOD} ${latest['sma_trend']:.2f})")
            return None
        
        # FILTRO 3: Relative Strength vs SPY (3M return)
        # Calculate 3-month return for the stock
        if len(df) < 63:  # Need at least 3 months of data (21*3 trading days)
            logger.debug(f"{symbol}: ❌ Insufficient data for 3M return")
            return None
        
        stock_3m_return = (latest['close'] / df.iloc[-63]['close']) - 1
        
        # Use cached SPY 3M return (passed as parameter)
        if spy_3m_return is not None:
            # Stock must outperform SPY by at least X% (relative strength)
            # Allow slight underperformance for more signals
            MIN_OUTPERFORMANCE = -0.03  # Stock can underperform SPY by max 3%
            relative_performance = stock_3m_return - spy_3m_return
            
            if relative_performance < MIN_OUTPERFORMANCE:
                logger.debug(f"{symbol}: ❌ Relative Strength ({stock_3m_return:.2%} vs SPY {spy_3m_return:.2%}, diff={relative_performance:.2%} < {MIN_OUTPERFORMANCE:.2%})")
                return None
            
            logger.debug(f"{symbol}: ✅ Relative Strength ({stock_3m_return:.2%} vs SPY {spy_3m_return:.2%}, diff={relative_performance:.2%})")
        else:
            # SPY data not available - skip filter (be permissive)
            logger.debug(f"{symbol}: ⚠️ Relative Strength filter skipped (SPY data unavailable)")
        
        # PASSA TUTTI I FILTRI → Genera signal
        entry_price = float(latest['close'])
        
        # Stop ATR-based: entry - (ATR × 2.0), con cap -5%
        # PROVEN: 2.0x ATR avoids premature stops, -5% cap limits max loss
        atr_value = float(latest['atr_14']) if pd.notna(latest.get('atr_14')) else entry_price * 0.03
        stop_loss = entry_price - (atr_value * 2.0)
        # Cap: non più del -5%
        stop_loss = max(stop_loss, entry_price * 0.95)
        
        # Position sizing
        risk_per_share_usd = entry_price - stop_loss
        if risk_per_share_usd <= 0:
            return None
        
        # Converti risk in USD usando exchange rate
        from ..utils.currency import get_exchange_rate
        rate = get_exchange_rate(user_db=self.user_db)  # Get from user DB or fallback to 0.92
        risk_usd = self.RISK_PER_TRADE_EUR / rate
        quantity = int(risk_usd / risk_per_share_usd)
        
        if quantity <= 0:
            return None
        
        # ========== TRADE ECONOMICS VALIDATION ==========
        # Per Code Review Issue #1: Validate trade is economically viable
        trade_value_usd = entry_price * quantity
        trade_value_eur = trade_value_usd * rate
        
        # Check 1: Minimum trade value (€50 minimum per spec)
        MIN_TRADE_VALUE_EUR = 50.0
        if trade_value_eur < MIN_TRADE_VALUE_EUR:
            logger.debug(f"{symbol}: ❌ Trade value too small (€{trade_value_eur:.2f} < €{MIN_TRADE_VALUE_EUR})")
            return None
        
        # Check 2: Commission impact (must be < 2% of trade value)
        COMMISSION_ROUND_TRIP = 2.0  # €1 entry + €1 exit on Trade Republic
        commission_percent = (COMMISSION_ROUND_TRIP / trade_value_eur) * 100
        MAX_COMMISSION_PERCENT = 2.0
        if commission_percent > MAX_COMMISSION_PERCENT:
            logger.debug(f"{symbol}: ❌ Commission too high ({commission_percent:.2f}% > {MAX_COMMISSION_PERCENT}%)")
            return None
        
        # Target price - ATR-based for realistic targets
        # OPTIMIZED: 3x ATR target with minimum +4% floor
        target_price = entry_price + (atr_value * 3.0)
        min_target = entry_price * 1.04  # At least +4%
        target_price = max(target_price, min_target)
        
        # Calculate 3M return for info
        symbol_return_3m = self._calculate_return(df, months=3)
        
        return {
            'symbol': symbol,
            'strategy': 'simple_momentum_v2.1',
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'position_size': quantity,
            'risk_amount': self.RISK_PER_TRADE_EUR,
            'signal_date': as_of_date,
            'filters_passed': {
                'liquidity': f"${dollar_volume:,.0f}",
                'trend': f"${latest['close']:.2f} > SMA{self.SMA_PERIOD} ${latest['sma_trend']:.2f}"
            },
            'metrics': {
                'return_3m': symbol_return_3m,
                'sma_trend': float(latest['sma_trend']),
                'dollar_volume': dollar_volume,
                'natr': float(latest['natr']) if pd.notna(latest.get('natr')) else 3.0,
                'atr_stop_pct': round(((entry_price - stop_loss) / entry_price) * 100, 2)
            }
        }
    
    def _calculate_return(self, df: pd.DataFrame, months: int) -> float:
        """
        Calcola return su N mesi
        
        Args:
            df: DataFrame con colonna 'close'
            months: Numero mesi lookback
        
        Returns:
            Return percentuale
        """
        if len(df) < 2:
            return 0.0
        
        days = months * 21  # ~21 trading days per mese
        lookback = min(days, len(df) - 1)
        
        if lookback < 1:
            return 0.0
        
        current_price = df['close'].iloc[-1]
        past_price = df['close'].iloc[-lookback]
        
        if past_price <= 0:
            return 0.0
        
        return ((current_price / past_price) - 1) * 100
    
    def close(self):
        """Cleanup"""
        self.db.close()


def calculate_trailing_stop(
    entry_price: float,
    current_price: float,
    highest_price: float
) -> float:
    """
    Calcola trailing stop secondo regole strategia (Short-Term Swing)

    NOTA: Questa funzione usa parametri legacy. Il backtest reale usa
    i parametri definiti in scripts/backtest_portfolio.py:
    - TRAILING_TRIGGER_PCT = 6.0, TRAILING_DISTANCE_PCT = 1.5, TRAILING_MIN_LOCK_PCT = 3.5

    Regole (legacy):
    - Se profit < +3%: stop = entry - 5%
    - Se profit >= +3%: stop = entry + 1% (trailing attivato)

    Args:
        entry_price: Prezzo ingresso
        current_price: Prezzo corrente
        highest_price: Prezzo massimo raggiunto

    Returns:
        Prezzo trailing stop
    """
    TRAILING_TRIGGER_PCT = 3.0
    TRAILING_STOP_PCT = 1.0

    profit_pct = ((current_price - entry_price) / entry_price) * 100

    if profit_pct < TRAILING_TRIGGER_PCT:
        # Trailing non attivo, usa stop fisso -5%
        return entry_price * (1 + SimpleMomentumStrategy.STOP_LOSS_PCT / 100)
    else:
        # Trailing attivo: stop = entry + 1%
        return entry_price * (1 + TRAILING_STOP_PCT / 100)
