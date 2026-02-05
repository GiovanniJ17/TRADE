"""
Breakout Strategy (Short-Term Swing)
Strategia per catturare esplosioni di volatilità dopo consolidazioni
Optimized for 3-5 day holding period

FILOSOFIA: "Compra quando il prezzo esce da una zona di range con volume"

REGOLE:
Entry:
  1. Price breaks 20-day high
  2. Volume > 1.2x average volume (spike)
  3. Bollinger Bands in squeeze (bassa volatilità pre-breakout)
  4. Price > SMA(50) (trend context)

Exit:
  - Target: +8% (was +15%, realistic for 3-5 days)
  - Stop: -3% (was -4%, tighter for failed breakouts)
  - Max hold: 5 giorni (was 10)

Position Sizing:
  - Risk fisso 20€ per trade
  - Max 3 posizioni
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from loguru import logger

from ..database.market_db import MarketDatabase


class BreakoutStrategy:
    """
    Breakout strategy - cattura esplosioni dopo consolidazioni
    
    Entry: High break + Volume spike + BB squeeze
    Hold time: 3-5 giorni (short-term swing)
    """
    
    # Parametri FISSI
    BREAKOUT_PERIOD = 20  # 20-day high
    SMA_PERIOD = 50
    VOLUME_SPIKE_MULTIPLIER = 1.3  # Balanced: enough confirmation without being too strict
    BB_SQUEEZE_THRESHOLD = 0.05  # RILASSATO: 5% (meno squeeze richiesto)
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
        Genera segnali breakout
        
        Returns:
            Lista di segnali breakout con volume spike
        """
        if symbols is None:
            symbols = self.db.get_all_symbols()
        
        if as_of_date is None:
            as_of_date = pd.Timestamp.now()
        
        logger.info(f"Breakout Strategy: Analyzing {len(symbols)} symbols as of {as_of_date.date()}")
        
        # Fetch data
        lookback_days = 250  # ~6 mesi per calcoli
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
                    logger.debug(
                        f"✅ {symbol}: BREAKOUT - High break, Volume {signal['metrics']['volume_ratio']:.1f}x"
                    )
            
            except Exception as e:
                logger.debug(f"❌ {symbol}: Error - {e}")
        
        logger.info(f"Breakout Strategy: {len(signals)} breakout signals found")
        return signals
    
    def _analyze_symbol(
        self,
        symbol: str,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        as_of_date: pd.Timestamp
    ) -> Optional[Dict]:
        """
        Analizza singolo simbolo per breakout
        """
        df = self.db.get_data(symbol, start_date=start_date, end_date=end_date)
        
        if df.empty or len(df) < max(self.BREAKOUT_PERIOD, self.SMA_PERIOD) + 10:
            logger.debug(f"{symbol}: ❌ Insufficient data ({len(df)} rows)")
            return None
        
        # Calculate indicators
        df['sma_50'] = df['close'].rolling(window=self.SMA_PERIOD).mean()
        df['high_20'] = df['high'].rolling(window=self.BREAKOUT_PERIOD).max()
        df['avg_volume'] = df['volume'].rolling(window=20).mean()
        
        # Bollinger Bands per squeeze detection
        sma_20 = df['close'].rolling(window=20).mean()
        std_20 = df['close'].rolling(window=20).std()
        upper = sma_20 + (2 * std_20)
        lower = sma_20 - (2 * std_20)
        df['bb_bandwidth'] = (upper - lower) / sma_20
        
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
        
        # FILTRO 2: Trend context (Price > SMA50)
        if pd.isna(latest['sma_50']) or latest['close'] <= latest['sma_50']:
            logger.debug(f"{symbol}: ❌ Below SMA50")
            return None
        
        # FILTRO 3: High breakout (price > 20-day high)
        # FIX: Check finestra di 3 giorni per compensare step_days
        # Un breakout può durare solo 1 giorno, con step_days>1 lo perderesti
        BREAKOUT_WINDOW = 3  # Check last 3 days for breakout
        
        breakout_detected = False
        breakout_day_idx = -1
        breakout_day = None
        
        for i in range(1, min(BREAKOUT_WINDOW + 1, len(df))):
            day_idx = -i
            if abs(day_idx) >= len(df):
                break
            
            day = df.iloc[day_idx]
            prev_day = df.iloc[day_idx - 1] if abs(day_idx - 1) < len(df) else day
            
            if pd.isna(prev_day['high_20']):
                continue
            
            # Breakout condition: close > previous day's high_20
            if day['close'] > prev_day['high_20']:
                breakout_detected = True
                breakout_day_idx = day_idx
                breakout_day = day  # Store the day data for filter checks
                break
        
        if not breakout_detected:
            logger.debug(f"{symbol}: ❌ No breakout in last {BREAKOUT_WINDOW} days")
            return None
        
        # FIX: Use breakout_day for volume and BB filters (not latest)
        # This ensures consistency: if breakout happened 2 days ago, 
        # check volume/BB from THAT day, not today
        filter_day = breakout_day if breakout_day is not None else latest
        
        # FILTRO 4: BB Squeeze (consolidation pre-breakout)
        if pd.isna(filter_day['bb_bandwidth']) or filter_day['bb_bandwidth'] > self.BB_SQUEEZE_THRESHOLD:
            logger.debug(f"{symbol}: ❌ No BB squeeze on breakout day (width {filter_day['bb_bandwidth']:.4f})")
            return None
        
        # FILTRO 5: Volume spike (on breakout day)
        if pd.isna(filter_day['avg_volume']):
            return None
        
        volume_ratio = filter_day['volume'] / filter_day['avg_volume']
        if volume_ratio < self.VOLUME_SPIKE_MULTIPLIER:
            logger.debug(f"{symbol}: ❌ No volume spike on breakout day ({volume_ratio:.1f}x < {self.VOLUME_SPIKE_MULTIPLIER}x)")
            return None
        
        # PASSA TUTTI I FILTRI → Segnale breakout!
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
            'strategy': 'breakout',
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'position_size': quantity,
            'risk_amount': self.RISK_PER_TRADE_EUR,
            'signal_date': as_of_date,
            'filters_passed': {
                'liquidity': f"${dollar_volume:,.0f}",
                'trend': f"Price ${latest['close']:.2f} > SMA50 ${latest['sma_50']:.2f}",
                'bb_squeeze': f"BB width {latest['bb_bandwidth']:.4f} < {self.BB_SQUEEZE_THRESHOLD}",
                'breakout': f"${entry_price:.2f} > 20D high ${filter_day['high_20']:.2f}",
                'volume_spike': f"{volume_ratio:.1f}x > {self.VOLUME_SPIKE_MULTIPLIER}x"
            },
            'metrics': {
                'high_20': float(filter_day['high_20']),
                'volume_ratio': float(volume_ratio),
                'bb_bandwidth': float(latest['bb_bandwidth']),
                'sma_50': float(latest['sma_50']),
                'dollar_volume': dollar_volume,
                'natr': float(latest['natr']) if pd.notna(latest.get('natr')) else 3.0,
                'atr_stop_pct': round(((entry_price - stop_loss) / entry_price) * 100, 2)
            }
        }

    def close(self):
        """Cleanup - only close db if we own it"""
        if self._owns_db:
            self.db.close()
