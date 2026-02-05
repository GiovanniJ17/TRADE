"""
DEPRECATED - Moved to dss.intelligence.legacy.signal_generator

For new code, use dss.core.portfolio_manager.PortfolioManager instead.
This file exists only for backward compatibility.
"""
import warnings
warnings.warn(
    "dss.intelligence.signal_generator is deprecated. "
    "Use dss.core.portfolio_manager.PortfolioManager instead. "
    "Legacy import moved to dss.intelligence.legacy.signal_generator",
    DeprecationWarning,
    stacklevel=2
)
from .legacy.signal_generator import SignalGenerator

__all__ = ['SignalGenerator']
