"""
DEPRECATED - Moved to dss.intelligence.legacy.screening

For new code, use dss.core.portfolio_manager.PortfolioManager instead.
This file exists only for backward compatibility.
"""
import warnings
warnings.warn(
    "dss.intelligence.screening is deprecated. "
    "Legacy import moved to dss.intelligence.legacy.screening",
    DeprecationWarning,
    stacklevel=2
)
from .legacy.screening import StockScreener

__all__ = ['StockScreener']
