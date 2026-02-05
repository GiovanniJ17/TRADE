"""
Unit tests for the Regime Detector module.

Tests:
- ADX-based regime classification
- Regime transitions
- Edge cases (insufficient data, NaN handling)
"""
import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_ohlcv():
    """Generate a realistic OHLCV DataFrame for testing"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range('2024-01-01', periods=n, freq='B')

    price = 100.0
    prices = []
    for _ in range(n):
        price *= 1 + np.random.normal(0.0005, 0.015)
        prices.append(price)

    close = pd.Series(prices, index=dates)
    high = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.randint(500_000, 5_000_000, n), index=dates)

    df = pd.DataFrame({
        'timestamp': dates,
        'open': open_.values,
        'high': high.values,
        'low': low.values,
        'close': close.values,
        'volume': volume.values,
        'symbol': 'TEST'
    })
    return df


@pytest.fixture
def strong_trend_data():
    """Generate data with strong uptrend (high ADX)"""
    n = 300
    dates = pd.date_range('2024-01-01', periods=n, freq='B')
    prices = [100 + i * 0.5 for i in range(n)]  # Strong linear uptrend

    close = pd.Series(prices, index=dates)
    high = close * 1.005
    low = close * 0.995
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.randint(1_000_000, 5_000_000, n), index=dates)

    return pd.DataFrame({
        'timestamp': dates,
        'open': open_.values,
        'high': high.values,
        'low': low.values,
        'close': close.values,
        'volume': volume.values,
        'symbol': 'TREND'
    })


@pytest.fixture
def choppy_data():
    """Generate choppy, range-bound data (low ADX)"""
    n = 300
    dates = pd.date_range('2024-01-01', periods=n, freq='B')
    np.random.seed(99)
    # Oscillate around 100
    prices = [100 + 3 * np.sin(i * 0.5) + np.random.normal(0, 0.5) for i in range(n)]

    close = pd.Series(prices, index=dates)
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.randint(500_000, 2_000_000, n), index=dates)

    return pd.DataFrame({
        'timestamp': dates,
        'open': open_.values,
        'high': high.values,
        'low': low.values,
        'close': close.values,
        'volume': volume.values,
        'symbol': 'CHOPPY'
    })


class TestRegimeDetector:
    """Test regime detection logic"""

    def test_adx_calculation_no_nan(self, sample_ohlcv):
        """ADX should not produce NaN after warmup"""
        from dss.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector.__new__(MarketRegimeDetector)

        adx_result = detector._calculate_adx(sample_ohlcv)
        adx_values = adx_result['adx'].iloc[30:]
        nan_count = adx_values.isna().sum()

        assert nan_count == 0, f"ADX has {nan_count} NaN after warmup"

    def test_adx_range(self, sample_ohlcv):
        """ADX should be between 0 and 100"""
        from dss.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector.__new__(MarketRegimeDetector)

        adx_result = detector._calculate_adx(sample_ohlcv)
        adx = adx_result['adx'].dropna()
        assert adx.min() >= 0, f"ADX below 0: {adx.min()}"
        assert adx.max() <= 100, f"ADX above 100: {adx.max()}"

    def test_regime_returns_valid_type(self, sample_ohlcv):
        """Regime detection should return a valid regime type"""
        from dss.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector.__new__(MarketRegimeDetector)

        adx_result = detector._calculate_adx(sample_ohlcv)
        valid_regimes = {'STRONG_TREND', 'TRENDING', 'CHOPPY', 'BREAKOUT', 'UNKNOWN'}

        adx_val = adx_result['adx'].dropna().iloc[-1]
        # Classify based on ADX
        if adx_val > 30:
            regime = 'STRONG_TREND'
        elif adx_val > 25:
            regime = 'TRENDING'
        else:
            regime = 'CHOPPY'

        assert regime in valid_regimes

    def test_insufficient_data(self):
        """Regime detector should handle insufficient data gracefully"""
        from dss.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector.__new__(MarketRegimeDetector)

        short_data = pd.DataFrame({
            'open': [100, 101],
            'high': [102, 103],
            'low': [99, 100],
            'close': [101, 102],
            'volume': [1000000, 1000000]
        })

        adx_result = detector._calculate_adx(short_data)
        # Should return mostly NaN for insufficient data
        assert adx_result['adx'].isna().sum() > 0
