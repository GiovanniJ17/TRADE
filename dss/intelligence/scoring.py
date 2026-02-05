"""
Signal Scoring System - 100-Point Scale
Per Trading System Specification v1.0

Category Weights:
- Trend Alignment:       35 points (35%)
- Momentum Confirmation: 25 points (25%)
- Volume Validation:     20 points (20%)
- Volatility Context:    10 points (10%)
- Pattern Recognition:   10 points (10%)

Signal Thresholds:
- 80-100: Strong Signal (primary alert)
- 65-79:  Moderate Signal (watchlist)
- 50-64:  Weak Signal (monitor only)
- 0-49:   No Signal (filtered out)
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
from loguru import logger

from .indicators import IndicatorCalculator
from .risk_manager import RiskManager
from ..utils.config import config


class SignalScorer:
    """Calculate trading signal scores using 100-point weighted system"""
    
    # Category weights (must sum to 100)
    WEIGHT_TREND = 35
    WEIGHT_MOMENTUM = 25
    WEIGHT_VOLUME = 20
    WEIGHT_VOLATILITY = 10
    WEIGHT_PATTERN = 10
    
    # Signal thresholds
    THRESHOLD_STRONG = 80
    THRESHOLD_MODERATE = 65
    THRESHOLD_WEAK = 50
    
    def __init__(self):
        """Initialize scorer with configurable thresholds"""
        # Allow config overrides
        self.threshold_strong = config.get("scoring.threshold_strong", self.THRESHOLD_STRONG)
        self.threshold_moderate = config.get("scoring.threshold_moderate", self.THRESHOLD_MODERATE)
        self.threshold_weak = config.get("scoring.threshold_weak", self.THRESHOLD_WEAK)
    
    def score_symbol(self, df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None,
                    volume_profile: Optional[Dict] = None, weekly_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        Calculate comprehensive score for a symbol (0-100 scale)
        
        Args:
            df: OHLCV DataFrame with all indicators calculated
            benchmark_df: Benchmark index DataFrame (e.g., SPY) for relative strength
            volume_profile: Volume profile data with POC, VAH, VAL
            weekly_df: Weekly timeframe data for confluence
        
        Returns:
            Dict with score, breakdown, classification, and risk parameters
        """
        if df.empty:
            return self._empty_result("Empty data")
        
        if len(df) < 50:
            return self._empty_result("Insufficient data (need 50+ bars)")
        
        latest = df.iloc[-1]
        
        # ==================== PRE-CHECK: BULLISH TREND REQUIRED ====================
        # For long trades, we require overall bullish bias
        is_bullish, bullish_reason = self._check_bullish_bias(df, latest)
        
        if not is_bullish:
            return self._bearish_result(latest, bullish_reason)
        
        # ==================== CALCULATE CATEGORY SCORES ====================
        trend_score, trend_breakdown = self._score_trend(df, latest, weekly_df)
        momentum_score, momentum_breakdown = self._score_momentum(df, latest)
        volume_score, volume_breakdown = self._score_volume(df, latest, volume_profile, benchmark_df)
        volatility_score, volatility_breakdown = self._score_volatility(df, latest)
        pattern_score, pattern_breakdown = self._score_patterns(df, latest)
        
        # ==================== CALCULATE TOTAL SCORE ====================
        total_score = trend_score + momentum_score + volume_score + volatility_score + pattern_score
        
        # Determine signal classification
        if total_score >= self.threshold_strong:
            classification = "STRONG"
        elif total_score >= self.threshold_moderate:
            classification = "MODERATE"
        elif total_score >= self.threshold_weak:
            classification = "WEAK"
        else:
            classification = "NO_SIGNAL"
        
        # ==================== CALCULATE RISK PARAMETERS ====================
        entry_price = float(latest['close'])
        atr = float(latest.get('atr', 0)) if pd.notna(latest.get('atr')) else 0
        
        if atr > 0:
            stop_loss = RiskManager.calculate_stop_loss(entry_price, atr)
            quantity, actual_risk, risk_metadata = RiskManager.calculate_position_size(
                entry_price, stop_loss, include_commissions=True
            )
            
            # Calculate target prices (TP1 and TP2 per spec)
            target_price = RiskManager.calculate_target_price(
                entry_price, stop_loss, atr, volume_profile, method="risk_reward"
            )
            if target_price is None:
                target_price = RiskManager.calculate_target_price(
                    entry_price, stop_loss, atr, volume_profile, method="atr_multiple"
                )
            
            # TP1 (partial exit) and TP2 (full exit) per spec
            tp1 = entry_price + (1.5 * atr)  # Sell 50%
            tp2 = entry_price + (3.0 * atr)  # Close remaining
        else:
            stop_loss = None
            quantity = 0
            actual_risk = 0
            target_price = None
            tp1 = None
            tp2 = None
            risk_metadata = {
                'commission_cost': 0,
                'net_risk': 0,
                'min_profit_needed': 0,
                'trade_value': 0,
                'commission_percent': 0,
                'is_profitable_after_commissions': False
            }
        
        # ==================== BUILD RESULT ====================
        breakdown = {
            'trend': trend_breakdown,
            'momentum': momentum_breakdown,
            'volume': volume_breakdown,
            'volatility': volatility_breakdown,
            'pattern': pattern_breakdown
        }
        
        return {
            'score': round(total_score, 1),
            'max_score': 100,
            'classification': classification,
            'breakdown': breakdown,
            'category_scores': {
                'trend': round(trend_score, 1),
                'momentum': round(momentum_score, 1),
                'volume': round(volume_score, 1),
                'volatility': round(volatility_score, 1),
                'pattern': round(pattern_score, 1)
            },
            'is_bullish': True,
            'trend_direction': 'BULLISH',
            'entry_price': entry_price,
            'stop_loss': float(stop_loss) if stop_loss else None,
            'target_price': float(target_price) if target_price else None,
            'tp1': float(tp1) if tp1 else None,
            'tp2': float(tp2) if tp2 else None,
            'position_size': quantity,
            'risk_amount': float(actual_risk),
            'commission_cost': float(risk_metadata.get('commission_cost', 0)),
            'net_risk': float(risk_metadata.get('net_risk', actual_risk)),
            'min_profit_needed': float(risk_metadata.get('min_profit_needed', 0)),
            'trade_value': float(risk_metadata.get('trade_value', 0)),
            'commission_percent': float(risk_metadata.get('commission_percent', 0)),
            'is_profitable_after_commissions': risk_metadata.get('is_profitable_after_commissions', False),
            'sizing_method': risk_metadata.get('sizing_method', 'risk_based'),
            'slot_value_eur': risk_metadata.get('slot_value_eur'),
            'atr': atr,
            'current_price': entry_price,
            'sma_200': float(latest.get('sma_200', 0)) if pd.notna(latest.get('sma_200')) else None,
            'rsi': float(latest.get('rsi', 0)) if pd.notna(latest.get('rsi')) else None,
            'adx': float(latest.get('adx', 0)) if pd.notna(latest.get('adx')) else None
        }
    
    def _check_bullish_bias(self, df: pd.DataFrame, latest: pd.Series) -> Tuple[bool, str]:
        """
        Check if overall trend is bullish (required for long trades)
        Returns: (is_bullish, reason)
        """
        # Primary check: Price > SMA200
        if pd.notna(latest.get('sma_200')):
            if latest['close'] > latest['sma_200']:
                return True, f"Price ${latest['close']:.2f} > SMA200 ${latest['sma_200']:.2f}"
            else:
                return False, f"Price ${latest['close']:.2f} < SMA200 ${latest['sma_200']:.2f} (BEARISH)"
        
        # Fallback: Price > SMA50
        if pd.notna(latest.get('sma_50')):
            if latest['close'] > latest['sma_50']:
                return True, f"Price > SMA50 (SMA200 not available)"
            else:
                return False, f"Price < SMA50 (BEARISH, SMA200 not available)"
        
        # Last resort: Check price position in recent range
        if len(df) >= 50:
            recent_high = df['close'].tail(50).max()
            recent_low = df['close'].tail(50).min()
            current_price = latest['close']
            
            if (recent_high - recent_low) > 0:
                price_position = (current_price - recent_low) / (recent_high - recent_low)
                recent_avg = df['close'].tail(50).mean()
                
                if price_position > 0.6 and current_price > recent_avg:
                    return True, "Price in upper 40% of 50-day range"
        
        return False, "Insufficient bullish confirmation"
    
    def _score_trend(self, df: pd.DataFrame, latest: pd.Series, weekly_df: Optional[pd.DataFrame]) -> Tuple[float, str]:
        """
        Score trend alignment (max 35 points)
        
        Scoring criteria:
        - Price > SMA200: 7 points
        - Price > SMA50 > SMA200 (aligned): 5 points
        - EMA9 > EMA21 > EMA50 (aligned): 5 points
        - MACD > Signal line: 4 points
        - MACD histogram positive & rising: 3 points
        - ADX > 25 (trending): 4 points
        - SuperTrend bullish: 3 points
        - Weekly confluence: 4 points
        """
        score = 0
        details = []
        
        # 1. Price > SMA200 (7 points)
        if pd.notna(latest.get('sma_200')) and latest['close'] > latest['sma_200']:
            score += 7
            details.append("+7 Price > SMA200")
        
        # 2. MA alignment: Price > SMA50 > SMA200 (5 points)
        if (pd.notna(latest.get('sma_50')) and pd.notna(latest.get('sma_200'))):
            if latest['close'] > latest['sma_50'] > latest['sma_200']:
                score += 5
                details.append("+5 MA aligned (Price>SMA50>SMA200)")
        
        # 3. EMA alignment: EMA9 > EMA21 > EMA50 (5 points)
        if (pd.notna(latest.get('ema_9')) and pd.notna(latest.get('ema_21')) and pd.notna(latest.get('ema_50'))):
            if latest['ema_9'] > latest['ema_21'] > latest['ema_50']:
                score += 5
                details.append("+5 EMA aligned (9>21>50)")
        
        # 4. MACD > Signal (4 points)
        if pd.notna(latest.get('macd')) and pd.notna(latest.get('macd_signal')):
            if latest['macd'] > latest['macd_signal']:
                score += 4
                details.append("+4 MACD > Signal")
        
        # 5. MACD histogram positive & rising (3 points)
        if pd.notna(latest.get('macd_hist')) and len(df) >= 2:
            prev_hist = df['macd_hist'].iloc[-2] if pd.notna(df['macd_hist'].iloc[-2]) else 0
            if latest['macd_hist'] > 0 and latest['macd_hist'] > prev_hist:
                score += 3
                details.append("+3 MACD histogram rising")
        
        # 6. ADX > 25 (trending market) (4 points)
        if pd.notna(latest.get('adx')):
            if latest['adx'] > 25:
                score += 4
                details.append(f"+4 ADX {latest['adx']:.1f} > 25 (trending)")
            elif latest['adx'] > 20:
                score += 2
                details.append(f"+2 ADX {latest['adx']:.1f} > 20 (moderate)")
        
        # 7. SuperTrend bullish (3 points)
        if pd.notna(latest.get('supertrend_direction')):
            if latest['supertrend_direction'] == 1:
                score += 3
                details.append("+3 SuperTrend bullish")
        
        # 8. Weekly timeframe confluence (4 points)
        if weekly_df is not None and not weekly_df.empty and len(weekly_df) >= 10:
            try:
                weekly_latest = weekly_df.iloc[-1]
                weekly_sma_200 = weekly_latest.get('sma_200')
                
                if pd.notna(weekly_sma_200) and weekly_latest['close'] > weekly_sma_200:
                    score += 4
                    details.append("+4 Weekly confirms daily (above SMA200)")
            except Exception:
                pass
        
        breakdown = f"{score}/{self.WEIGHT_TREND} - " + ", ".join(details) if details else f"{score}/{self.WEIGHT_TREND}"
        return min(score, self.WEIGHT_TREND), breakdown
    
    def _score_momentum(self, df: pd.DataFrame, latest: pd.Series) -> Tuple[float, str]:
        """
        Score momentum confirmation (max 25 points)
        
        Scoring criteria:
        - RSI in bullish zone (40-70): 5 points
        - RSI rising from oversold (<35): 3 points bonus
        - Stochastic %K > %D: 4 points
        - Stochastic in bullish zone (20-80): 3 points
        - Williams %R rising from oversold: 3 points
        - CCI positive: 3 points
        - ROC positive: 2 points
        - MFI > 50 (buying pressure): 2 points
        """
        score = 0
        details = []
        
        # 1. RSI analysis (up to 8 points)
        if pd.notna(latest.get('rsi')):
            rsi = latest['rsi']
            
            # RSI in bullish zone (40-70) - not overbought
            if 40 <= rsi <= 70:
                score += 5
                details.append(f"+5 RSI {rsi:.1f} in bullish zone")
                
                # Bonus: Rising from oversold
                if len(df) >= 5:
                    rsi_5_ago = df['rsi'].iloc[-5] if pd.notna(df['rsi'].iloc[-5]) else rsi
                    if rsi_5_ago < 35 and rsi > rsi_5_ago:
                        score += 3
                        details.append("+3 RSI rising from oversold")
            elif rsi < 30:
                # Oversold - potential bounce
                score += 2
                details.append(f"+2 RSI {rsi:.1f} oversold (bounce potential)")
        
        # 2. Stochastic analysis (up to 7 points)
        if pd.notna(latest.get('stoch_k')) and pd.notna(latest.get('stoch_d')):
            stoch_k = latest['stoch_k']
            stoch_d = latest['stoch_d']
            
            # %K > %D (bullish crossover)
            if stoch_k > stoch_d:
                score += 4
                details.append("+4 Stoch %K > %D")
            
            # In bullish zone (not extreme)
            if 20 <= stoch_k <= 80:
                score += 3
                details.append("+3 Stoch in healthy zone")
        
        # 3. Williams %R (3 points)
        if pd.notna(latest.get('williams_r')):
            wr = latest['williams_r']
            if len(df) >= 3:
                wr_prev = df['williams_r'].iloc[-3] if pd.notna(df['williams_r'].iloc[-3]) else wr
                if wr_prev < -80 and wr > wr_prev:
                    score += 3
                    details.append("+3 Williams %R rising from oversold")
        
        # 4. CCI positive (3 points)
        if pd.notna(latest.get('cci')):
            if latest['cci'] > 0:
                score += 3
                details.append(f"+3 CCI {latest['cci']:.1f} positive")
        
        # 5. ROC positive (2 points)
        if pd.notna(latest.get('roc')):
            if latest['roc'] > 0:
                score += 2
                details.append(f"+2 ROC {latest['roc']:.1f}% positive")
        
        # 6. MFI > 50 (2 points)
        if pd.notna(latest.get('mfi')):
            if latest['mfi'] > 50:
                score += 2
                details.append(f"+2 MFI {latest['mfi']:.1f} > 50 (buying pressure)")
        
        breakdown = f"{score}/{self.WEIGHT_MOMENTUM} - " + ", ".join(details) if details else f"{score}/{self.WEIGHT_MOMENTUM}"
        return min(score, self.WEIGHT_MOMENTUM), breakdown
    
    def _score_volume(self, df: pd.DataFrame, latest: pd.Series, 
                      volume_profile: Optional[Dict], benchmark_df: Optional[pd.DataFrame]) -> Tuple[float, str]:
        """
        Score volume validation (max 20 points)
        
        Scoring criteria:
        - Volume > 1.5x average: 5 points
        - OBV rising with price: 4 points
        - CMF > 0 (buying pressure): 4 points
        - Price above VWAP: 3 points
        - Price above POC or on volume shelf: 2 points
        - Relative strength vs benchmark: 2 points
        """
        score = 0
        details = []
        
        # 1. Volume surge (5 points)
        if pd.notna(latest.get('volume_ratio')):
            if latest['volume_ratio'] > 1.5:
                score += 5
                details.append(f"+5 Volume {latest['volume_ratio']:.1f}x above average")
            elif latest['volume_ratio'] > 1.2:
                score += 3
                details.append(f"+3 Volume {latest['volume_ratio']:.1f}x above average")
        
        # 2. OBV confirmation (4 points)
        if pd.notna(latest.get('obv')) and len(df) >= 5:
            obv_now = latest['obv']
            obv_5_ago = df['obv'].iloc[-5] if pd.notna(df['obv'].iloc[-5]) else obv_now
            price_now = latest['close']
            price_5_ago = df['close'].iloc[-5]
            
            # OBV rising with price = confirmed trend
            if obv_now > obv_5_ago and price_now > price_5_ago:
                score += 4
                details.append("+4 OBV confirms price rise")
        
        # 3. CMF positive (4 points)
        if pd.notna(latest.get('cmf')):
            if latest['cmf'] > 0.1:
                score += 4
                details.append(f"+4 CMF {latest['cmf']:.2f} strong buying")
            elif latest['cmf'] > 0:
                score += 2
                details.append(f"+2 CMF {latest['cmf']:.2f} buying pressure")
        
        # 4. Price above VWAP (3 points)
        if pd.notna(latest.get('vwap')):
            if latest['close'] > latest['vwap']:
                score += 3
                details.append("+3 Price > VWAP")
        
        # 5. Volume Profile analysis (2 points)
        if volume_profile and latest['close'] > 0:
            poc_price = volume_profile.get('poc_price', 0)
            if poc_price > 0:
                # Price above POC
                if latest['close'] > poc_price:
                    score += 2
                    details.append("+2 Price above POC")
                # Or on a volume shelf (support)
                elif volume_profile.get('shelves'):
                    for shelf in volume_profile['shelves']:
                        if abs(latest['close'] - shelf) / latest['close'] < 0.02:
                            score += 2
                            details.append("+2 Price on volume shelf")
                            break
        
        # 6. Relative strength vs benchmark (2 points)
        if benchmark_df is not None and not benchmark_df.empty and len(df) >= 20:
            try:
                lookback = min(20, len(df), len(benchmark_df))
                symbol_return = (df['close'].iloc[-1] / df['close'].iloc[-lookback] - 1) * 100
                benchmark_return = (benchmark_df['close'].iloc[-1] / benchmark_df['close'].iloc[-lookback] - 1) * 100
                
                if symbol_return > benchmark_return:
                    score += 2
                    details.append(f"+2 Outperforming benchmark by {symbol_return - benchmark_return:.1f}%")
            except Exception:
                pass
        
        breakdown = f"{score}/{self.WEIGHT_VOLUME} - " + ", ".join(details) if details else f"{score}/{self.WEIGHT_VOLUME}"
        return min(score, self.WEIGHT_VOLUME), breakdown
    
    def _score_volatility(self, df: pd.DataFrame, latest: pd.Series) -> Tuple[float, str]:
        """
        Score volatility context (max 10 points)
        
        Scoring criteria:
        - ATR in tradeable range (1.5-5% of price): 3 points
        - Price in lower half of Bollinger Bands (room to run): 3 points
        - Squeeze detected (BB inside Keltner): 2 points
        - Donchian breakout: 2 points
        """
        score = 0
        details = []
        
        # 1. ATR in tradeable range (3 points)
        if pd.notna(latest.get('natr')):
            natr = latest['natr']
            if 1.5 <= natr <= 5.0:
                score += 3
                details.append(f"+3 NATR {natr:.2f}% in good range")
            elif 1.0 <= natr < 1.5:
                score += 1
                details.append(f"+1 NATR {natr:.2f}% low but tradeable")
        
        # 2. Bollinger Bands position (3 points)
        if pd.notna(latest.get('bb_percent')):
            bb_pct = latest['bb_percent']
            # Price in lower half = room to run up
            if 0.2 <= bb_pct <= 0.5:
                score += 3
                details.append(f"+3 BB%B {bb_pct:.2f} (room to run)")
            elif 0.5 < bb_pct <= 0.7:
                score += 2
                details.append(f"+2 BB%B {bb_pct:.2f} (middle zone)")
        
        # 3. Squeeze detection (2 points)
        if pd.notna(latest.get('squeeze')):
            if latest['squeeze']:
                # Check if squeeze is releasing (breakout imminent)
                if len(df) >= 3:
                    prev_squeeze = df['squeeze'].iloc[-3] if pd.notna(df['squeeze'].iloc[-3]) else False
                    if prev_squeeze and not latest['squeeze']:
                        score += 2
                        details.append("+2 Squeeze releasing (breakout)")
                    elif latest['squeeze']:
                        score += 1
                        details.append("+1 Squeeze detected (consolidation)")
        
        # 4. Donchian breakout (2 points)
        if pd.notna(latest.get('donchian_upper')) and len(df) >= 2:
            prev_close = df['close'].iloc[-2]
            prev_donchian = df['donchian_upper'].iloc[-2] if pd.notna(df['donchian_upper'].iloc[-2]) else 0
            
            # Breaking above Donchian upper = breakout
            if latest['close'] > latest['donchian_upper'] * 0.99:  # Within 1% of upper
                score += 2
                details.append("+2 Near Donchian upper (breakout)")
        
        breakdown = f"{score}/{self.WEIGHT_VOLATILITY} - " + ", ".join(details) if details else f"{score}/{self.WEIGHT_VOLATILITY}"
        return min(score, self.WEIGHT_VOLATILITY), breakdown
    
    def _score_patterns(self, df: pd.DataFrame, latest: pd.Series) -> Tuple[float, str]:
        """
        Score pattern recognition (max 10 points)
        
        Basic candlestick patterns:
        - Bullish engulfing: 4 points
        - Hammer/Doji at support: 3 points
        - Higher highs and higher lows: 3 points
        """
        score = 0
        details = []
        
        if len(df) < 3:
            return 0, f"0/{self.WEIGHT_PATTERN} - Insufficient data"
        
        # Get recent bars
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        # 1. Bullish engulfing (4 points)
        curr_body = curr['close'] - curr['open']
        prev_body = prev['close'] - prev['open']
        
        if (prev_body < 0 and  # Previous was bearish
            curr_body > 0 and  # Current is bullish
            curr['open'] < prev['close'] and  # Opens below prev close
            curr['close'] > prev['open']):  # Closes above prev open
            score += 4
            details.append("+4 Bullish engulfing")
        
        # 2. Hammer pattern (3 points)
        body_size = abs(curr_body)
        lower_wick = min(curr['open'], curr['close']) - curr['low']
        upper_wick = curr['high'] - max(curr['open'], curr['close'])
        
        if (lower_wick > body_size * 2 and  # Long lower wick
            upper_wick < body_size * 0.5 and  # Small upper wick
            curr_body >= 0):  # Bullish or neutral
            score += 3
            details.append("+3 Hammer pattern")
        
        # 3. Higher highs and higher lows (3 points)
        if (curr['high'] > prev['high'] > prev2['high'] and
            curr['low'] > prev['low'] > prev2['low']):
            score += 3
            details.append("+3 Higher highs & higher lows")
        
        breakdown = f"{score}/{self.WEIGHT_PATTERN} - " + ", ".join(details) if details else f"{score}/{self.WEIGHT_PATTERN}"
        return min(score, self.WEIGHT_PATTERN), breakdown
    
    def _empty_result(self, reason: str) -> Dict:
        """Return empty result for invalid data"""
        return {
            'score': 0,
            'max_score': 100,
            'classification': 'NO_SIGNAL',
            'reason': reason,
            'breakdown': {},
            'category_scores': {
                'trend': 0, 'momentum': 0, 'volume': 0, 'volatility': 0, 'pattern': 0
            },
            'is_bullish': False,
            'trend_direction': 'UNKNOWN',
            'entry_price': 0,
            'stop_loss': None,
            'target_price': None,
            'tp1': None,
            'tp2': None,
            'position_size': 0,
            'risk_amount': 0
        }
    
    def _bearish_result(self, latest: pd.Series, reason: str) -> Dict:
        """Return result for bearish trend (not suitable for long trades)"""
        return {
            'score': 0,
            'max_score': 100,
            'classification': 'NO_SIGNAL',
            'reason': f'Bearish trend - {reason}',
            'breakdown': {'trend': f'0 ({reason})'},
            'category_scores': {
                'trend': 0, 'momentum': 0, 'volume': 0, 'volatility': 0, 'pattern': 0
            },
            'is_bullish': False,
            'trend_direction': 'BEARISH',
            'entry_price': float(latest['close']),
            'stop_loss': None,
            'target_price': None,
            'tp1': None,
            'tp2': None,
            'position_size': 0,
            'risk_amount': 0,
            'atr': float(latest.get('atr', 0)) if pd.notna(latest.get('atr')) else None,
            'current_price': float(latest['close']),
            'sma_200': float(latest.get('sma_200', 0)) if pd.notna(latest.get('sma_200')) else None,
            'rsi': float(latest.get('rsi', 0)) if pd.notna(latest.get('rsi')) else None
        }
    
    def get_signal_classification(self, score: float) -> str:
        """Get signal classification based on score"""
        if score >= self.threshold_strong:
            return "STRONG"
        elif score >= self.threshold_moderate:
            return "MODERATE"
        elif score >= self.threshold_weak:
            return "WEAK"
        else:
            return "NO_SIGNAL"
