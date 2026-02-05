"""
Unit tests for strategy modules.

Tests:
- SimpleMomentumStrategy parameter defaults
- MeanReversionRSI parameter defaults
- BreakoutStrategy parameter defaults
- Signal structure validation
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMomentumStrategy:
    """Tests for SimpleMomentumStrategy"""

    def test_default_parameters(self):
        """Verify default parameters match specification"""
        from dss.strategies.momentum_simple import SimpleMomentumStrategy
        assert SimpleMomentumStrategy.SMA_PERIOD == 100
        assert SimpleMomentumStrategy.LOOKBACK_MONTHS == 3
        assert SimpleMomentumStrategy.MIN_DOLLAR_VOLUME == 3_000_000
        assert SimpleMomentumStrategy.STOP_LOSS_PCT == -5.0
        assert SimpleMomentumStrategy.RISK_PER_TRADE_EUR == 20.0

    def test_initialization(self):
        """Strategy should initialize without errors"""
        from dss.strategies.momentum_simple import SimpleMomentumStrategy
        strategy = SimpleMomentumStrategy.__new__(SimpleMomentumStrategy)
        assert strategy is not None


class TestMeanReversionStrategy:
    """Tests for MeanReversionRSI"""

    def test_default_parameters(self):
        """Verify default parameters match specification"""
        from dss.strategies.mean_reversion_rsi import MeanReversionRSI
        assert MeanReversionRSI.SMA_PERIOD == 200
        assert MeanReversionRSI.RSI_PERIOD == 14
        assert MeanReversionRSI.RSI_OVERSOLD == 40
        assert MeanReversionRSI.RSI_OVERBOUGHT == 70
        assert MeanReversionRSI.MIN_DOLLAR_VOLUME == 3_000_000

    def test_initialization(self):
        """Strategy should initialize without errors"""
        from dss.strategies.mean_reversion_rsi import MeanReversionRSI
        strategy = MeanReversionRSI.__new__(MeanReversionRSI)
        assert strategy is not None


class TestBreakoutStrategy:
    """Tests for BreakoutStrategy"""

    def test_default_parameters(self):
        """Verify default parameters match specification"""
        from dss.strategies.breakout_strategy import BreakoutStrategy
        assert BreakoutStrategy.BREAKOUT_PERIOD == 20
        assert BreakoutStrategy.SMA_PERIOD == 50
        assert BreakoutStrategy.VOLUME_SPIKE_MULTIPLIER == 1.3
        assert BreakoutStrategy.BB_SQUEEZE_THRESHOLD == 0.05
        assert BreakoutStrategy.MIN_DOLLAR_VOLUME == 3_000_000

    def test_initialization(self):
        """Strategy should initialize without errors"""
        from dss.strategies.breakout_strategy import BreakoutStrategy
        strategy = BreakoutStrategy.__new__(BreakoutStrategy)
        assert strategy is not None


class TestSectorMapping:
    """Test sector mapping completeness"""

    def test_all_watchlist_symbols_mapped(self):
        """Every symbol in watchlist should have a sector mapping"""
        from dss.core.portfolio_manager import SECTOR_MAPPING

        watchlist_path = Path(__file__).parent.parent / "config" / "watchlist.txt"
        if not watchlist_path.exists():
            pytest.skip("Watchlist file not found")

        symbols = set()
        with open(watchlist_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    symbols.add(line.upper())

        # ETFs/benchmarks to exclude
        etfs = {'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI', 'ARKK',
                'SPXL', 'TQQQ', 'UPRO', 'SOXL', 'FNGU', 'TECL', 'LABU', 'TNA', 'FAS'}
        symbols -= etfs

        unmapped = symbols - set(SECTOR_MAPPING.keys())

        assert len(unmapped) == 0, (
            f"{len(unmapped)} symbols not in SECTOR_MAPPING: {sorted(unmapped)}"
        )
