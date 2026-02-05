"""Technical indicators calculation - Full 22+ indicator suite per Trading System Specification v1.0"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from loguru import logger


class IndicatorCalculator:
    """Calculate technical indicators - Full suite for signal scoring"""
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all 22+ indicators across 4 categories:
        - Trend (7): SMA 20/50/200, EMA 9/21/50, MACD, ADX, Ichimoku, Parabolic SAR, SuperTrend
        - Momentum (6): RSI, Stochastic, Williams %R, CCI, ROC, MFI
        - Volatility (4): ATR, Bollinger Bands, Keltner Channels, Donchian Channels
        - Volume (5): VWAP, Volume SMA, OBV, A/D Line, CMF
        """
        if df.empty:
            return df
        
        df = df.copy()
        
        # ==================== TREND INDICATORS ====================
        # Simple Moving Averages
        df['sma_20'] = IndicatorCalculator._sma(df['close'], length=20)
        df['sma_50'] = IndicatorCalculator._sma(df['close'], length=50)
        df['sma_200'] = IndicatorCalculator._sma(df['close'], length=200)
        
        # Exponential Moving Averages
        df['ema_9'] = IndicatorCalculator._ema(df['close'], length=9)
        df['ema_20'] = IndicatorCalculator._ema(df['close'], length=20)  # Keep for backward compat
        df['ema_21'] = IndicatorCalculator._ema(df['close'], length=21)
        df['ema_50'] = IndicatorCalculator._ema(df['close'], length=50)
        
        # MACD (12, 26, 9)
        macd_data = IndicatorCalculator._macd(df['close'])
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal']
        df['macd_hist'] = macd_data['hist']
        
        # ADX - Average Directional Index (trend strength)
        adx_data = IndicatorCalculator._adx(df['high'], df['low'], df['close'], length=14)
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di']
        df['minus_di'] = adx_data['minus_di']
        
        # Ichimoku Cloud (9, 26, 52)
        ichimoku_data = IndicatorCalculator._ichimoku(df['high'], df['low'], df['close'])
        df['ichimoku_tenkan'] = ichimoku_data['tenkan']
        df['ichimoku_kijun'] = ichimoku_data['kijun']
        df['ichimoku_senkou_a'] = ichimoku_data['senkou_a']
        df['ichimoku_senkou_b'] = ichimoku_data['senkou_b']
        df['ichimoku_chikou'] = ichimoku_data['chikou']
        
        # Parabolic SAR (0.02, 0.2)
        df['parabolic_sar'] = IndicatorCalculator._parabolic_sar(df['high'], df['low'], df['close'])
        
        # SuperTrend (10, 3)
        supertrend_data = IndicatorCalculator._supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
        df['supertrend'] = supertrend_data['supertrend']
        df['supertrend_direction'] = supertrend_data['direction']
        
        # ==================== MOMENTUM INDICATORS ====================
        # RSI (14)
        df['rsi'] = IndicatorCalculator._rsi(df['close'], length=14)
        
        # Stochastic Oscillator (14, 3, 3)
        stoch_data = IndicatorCalculator._stochastic(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch_data['k']
        df['stoch_d'] = stoch_data['d']
        
        # Williams %R (14)
        df['williams_r'] = IndicatorCalculator._williams_r(df['high'], df['low'], df['close'], length=14)
        
        # CCI - Commodity Channel Index (20)
        df['cci'] = IndicatorCalculator._cci(df['high'], df['low'], df['close'], length=20)
        
        # ROC - Rate of Change (12)
        df['roc'] = IndicatorCalculator._roc(df['close'], length=12)
        
        # MFI - Money Flow Index (14) - volume-weighted RSI
        df['mfi'] = IndicatorCalculator._mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
        
        # ==================== VOLATILITY INDICATORS ====================
        # ATR - Average True Range (14)
        df['atr'] = IndicatorCalculator._atr(df['high'], df['low'], df['close'], length=14)
        df['natr'] = (df['atr'] / df['close']) * 100  # Normalized ATR (percentage)
        
        # Bollinger Bands (20, 2)
        bb_data = IndicatorCalculator._bollinger_bands(df['close'], length=20, std_dev=2)
        df['bb_upper'] = bb_data['upper']
        df['bb_middle'] = bb_data['middle']
        df['bb_lower'] = bb_data['lower']
        df['bb_width'] = bb_data['width']
        df['bb_percent'] = bb_data['percent_b']
        
        # Keltner Channels (20, 1.5)
        keltner_data = IndicatorCalculator._keltner_channels(df['high'], df['low'], df['close'], length=20, multiplier=1.5)
        df['keltner_upper'] = keltner_data['upper']
        df['keltner_middle'] = keltner_data['middle']
        df['keltner_lower'] = keltner_data['lower']
        
        # Donchian Channels (20)
        donchian_data = IndicatorCalculator._donchian_channels(df['high'], df['low'], length=20)
        df['donchian_upper'] = donchian_data['upper']
        df['donchian_lower'] = donchian_data['lower']
        df['donchian_middle'] = donchian_data['middle']
        
        # Squeeze detection (BB inside Keltner)
        df['squeeze'] = (df['bb_lower'] > df['keltner_lower']) & (df['bb_upper'] < df['keltner_upper'])
        
        # ==================== VOLUME INDICATORS ====================
        # VWAP
        df['vwap'] = IndicatorCalculator._calculate_vwap(df)
        
        # Volume SMA (20)
        df['volume_sma'] = IndicatorCalculator._sma(df['volume'], length=20)
        df['volume_ratio'] = df['volume'] / df['volume_sma']  # Current vs average
        
        # OBV - On-Balance Volume
        df['obv'] = IndicatorCalculator._obv(df['close'], df['volume'])
        
        # A/D Line - Accumulation/Distribution
        df['ad_line'] = IndicatorCalculator._ad_line(df['high'], df['low'], df['close'], df['volume'])
        
        # CMF - Chaikin Money Flow (20)
        df['cmf'] = IndicatorCalculator._cmf(df['high'], df['low'], df['close'], df['volume'], length=20)
        
        # Dollar volume (for liquidity filtering)
        df['dollar_volume'] = df['close'] * df['volume']
        
        return df
    
    # ==================== BASIC INDICATORS ====================
    
    @staticmethod
    def _sma(series: pd.Series, length: int) -> pd.Series:
        """Simple Moving Average"""
        return series.rolling(window=length, min_periods=length).mean()
    
    @staticmethod
    def _ema(series: pd.Series, length: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=length, adjust=False).mean()
    
    @staticmethod
    def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
        """Relative Strength Index"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """MACD (Moving Average Convergence Divergence)"""
        ema_fast = IndicatorCalculator._ema(series, fast)
        ema_slow = IndicatorCalculator._ema(series, slow)
        macd_line = ema_fast - ema_slow
        signal_line = IndicatorCalculator._ema(macd_line, signal)
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'hist': histogram
        }
    
    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        """Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=length).mean()
        return atr
    
    @staticmethod
    def _calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """Calculate VWAP (Volume Weighted Average Price)"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
        return vwap
    
    # ==================== TREND INDICATORS ====================
    
    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> Dict[str, pd.Series]:
        """
        Average Directional Index - measures trend strength
        ADX > 25 = trending, ADX < 20 = ranging
        """
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

        # Smoothed averages
        # NOTE: pd.Series must use the original index to avoid NaN from index mismatch
        atr = tr.rolling(window=length).mean()
        plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(window=length).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(window=length).mean() / atr
        
        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=length).mean()
        
        return {
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di
        }
    
    @staticmethod
    def _ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
                  tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> Dict[str, pd.Series]:
        """
        Ichimoku Cloud indicator
        Price above cloud = bullish, Tenkan/Kijun cross = entry signal
        """
        # Tenkan-sen (Conversion Line)
        tenkan_high = high.rolling(window=tenkan).max()
        tenkan_low = low.rolling(window=tenkan).min()
        tenkan_sen = (tenkan_high + tenkan_low) / 2
        
        # Kijun-sen (Base Line)
        kijun_high = high.rolling(window=kijun).max()
        kijun_low = low.rolling(window=kijun).min()
        kijun_sen = (kijun_high + kijun_low) / 2
        
        # Senkou Span A (Leading Span A)
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
        
        # Senkou Span B (Leading Span B)
        senkou_b_high = high.rolling(window=senkou_b).max()
        senkou_b_low = low.rolling(window=senkou_b).min()
        senkou_span_b = ((senkou_b_high + senkou_b_low) / 2).shift(kijun)
        
        # Chikou Span (Lagging Span)
        chikou_span = close.shift(-kijun)
        
        return {
            'tenkan': tenkan_sen,
            'kijun': kijun_sen,
            'senkou_a': senkou_span_a,
            'senkou_b': senkou_span_b,
            'chikou': chikou_span
        }
    
    @staticmethod
    def _parabolic_sar(high: pd.Series, low: pd.Series, close: pd.Series,
                       af_start: float = 0.02, af_max: float = 0.2) -> pd.Series:
        """
        Parabolic SAR - trend following indicator
        Dots below price = uptrend, dots above = downtrend
        """
        length = len(close)
        sar = pd.Series(index=close.index, dtype=float)
        af = af_start
        trend = 1  # 1 = uptrend, -1 = downtrend
        
        # Initialize
        sar.iloc[0] = low.iloc[0]
        ep = high.iloc[0]  # Extreme point
        
        for i in range(1, length):
            if trend == 1:  # Uptrend
                sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
                sar.iloc[i] = min(sar.iloc[i], low.iloc[i-1], low.iloc[i-2] if i > 1 else low.iloc[i-1])
                
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + af_start, af_max)
                
                if low.iloc[i] < sar.iloc[i]:  # Trend reversal
                    trend = -1
                    sar.iloc[i] = ep
                    ep = low.iloc[i]
                    af = af_start
            else:  # Downtrend
                sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
                sar.iloc[i] = max(sar.iloc[i], high.iloc[i-1], high.iloc[i-2] if i > 1 else high.iloc[i-1])
                
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + af_start, af_max)
                
                if high.iloc[i] > sar.iloc[i]:  # Trend reversal
                    trend = 1
                    sar.iloc[i] = ep
                    ep = high.iloc[i]
                    af = af_start
        
        return sar
    
    @staticmethod
    def _supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                    length: int = 10, multiplier: float = 3) -> Dict[str, pd.Series]:
        """
        SuperTrend indicator
        Price above band = bullish, below = bearish
        """
        atr = IndicatorCalculator._atr(high, low, close, length)
        hl2 = (high + low) / 2
        
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        supertrend = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=int)
        
        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = -1
        
        for i in range(1, len(close)):
            if close.iloc[i] > supertrend.iloc[i-1]:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1
            elif close.iloc[i] < supertrend.iloc[i-1]:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1
            else:
                supertrend.iloc[i] = supertrend.iloc[i-1]
                direction.iloc[i] = direction.iloc[i-1]
                
                if direction.iloc[i] == 1 and lower_band.iloc[i] > supertrend.iloc[i]:
                    supertrend.iloc[i] = lower_band.iloc[i]
                elif direction.iloc[i] == -1 and upper_band.iloc[i] < supertrend.iloc[i]:
                    supertrend.iloc[i] = upper_band.iloc[i]
        
        return {
            'supertrend': supertrend,
            'direction': direction  # 1 = bullish, -1 = bearish
        }
    
    # ==================== MOMENTUM INDICATORS ====================
    
    @staticmethod
    def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                    k_period: int = 14, d_period: int = 3, smooth_k: int = 3) -> Dict[str, pd.Series]:
        """
        Stochastic Oscillator
        %K/%D crossover in extreme zones (< 20 or > 80) = entry signal
        """
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        
        stoch_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
        stoch_k = stoch_k.rolling(window=smooth_k).mean()  # Smooth %K
        stoch_d = stoch_k.rolling(window=d_period).mean()
        
        return {
            'k': stoch_k,
            'd': stoch_d
        }
    
    @staticmethod
    def _williams_r(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        """
        Williams %R
        < -80 = oversold, > -20 = overbought
        """
        highest_high = high.rolling(window=length).max()
        lowest_low = low.rolling(window=length).min()
        
        wr = -100 * (highest_high - close) / (highest_high - lowest_low)
        return wr
    
    @staticmethod
    def _cci(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 20) -> pd.Series:
        """
        Commodity Channel Index
        > +100 = overbought, < -100 = oversold
        """
        typical_price = (high + low + close) / 3
        sma_tp = typical_price.rolling(window=length).mean()
        mean_deviation = typical_price.rolling(window=length).apply(lambda x: np.abs(x - x.mean()).mean())
        
        cci = (typical_price - sma_tp) / (0.015 * mean_deviation)
        return cci
    
    @staticmethod
    def _roc(series: pd.Series, length: int = 12) -> pd.Series:
        """
        Rate of Change
        Positive = bullish momentum, zero-line cross = signal
        """
        roc = ((series - series.shift(length)) / series.shift(length)) * 100
        return roc
    
    @staticmethod
    def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, length: int = 14) -> pd.Series:
        """
        Money Flow Index - Volume-weighted RSI
        < 20 = oversold, > 80 = overbought
        """
        typical_price = (high + low + close) / 3
        raw_money_flow = typical_price * volume
        
        # Positive and negative money flow
        delta = typical_price.diff()
        positive_flow = raw_money_flow.where(delta > 0, 0).rolling(window=length).sum()
        negative_flow = raw_money_flow.where(delta < 0, 0).rolling(window=length).sum()
        
        money_ratio = positive_flow / negative_flow
        mfi = 100 - (100 / (1 + money_ratio))
        return mfi
    
    # ==================== VOLATILITY INDICATORS ====================
    
    @staticmethod
    def _bollinger_bands(series: pd.Series, length: int = 20, std_dev: float = 2) -> Dict[str, pd.Series]:
        """
        Bollinger Bands
        Price at lower band + RSI < 30 = potential buy signal
        """
        middle = series.rolling(window=length).mean()
        std = series.rolling(window=length).std()
        
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        
        # Bandwidth (volatility measure)
        width = (upper - lower) / middle
        
        # %B (position within bands)
        percent_b = (series - lower) / (upper - lower)
        
        return {
            'upper': upper,
            'middle': middle,
            'lower': lower,
            'width': width,
            'percent_b': percent_b
        }
    
    @staticmethod
    def _keltner_channels(high: pd.Series, low: pd.Series, close: pd.Series,
                          length: int = 20, multiplier: float = 1.5) -> Dict[str, pd.Series]:
        """
        Keltner Channels
        Used with Bollinger Bands for squeeze detection
        """
        middle = IndicatorCalculator._ema(close, length)
        atr = IndicatorCalculator._atr(high, low, close, length)
        
        upper = middle + (multiplier * atr)
        lower = middle - (multiplier * atr)
        
        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }
    
    @staticmethod
    def _donchian_channels(high: pd.Series, low: pd.Series, length: int = 20) -> Dict[str, pd.Series]:
        """
        Donchian Channels
        Breakout above upper = long entry signal
        """
        upper = high.rolling(window=length).max()
        lower = low.rolling(window=length).min()
        middle = (upper + lower) / 2
        
        return {
            'upper': upper,
            'lower': lower,
            'middle': middle
        }
    
    # ==================== VOLUME INDICATORS ====================
    
    @staticmethod
    def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        On-Balance Volume
        Rising OBV + rising price = confirmed trend
        """
        direction = np.where(close > close.shift(), 1, np.where(close < close.shift(), -1, 0))
        obv = (volume * direction).cumsum()
        return pd.Series(obv, index=close.index)
    
    @staticmethod
    def _ad_line(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Accumulation/Distribution Line
        Divergence from price = potential reversal
        """
        clv = ((close - low) - (high - close)) / (high - low)
        clv = clv.fillna(0)  # Handle division by zero
        ad = (clv * volume).cumsum()
        return ad
    
    @staticmethod
    def _cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, length: int = 20) -> pd.Series:
        """
        Chaikin Money Flow
        > 0 = buying pressure, < 0 = selling pressure
        """
        clv = ((close - low) - (high - close)) / (high - low)
        clv = clv.fillna(0)
        
        cmf = (clv * volume).rolling(window=length).sum() / volume.rolling(window=length).sum()
        return cmf
    
    # ==================== UTILITY METHODS ====================
    
    @staticmethod
    def calculate_volume_profile(df: pd.DataFrame, bins: int = 20) -> Dict:
        """
        Calculate Volume Profile to identify POC (Point of Control) and support/resistance levels
        
        Returns:
            Dict with 'poc_price', 'value_area_high', 'value_area_low', 'shelves'
        """
        if df.empty:
            return {}
        
        # Use high-low range for volume distribution
        price_range = df['high'].max() - df['low'].min()
        bin_size = price_range / bins
        
        # Create price bins
        min_price = df['low'].min()
        price_bins = [min_price + i * bin_size for i in range(bins + 1)]
        
        # Distribute volume across price bins
        volume_distribution = {}
        for _, row in df.iterrows():
            # Find which bins this bar contributes to
            bar_low = row['low']
            bar_high = row['high']
            bar_volume = row['volume']
            
            # Distribute volume proportionally across bins
            for i in range(len(price_bins) - 1):
                bin_low = price_bins[i]
                bin_high = price_bins[i + 1]
                
                # Check if bar overlaps with bin
                if bar_low <= bin_high and bar_high >= bin_low:
                    overlap_low = max(bar_low, bin_low)
                    overlap_high = min(bar_high, bin_high)
                    overlap_ratio = (overlap_high - overlap_low) / (bar_high - bar_low) if bar_high != bar_low else 1
                    
                    bin_mid = (bin_low + bin_high) / 2
                    if bin_mid not in volume_distribution:
                        volume_distribution[bin_mid] = 0
                    volume_distribution[bin_mid] += bar_volume * overlap_ratio
        
        if not volume_distribution:
            return {}
        
        # Find POC (price with highest volume)
        poc_price = max(volume_distribution, key=volume_distribution.get)
        total_volume = sum(volume_distribution.values())
        poc_volume = volume_distribution[poc_price]
        
        # Calculate Value Area (70% of volume)
        sorted_prices = sorted(volume_distribution.items(), key=lambda x: x[1], reverse=True)
        cumulative_volume = 0
        value_area_prices = []
        
        for price, volume in sorted_prices:
            cumulative_volume += volume
            value_area_prices.append(price)
            if cumulative_volume >= total_volume * 0.70:
                break
        
        value_area_high = max(value_area_prices)
        value_area_low = min(value_area_prices)
        
        # Identify volume shelves (price levels with significant volume)
        avg_volume = total_volume / len(volume_distribution)
        shelves = [price for price, vol in volume_distribution.items() 
                  if vol > avg_volume * 1.5]
        
        return {
            'poc_price': poc_price,
            'poc_volume': poc_volume,
            'value_area_high': value_area_high,
            'value_area_low': value_area_low,
            'shelves': sorted(shelves),
            'volume_distribution': volume_distribution
        }
