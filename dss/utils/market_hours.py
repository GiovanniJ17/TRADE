"""
Market Hours Utilities
Per Code Review Issue #8: Check if US market is currently open

US Market Hours (NYSE/NASDAQ):
- Regular Session: 9:30 AM - 4:00 PM Eastern Time
- Pre-Market: 4:00 AM - 9:30 AM ET
- After-Hours: 4:00 PM - 8:00 PM ET

Note: Trade Republic trades via MIC exchange, but US stocks follow NYSE hours.
"""
from datetime import datetime, time, timedelta
from typing import Dict, Optional
import pytz
from loguru import logger


# US Eastern Timezone
ET = pytz.timezone('US/Eastern')

# Market hours (Eastern Time)
MARKET_OPEN = time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET

# Pre-market and after-hours
PREMARKET_OPEN = time(4, 0)   # 4:00 AM ET
AFTERHOURS_CLOSE = time(20, 0)  # 8:00 PM ET

# US Market Holidays 2024-2026 (approximate - should be updated yearly)
US_MARKET_HOLIDAYS = [
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # MLK Day
    "2024-02-19",  # Presidents Day
    "2024-03-29",  # Good Friday
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving
    "2024-12-25",  # Christmas
    # 2025
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # MLK Day
    "2025-02-17",  # Presidents Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving
    "2025-12-25",  # Christmas
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
]


def is_market_open(check_time: Optional[datetime] = None) -> bool:
    """
    Check if US stock market is currently open (regular session).
    
    Args:
        check_time: Optional datetime to check (defaults to now)
        
    Returns:
        True if market is in regular session, False otherwise
    """
    if check_time is None:
        check_time = datetime.now(ET)
    elif check_time.tzinfo is None:
        # Assume local time, convert to ET
        check_time = ET.localize(check_time)
    else:
        check_time = check_time.astimezone(ET)
    
    # Weekend check (Monday=0, Sunday=6)
    if check_time.weekday() >= 5:  # Saturday or Sunday
        return False
    
    # Holiday check
    date_str = check_time.strftime("%Y-%m-%d")
    if date_str in US_MARKET_HOLIDAYS:
        return False
    
    # Hours check
    current_time = check_time.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_extended_hours_open(check_time: Optional[datetime] = None) -> bool:
    """
    Check if pre-market or after-hours trading is available.
    
    Note: Trade Republic may not support extended hours for all stocks.
    
    Args:
        check_time: Optional datetime to check (defaults to now)
        
    Returns:
        True if in pre-market or after-hours session
    """
    if check_time is None:
        check_time = datetime.now(ET)
    elif check_time.tzinfo is None:
        check_time = ET.localize(check_time)
    else:
        check_time = check_time.astimezone(ET)
    
    # Weekend check
    if check_time.weekday() >= 5:
        return False
    
    # Holiday check
    date_str = check_time.strftime("%Y-%m-%d")
    if date_str in US_MARKET_HOLIDAYS:
        return False
    
    current_time = check_time.time()
    
    # Pre-market: 4:00 AM - 9:30 AM
    in_premarket = PREMARKET_OPEN <= current_time < MARKET_OPEN
    
    # After-hours: 4:00 PM - 8:00 PM
    in_afterhours = MARKET_CLOSE < current_time <= AFTERHOURS_CLOSE
    
    return in_premarket or in_afterhours


def get_market_status(check_time: Optional[datetime] = None) -> Dict:
    """
    Get detailed market status information.
    
    Args:
        check_time: Optional datetime to check (defaults to now)
        
    Returns:
        Dict with:
            - is_open: bool - regular session open
            - is_extended_hours: bool - pre/after hours open
            - status: str - 'open', 'pre-market', 'after-hours', 'closed'
            - next_open: datetime|None - when market opens next
            - time_until_open: str|None - human-readable time until open
            - reason: str - explanation (e.g., 'Weekend', 'Holiday', etc.)
    """
    if check_time is None:
        check_time = datetime.now(ET)
    elif check_time.tzinfo is None:
        check_time = ET.localize(check_time)
    else:
        check_time = check_time.astimezone(ET)
    
    result = {
        'is_open': False,
        'is_extended_hours': False,
        'status': 'closed',
        'next_open': None,
        'time_until_open': None,
        'reason': None,
        'current_time_et': check_time.strftime("%Y-%m-%d %H:%M ET")
    }
    
    # Weekend check
    if check_time.weekday() >= 5:
        days_until_monday = (7 - check_time.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_open = check_time.replace(hour=9, minute=30, second=0, microsecond=0)
        next_open = next_open + timedelta(days=days_until_monday)
        result['next_open'] = next_open
        result['time_until_open'] = _format_time_delta(next_open - check_time)
        result['reason'] = 'Weekend'
        return result
    
    # Holiday check
    date_str = check_time.strftime("%Y-%m-%d")
    if date_str in US_MARKET_HOLIDAYS:
        # Find next trading day
        next_day = check_time + timedelta(days=1)
        while (next_day.weekday() >= 5 or 
               next_day.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS):
            next_day = next_day + timedelta(days=1)
        next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
        result['next_open'] = next_open
        result['time_until_open'] = _format_time_delta(next_open - check_time)
        result['reason'] = 'Market Holiday'
        return result
    
    current_time = check_time.time()
    
    # Check session
    if MARKET_OPEN <= current_time <= MARKET_CLOSE:
        result['is_open'] = True
        result['status'] = 'open'
        result['reason'] = 'Regular Session'
        
    elif PREMARKET_OPEN <= current_time < MARKET_OPEN:
        result['is_extended_hours'] = True
        result['status'] = 'pre-market'
        result['reason'] = 'Pre-Market Session'
        # Time until regular open
        next_open = check_time.replace(hour=9, minute=30, second=0, microsecond=0)
        result['next_open'] = next_open
        result['time_until_open'] = _format_time_delta(next_open - check_time)
        
    elif MARKET_CLOSE < current_time <= AFTERHOURS_CLOSE:
        result['is_extended_hours'] = True
        result['status'] = 'after-hours'
        result['reason'] = 'After-Hours Session'
        # Next open is tomorrow (or Monday)
        next_day = check_time + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day = next_day + timedelta(days=1)
        next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
        result['next_open'] = next_open
        result['time_until_open'] = _format_time_delta(next_open - check_time)
        
    else:
        result['status'] = 'closed'
        # Before pre-market or after after-hours
        if current_time < PREMARKET_OPEN:
            # Early morning - today's pre-market
            next_open = check_time.replace(hour=4, minute=0, second=0, microsecond=0)
            result['reason'] = 'Before Pre-Market'
        else:
            # After 8 PM - tomorrow
            next_day = check_time + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day = next_day + timedelta(days=1)
            next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
            result['reason'] = 'After Extended Hours'
        
        result['next_open'] = next_open
        result['time_until_open'] = _format_time_delta(next_open - check_time)
    
    return result


def _format_time_delta(delta: timedelta) -> str:
    """Format timedelta as human-readable string."""
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 24:
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def warn_if_market_closed(context: str = "signal generation") -> bool:
    """
    Log a warning if market is closed.
    
    Args:
        context: Description of what's being done (for logging)
        
    Returns:
        True if market is closed (warning was logged)
    """
    status = get_market_status()
    
    if not status['is_open'] and not status['is_extended_hours']:
        logger.warning(
            f"⚠️ Market is {status['status'].upper()} ({status['reason']}) - "
            f"{context} may use stale prices. "
            f"Next open: {status['time_until_open']}"
        )
        return True
    
    return False


# For backward compatibility and convenience
from datetime import timedelta
