"""
DEPRECATED - Moved to dss.intelligence.legacy.scoring

For new code, use dss.core.portfolio_manager.PortfolioManager instead.
This file exists only for backward compatibility.
"""
import warnings
warnings.warn(
    "dss.intelligence.scoring is deprecated. "
    "Legacy import moved to dss.intelligence.legacy.scoring",
    DeprecationWarning,
    stacklevel=2
)
from .legacy.scoring import SignalScorer

__all__ = ['SignalScorer']
