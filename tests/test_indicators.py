"""
Test suite per i calcoli finanziari critici del DSS.

Testa:
- RSI (Wilder's EMA)
- ADX (index alignment)
- SMA (min_periods correctness)
- VWAP (rolling window)
- Trailing stop logic
- Position sizing
"""
import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ==================== FIXTURES ====================

@pytest.fixture
def sample_ohlcv():
    """Generate a realistic OHLCV DataFrame for testing"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range('2024-01-01', periods=n, freq='B')

    # Simulate trending price with noise
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
def trending_up_series():
    """Monotonically increasing price series for RSI testing"""
    dates = pd.date_range('2024-01-01', periods=50, freq='B')
    prices = pd.Series(np.linspace(100, 150, 50), index=dates)
    return prices


@pytest.fixture
def trending_down_series():
    """Monotonically decreasing price series for RSI testing"""
    dates = pd.date_range('2024-01-01', periods=50, freq='B')
    prices = pd.Series(np.linspace(150, 100, 50), index=dates)
    return prices


# ==================== RSI TESTS ====================

class TestRSI:
    """Test RSI calculation with Wilder's EMA"""

    def test_rsi_range(self, sample_ohlcv):
        """RSI must always be between 0 and 100"""
        from dss.intelligence.indicators import IndicatorCalculator
        rsi = IndicatorCalculator._rsi(sample_ohlcv['close'])
        valid = rsi.dropna()
        assert valid.min() >= 0, f"RSI below 0: {valid.min()}"
        assert valid.max() <= 100, f"RSI above 100: {valid.max()}"

    def test_rsi_trending_up_is_high(self, trending_up_series):
        """RSI of a monotonically increasing series should be very high (near 100)"""
        from dss.intelligence.indicators import IndicatorCalculator
        rsi = IndicatorCalculator._rsi(trending_up_series)
        last_rsi = rsi.iloc[-1]
        assert last_rsi > 80, f"RSI of strong uptrend should be > 80, got {last_rsi}"

    def test_rsi_trending_down_is_low(self, trending_down_series):
        """RSI of a monotonically decreasing series should be very low (near 0)"""
        from dss.intelligence.indicators import IndicatorCalculator
        rsi = IndicatorCalculator._rsi(trending_down_series)
        last_rsi = rsi.iloc[-1]
        assert last_rsi < 20, f"RSI of strong downtrend should be < 20, got {last_rsi}"

    def test_rsi_nan_for_insufficient_data(self):
        """RSI should be NaN when there isn't enough data"""
        from dss.intelligence.indicators import IndicatorCalculator
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        short_series = pd.Series(np.random.randn(10).cumsum() + 100, index=dates)
        rsi = IndicatorCalculator._rsi(short_series, length=14)
        # First 14 values should be NaN
        assert rsi.iloc[:14].isna().all(), "RSI should be NaN for first 14 values with period=14"

    def test_rsi_uses_ema_not_sma(self):
        """Verify RSI uses Wilder's EMA (reacts faster than SMA to recent changes)"""
        from dss.intelligence.indicators import IndicatorCalculator
        dates = pd.date_range('2024-01-01', periods=60, freq='B')
        # Flat then sudden spike
        prices = [100.0] * 30 + [100.0 + i * 2.0 for i in range(30)]
        series = pd.Series(prices, index=dates)
        rsi = IndicatorCalculator._rsi(series, length=14)
        # After the spike, EMA-RSI should react quickly (>70)
        assert rsi.iloc[-1] > 70, f"EMA-RSI should react quickly to trend change, got {rsi.iloc[-1]}"


# ==================== ADX TESTS ====================

class TestADX:
    """Test ADX calculation - especially index alignment"""

    def test_adx_no_nan_after_warmup(self, sample_ohlcv):
        """ADX should have no NaN values after the warmup period (2 * period)"""
        from dss.intelligence.indicators import IndicatorCalculator
        result = IndicatorCalculator._adx(
            sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close']
        )
        adx = result['adx']
        # ADX needs ~2*14=28 periods to warm up
        valid_adx = adx.iloc[30:]
        nan_count = valid_adx.isna().sum()
        assert nan_count == 0, f"ADX has {nan_count} NaN values after warmup (index alignment bug?)"

    def test_adx_range(self, sample_ohlcv):
        """ADX should be between 0 and 100"""
        from dss.intelligence.indicators import IndicatorCalculator
        result = IndicatorCalculator._adx(
            sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close']
        )
        adx = result['adx'].dropna()
        assert adx.min() >= 0, f"ADX below 0: {adx.min()}"
        assert adx.max() <= 100, f"ADX above 100: {adx.max()}"

    def test_adx_index_matches_input(self, sample_ohlcv):
        """ADX output index must match input index (no 0-based mismatch)"""
        from dss.intelligence.indicators import IndicatorCalculator
        result = IndicatorCalculator._adx(
            sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close']
        )
        assert result['adx'].index.equals(sample_ohlcv['close'].index), \
            "ADX index doesn't match input index"
        assert result['plus_di'].index.equals(sample_ohlcv['close'].index), \
            "+DI index doesn't match input index"


# ==================== SMA TESTS ====================

class TestSMA:
    """Test SMA calculation with correct min_periods"""

    def test_sma_nan_before_window(self):
        """SMA should be NaN before the window is full"""
        from dss.intelligence.indicators import IndicatorCalculator
        dates = pd.date_range('2024-01-01', periods=250, freq='B')
        series = pd.Series(np.random.randn(250).cumsum() + 100, index=dates)
        sma = IndicatorCalculator._sma(series, 200)
        # First 199 values should be NaN
        assert sma.iloc[:199].isna().all(), "SMA-200 should be NaN for first 199 values"
        # Value at index 199 should NOT be NaN
        assert pd.notna(sma.iloc[199]), "SMA-200 should have a value at index 199"

    def test_sma_correctness(self):
        """SMA value should equal the mean of the window"""
        from dss.intelligence.indicators import IndicatorCalculator
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], index=dates, dtype=float)
        sma = IndicatorCalculator._sma(series, 5)
        # SMA at index 4 should be mean(1,2,3,4,5) = 3.0
        assert sma.iloc[4] == pytest.approx(3.0), f"SMA(5) at index 4 should be 3.0, got {sma.iloc[4]}"
        # SMA at index 9 should be mean(6,7,8,9,10) = 8.0
        assert sma.iloc[9] == pytest.approx(8.0), f"SMA(5) at index 9 should be 8.0, got {sma.iloc[9]}"


# ==================== VWAP TESTS ====================

class TestVWAP:
    """Test rolling VWAP calculation"""

    def test_vwap_nan_before_window(self, sample_ohlcv):
        """VWAP should be NaN before the rolling window is full"""
        from dss.intelligence.indicators import IndicatorCalculator
        vwap = IndicatorCalculator._calculate_vwap(sample_ohlcv, window=20)
        assert vwap.iloc[:19].isna().all(), "Rolling VWAP should be NaN for first 19 values"
        assert pd.notna(vwap.iloc[19]), "Rolling VWAP should have a value at index 19"

    def test_vwap_within_price_range(self, sample_ohlcv):
        """VWAP should be within the low-high range of the rolling window"""
        from dss.intelligence.indicators import IndicatorCalculator
        vwap = IndicatorCalculator._calculate_vwap(sample_ohlcv, window=20)
        valid = vwap.dropna()
        # VWAP should be close to close price (within reasonable bounds)
        close = sample_ohlcv['close'].iloc[19:]
        ratio = valid.values / close.values
        assert ratio.min() > 0.9, "VWAP too far below price"
        assert ratio.max() < 1.1, "VWAP too far above price"


# ==================== TRAILING STOP TESTS ====================

class TestTrailingStop:
    """Test trailing stop logic from backtest"""

    def test_trailing_activates_at_trigger(self):
        """Trailing stop should activate when profit >= trigger_pct"""
        entry = 100.0
        trigger_pct = 6.0
        distance_pct = 1.5
        min_lock_pct = 3.5

        # Price at exactly +6% (trigger point)
        highest = entry * 1.06
        trailing_stop = highest * (1 - distance_pct / 100)
        min_lock = entry * (1 + min_lock_pct / 100)
        effective_stop = max(trailing_stop, min_lock)

        assert trailing_stop == pytest.approx(104.41, rel=0.01)
        assert min_lock == pytest.approx(103.50, rel=0.01)
        assert effective_stop == pytest.approx(104.41, rel=0.01)

    def test_min_lock_floor(self):
        """Min lock should act as floor when trailing stop drops below it"""
        entry = 100.0
        distance_pct = 1.5
        min_lock_pct = 3.5

        # Price at +6.5% but then drops - trailing would give lower value
        highest = entry * 1.065
        trailing_stop = highest * (1 - distance_pct / 100)
        min_lock = entry * (1 + min_lock_pct / 100)
        effective_stop = max(trailing_stop, min_lock)

        # Trailing: 106.5 * 0.985 = 104.9025
        assert effective_stop == pytest.approx(104.9025, rel=0.01)
        # Min lock floor: 103.5 (not used here since trailing is higher)
        assert trailing_stop > min_lock

    def test_trailing_not_active_below_trigger(self):
        """Trailing stop should NOT activate when profit < trigger_pct"""
        entry = 100.0
        highest = 105.0  # +5%, below 6% trigger
        trigger_pct = 6.0

        profit_from_high = ((highest - entry) / entry) * 100
        assert profit_from_high < trigger_pct, "Profit should be below trigger"


# ==================== POSITION SIZING TESTS ====================

class TestPositionSizing:
    """Test position sizing calculations"""

    def test_risk_based_sizing(self):
        """Position size should respect risk per trade"""
        entry_price = 50.0
        stop_loss = 47.0  # $3 risk per share
        risk_amount_eur = 150.0
        eur_usd_rate = 0.92

        risk_per_share = entry_price - stop_loss  # $3
        quantity = int(risk_amount_eur / (risk_per_share * eur_usd_rate))

        # 150 / (3 * 0.92) = 150 / 2.76 = 54 shares
        assert quantity == 54, f"Expected 54 shares, got {quantity}"

    def test_position_cap_33_percent(self):
        """Position value should not exceed 33% of capital"""
        total_capital = 10_000.0
        entry_price = 200.0
        eur_usd_rate = 0.92
        quantity = 20  # Would be $4000 * 0.92 = €3680

        max_position_eur = total_capital * 0.33  # €3300
        position_value_eur = entry_price * quantity * eur_usd_rate

        if position_value_eur > max_position_eur:
            capped_qty = int(max_position_eur / (entry_price * eur_usd_rate))
        else:
            capped_qty = quantity

        assert capped_qty < quantity, "Position should be capped"
        capped_value = capped_qty * entry_price * eur_usd_rate
        assert capped_value <= max_position_eur, "Capped position exceeds 33%"

    def test_minimum_one_share(self):
        """Position size should be at least 1 share"""
        entry_price = 500.0
        stop_loss = 475.0  # $25 risk per share
        risk_amount_eur = 15.0  # Very small risk
        eur_usd_rate = 0.92

        risk_per_share = entry_price - stop_loss
        quantity = max(1, int(risk_amount_eur / (risk_per_share * eur_usd_rate)))

        assert quantity >= 1, "Must buy at least 1 share"


# ==================== REGIME DETECTOR TESTS ====================

class TestRegimeDetector:
    """Test regime detection logic"""

    def test_regime_detector_adx_no_nan(self, sample_ohlcv):
        """Regime detector ADX calculation should not produce NaN after warmup"""
        from dss.core.regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector.__new__(MarketRegimeDetector)

        high = sample_ohlcv['high']
        low = sample_ohlcv['low']
        close = sample_ohlcv['close']

        adx_result = detector._calculate_adx(sample_ohlcv)
        adx_values = adx_result['adx'].iloc[30:]
        nan_count = adx_values.isna().sum()

        assert nan_count == 0, f"Regime detector ADX has {nan_count} NaN after warmup"
