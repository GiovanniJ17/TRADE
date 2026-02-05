"""
Market Regime Detector
Identifica il regime di mercato corrente per selezionare la strategia ottimale

REGIMES:
1. TRENDING (ADX > 25): Use Momentum Strategy
2. CHOPPY (ADX < 20): Use Mean Reversion Strategy
3. BREAKOUT (Consolidation → Expansion): Use Breakout Strategy
4. STRONG_TREND (ADX > 30 + alignment): Use Aggressive Momentum
"""
import pandas as pd
import numpy as np
from typing import Dict, Literal
from loguru import logger

from ..database.market_db import MarketDatabase


RegimeType = Literal['trending', 'choppy', 'breakout', 'strong_trend']


class MarketRegimeDetector:
    """
    Detector del regime di mercato per SPY (benchmark)
    
    Usa:
    - ADX (Average Directional Index) per trend strength
    - ATR (Average True Range) per volatilità
    - Bollinger Bands per consolidation/expansion
    - VIX per risk appetite
    """
    
    # Thresholds
    ADX_TRENDING = 25.0
    ADX_STRONG = 30.0
    ADX_CHOPPY = 20.0
    
    BB_SQUEEZE_THRESHOLD = 0.02  # 2% bandwidth = squeeze
    
    def __init__(self):
        self.db = MarketDatabase()
    
    def detect_regime(
        self,
        benchmark_symbol: str = 'SPY',
        as_of_date: pd.Timestamp = None
    ) -> Dict:
        """
        Rileva regime di mercato corrente
        
        Returns:
            {
                'regime': 'trending'|'choppy'|'breakout'|'strong_trend',
                'adx': float,
                'atr_pct': float,
                'trend_direction': 'up'|'down'|'neutral',
                'bb_bandwidth': float,
                'confidence': 0-100
            }
        """
        if as_of_date is None:
            as_of_date = pd.Timestamp.now()
        
        # Fetch 100 days of data for indicators
        lookback = as_of_date - pd.Timedelta(days=150)
        df = self.db.get_data(benchmark_symbol, start_date=lookback, end_date=as_of_date)
        
        if df.empty or len(df) < 50:
            logger.warning(f"Insufficient data for regime detection ({len(df)} rows)")
            return self._default_regime()
        
        # Calculate indicators
        df = self._calculate_adx(df, period=14)
        df = self._calculate_atr_pct(df, period=14)
        df = self._calculate_bollinger_bands(df, period=20)
        
        latest = df.iloc[-1]
        
        # Extract values
        adx = float(latest['adx']) if not pd.isna(latest['adx']) else 20.0
        atr_pct = float(latest['atr_pct']) if not pd.isna(latest['atr_pct']) else 1.0
        bb_bandwidth = float(latest['bb_bandwidth']) if not pd.isna(latest['bb_bandwidth']) else 0.05
        
        # Trend direction
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        sma_200 = df['close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else sma_50
        price = float(latest['close'])
        
        if price > sma_50 and price > sma_200:
            trend_direction = 'up'
        elif price < sma_50 and price < sma_200:
            trend_direction = 'down'
        else:
            trend_direction = 'neutral'
        
        # Regime classification
        regime, confidence = self._classify_regime(
            adx=adx,
            atr_pct=atr_pct,
            bb_bandwidth=bb_bandwidth,
            trend_direction=trend_direction
        )
        
        logger.info(
            f"Regime Detection: {regime.upper()} "
            f"(ADX={adx:.1f}, BB Width={bb_bandwidth:.3f}, Trend={trend_direction})"
        )
        
        return {
            'regime': regime,
            'adx': adx,
            'atr_pct': atr_pct,
            'trend_direction': trend_direction,
            'bb_bandwidth': bb_bandwidth,
            'confidence': confidence,
            'price': price,
            'sma_50': float(sma_50),
            'sma_200': float(sma_200)
        }
    
    def _classify_regime(
        self,
        adx: float,
        atr_pct: float,
        bb_bandwidth: float,
        trend_direction: str
    ) -> tuple[RegimeType, float]:
        """
        Classifica regime e confidence
        """
        confidence = 70.0  # Base confidence
        
        # STRONG TREND (aggressive momentum)
        if adx > self.ADX_STRONG and trend_direction == 'up' and atr_pct < 2.5:
            # Trend forte, volatilità controllata, uptrend
            confidence = 90.0
            return 'strong_trend', confidence
        
        # BREAKOUT (da consolidation a expansion)
        if bb_bandwidth < self.BB_SQUEEZE_THRESHOLD and adx < self.ADX_CHOPPY:
            # Squeeze: bassa volatilità, pronto per breakout
            confidence = 75.0
            return 'breakout', confidence
        
        # TRENDING
        if adx > self.ADX_TRENDING:
            confidence = 80.0 if adx > 30 else 70.0
            return 'trending', confidence
        
        # CHOPPY (default if not trending)
        if adx < self.ADX_CHOPPY:
            confidence = 65.0
            return 'choppy', confidence
        
        # UNCERTAIN (ADX between 20-25)
        confidence = 50.0
        return 'choppy', confidence  # Default to mean reversion
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Calculate ADX (Average Directional Index)
        Misura la forza del trend (0-100, >25 = strong trend)
        """
        df = df.copy()
        
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        # Smoothed indicators
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / atr
        
        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        df['adx'] = adx
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        
        return df
    
    def _calculate_atr_pct(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        ATR as percentage of price (volatility measure)
        """
        df = df.copy()
        
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        atr_pct = (atr / close) * 100
        
        df['atr_pct'] = atr_pct
        
        return df
    
    def _calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """
        Bollinger Bands per rilevare consolidation (squeeze)
        """
        df = df.copy()
        
        sma = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        
        # Bandwidth (distanza tra bande come % del prezzo)
        bandwidth = (upper - lower) / sma
        
        df['bb_upper'] = upper
        df['bb_lower'] = lower
        df['bb_middle'] = sma
        df['bb_bandwidth'] = bandwidth
        
        return df
    
    def _default_regime(self) -> Dict:
        """Regime di default se mancano dati"""
        return {
            'regime': 'choppy',
            'adx': 20.0,
            'atr_pct': 1.5,
            'trend_direction': 'neutral',
            'bb_bandwidth': 0.05,
            'confidence': 50.0,
            'price': 0.0,
            'sma_50': 0.0,
            'sma_200': 0.0
        }
    
    def close(self):
        """Cleanup"""
        self.db.close()
