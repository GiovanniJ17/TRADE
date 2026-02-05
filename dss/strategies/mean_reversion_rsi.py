"""
Mean Reversion RSI Strategy (Short-Term Swing)
Strategia contrarian per swing trading - 3-5 day hold

FILOSOFIA: "Compra il panico, vendi l'euforia"
Opposite di momentum - entra quando prezzo oversold

REGOLE:
Entry:
  1. RSI < 40 (oversold)
  2. Price > SMA(200) (long-term trend still bullish)
  3. Liquidity > $3M/day

Exit:
  - Target: RSI > 70 O +4% fisso (was +6%)
  - Stop: -4% fisso (was -5%)
  - Max hold: 5 giorni (was 15)

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


class MeanReversionRSI:
    """
    Mean Reversion strategy usando RSI per short-term swing trading
    
    Compra oversold (RSI < 40), vendi overbought (RSI > 70)
    Hold time: 3-5 giorni (max)
    """
    
    # Parametri FISSI (non ottimizzabili)
    # FIX: SMA200 invece di SMA50 - più permissivo per "buy the dip"
    # SMA50 + RSI<40 è internamente contraddittorio (raro)
    # SMA200 come floor di sicurezza permette dip più profondi
    SMA_PERIOD = 200  # Long-term trend filter (was 50)
    RSI_PERIOD = 14
    RSI_OVERSOLD = 40  # Allow more signals, quality controlled by ATR stop
    RSI_OVERBOUGHT = 70
    MIN_DOLLAR_VOLUME = 3_000_000  # RILASSATO: $3M/day (più titoli)
    
    # =========================================================================
    # PARAMETRI PER VALIDAZIONE SEGNALI (non per sizing/backtest)
    # I valori REALI usati dal backtest sono in scripts/backtest_portfolio.py
    # =========================================================================
    STOP_LOSS_PCT = -5.0  # Cap massimo -5%, stop reale = max(ATR*2, entry*0.95)
    RISK_PER_TRADE_EUR = 20.0  # Default, viene sovrascritto da UI settings
    
    def __init__(self, user_db=None, db=None):
        self.db = db or MarketDatabase()
        self._owns_db = db is None  # Only close if we created it
        self.user_db = user_db  # For get_exchange_rate()
    
    def generate_signals(
        self,
        symbols: Optional[List[str]] = None,
        as_of_date: Optional[pd.Timestamp] = None
    ) -> List[Dict]:
        """
        Genera segnali mean reversion
        
        Args:
            symbols: Lista simboli da analizzare
            as_of_date: Data as-of per backtest
        
        Returns:
            Lista di segnali oversold
        """
        if symbols is None:
            symbols = self.db.get_all_symbols()
        
        if as_of_date is None:
            as_of_date = pd.Timestamp.now()
        
        logger.info(f"Mean Reversion RSI: Analyzing {len(symbols)} symbols as of {as_of_date.date()}")
        
        # Fetch data - serve lookback per SMA200 + RSI14
        lookback_days = 350  # ~250 trading days for SMA200
        end_date = as_of_date
        start_date = as_of_date - pd.Timedelta(days=lookback_days)
        
        signals = []
        
        for symbol in symbols:
            try:
                signal = self._analyze_symbol(
                    symbol,
                    start_date,
                    end_date,
                    as_of_date
                )
                
                if signal:
                    signals.append(signal)
                    logger.debug(f"✅ {symbol}: OVERSOLD - RSI {signal['metrics']['rsi']:.1f}, Entry ${signal['entry_price']:.2f}")
            
            except Exception as e:
                logger.debug(f"❌ {symbol}: Error - {e}")
        
        logger.info(f"Mean Reversion RSI: {len(signals)} oversold signals found")
        return signals
    
    def _analyze_symbol(
        self,
        symbol: str,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        as_of_date: pd.Timestamp
    ) -> Optional[Dict]:
        """
        Analizza singolo simbolo per oversold condition
        """
        # Fetch data
        df = self.db.get_data(symbol, start_date=start_date, end_date=end_date)
        
        if df.empty or len(df) < max(self.SMA_PERIOD, self.RSI_PERIOD) + 10:
            logger.debug(f"{symbol}: ❌ Insufficient data ({len(df)} rows)")
            return None
        
        # Calcola SMA floor (SMA_PERIOD = 200, long-term safety filter)
        df['sma_floor'] = df['close'].rolling(window=self.SMA_PERIOD).mean()
        
        # Calcola RSI
        df['rsi'] = self._calculate_rsi(df['close'], self.RSI_PERIOD)
        
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
            logger.debug(f"{symbol}: ❌ Low liquidity (${dollar_volume:,.0f})")
            return None
        
        # FILTRO 2: Long-term trend still bullish (Price > SMA floor)
        if pd.isna(latest['sma_floor']):
            return None
        
        if latest['close'] <= latest['sma_floor']:
            logger.debug(f"{symbol}: ❌ Below SMA{self.SMA_PERIOD} floor (${latest['close']:.2f} < ${latest['sma_floor']:.2f})")
            return None
        
        # FILTRO 3: RSI oversold (< 30)
        if pd.isna(latest['rsi']) or latest['rsi'] >= self.RSI_OVERSOLD:
            logger.debug(f"{symbol}: ❌ Not oversold (RSI {latest['rsi']:.1f} >= {self.RSI_OVERSOLD})")
            return None
        
        # PASSA TUTTI I FILTRI → Segnale oversold!
        entry_price = float(latest['close'])
        
        # Stop ATR-based: entry - (ATR × 2.0), con cap -5%
        # PROVEN: 2.0x ATR avoids premature stops, -5% cap limits max loss
        atr_value = float(latest['atr_14']) if pd.notna(latest.get('atr_14')) else entry_price * 0.03
        stop_loss = entry_price - (atr_value * 2.0)
        # Cap: non più del -5%
        stop_loss = max(stop_loss, entry_price * 0.95)
        # Target price - ATR-based for realistic targets
        # OPTIMIZED: 3x ATR target with minimum +4% floor
        target_price = entry_price + (atr_value * 3.0)
        min_target = entry_price * 1.04  # At least +4%
        target_price = max(target_price, min_target)
        
        # Position sizing
        risk_per_share_usd = entry_price - stop_loss
        if risk_per_share_usd <= 0:
            return None
        
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
        
        return {
            'symbol': symbol,
            'strategy': 'mean_reversion_rsi',
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'position_size': quantity,
            'risk_amount': self.RISK_PER_TRADE_EUR,
            'signal_date': as_of_date,
            'filters_passed': {
                'liquidity': f"${dollar_volume:,.0f}",
                'trend': f"Price ${latest['close']:.2f} > SMA{self.SMA_PERIOD} ${latest['sma_floor']:.2f}",
                'rsi_oversold': f"RSI {latest['rsi']:.1f} < {self.RSI_OVERSOLD}"
            },
            'metrics': {
                'rsi': float(latest['rsi']),
                'sma_floor': float(latest['sma_floor']),
                'dollar_volume': dollar_volume,
                'natr': float(latest['natr']) if pd.notna(latest.get('natr')) else 3.0,
                'atr_stop_pct': round(((entry_price - stop_loss) / entry_price) * 100, 2)
            }
        }
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calcola RSI (Relative Strength Index) con Wilder's smoothing

        Usa EMA (alpha=1/period) come nella definizione originale di Wilder,
        piu' reattiva della SMA-RSI. Cruciale per segnali mean reversion.
        """
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi

    def close(self):
        """Cleanup - only close db if we own it"""
        if self._owns_db:
            self.db.close()
